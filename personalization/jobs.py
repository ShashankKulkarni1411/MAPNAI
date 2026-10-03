"""
MAPNAI — personalization/jobs.py
Personalization jobs. Each run is recorded in `job_runs` and holds a lease, so two workers (or a manual run
during a scheduled one) never run the same job at once. build_scheduler() registers the six periodic jobs on an
APScheduler BackgroundScheduler (cron in PERS_TZ); the API starts it in its lifespan (PERS_SCHEDULER_ENABLED).
An empty cron string (e.g. PERS_JOB_ALERTS="") leaves that job unscheduled.

    python -m personalization.jobs cluster
    python -m personalization.jobs recluster          # one-off, after a clustering rule change
    python -m personalization.jobs pi_topk [--user USER_ID ...]
    python -m personalization.jobs digests [--user USER_ID ...]
    python -m personalization.jobs tau
    python -m personalization.jobs proposals [--user USER_ID ...]
    python -m personalization.jobs alerts [--rescan]
"""

import argparse
import json
import sys
import traceback
from typing import Callable, Dict, List, Optional

from utils.logger import logger


def job_cluster(svc) -> Dict:
    """Hourly: name_lower → entity_keys → pers FAISS sync → clustering → materiality (new + rescore)."""
    return svc.cluster_articles()


def job_recluster(svc) -> Dict:
    """One-off (not scheduled): recluster the whole window after a clustering rule/threshold change."""
    return svc.recluster_window()


def job_pi_topk(svc, user_ids: Optional[List[str]] = None) -> Dict:
    """Nightly (and after exposure edits, per user): recompute every persona's pi_topk."""
    ok, failed = 0, {}
    for user_id in user_ids or svc.personas.all_ids():
        try:
            svc.compute_pi(user_id)
            ok += 1
        except Exception as e:
            failed[user_id] = f"{type(e).__name__}: {e}"
            logger.error(f"[Jobs] pi_topk failed for {user_id}: {e}")
    return {"users": ok, "failed": failed}


def job_digests(svc, user_ids: Optional[List[str]] = None) -> Dict:
    """Daily 05:30: precompute and cache today's digest per user. No impressions (those are logged per serve)."""
    ok, failed, items = 0, {}, 0
    for user_id in user_ids or svc.personas.all_ids():
        try:
            digest = svc.compute_digest(user_id)
            svc.logs.put_digest(digest)
            ok += 1
            items += len(digest["items"])
        except Exception as e:
            failed[user_id] = f"{type(e).__name__}: {e}"
            logger.error(f"[Jobs] digest failed for {user_id}: {e}")
    return {"users": ok, "items": items, "failed": failed}


def job_tau(svc) -> Dict:
    """Daily 02:30: one adaptive step of the must_know threshold τ from the last week's needed/missed feedback."""
    return svc.update_tau()


def job_proposals(svc, user_ids: Optional[List[str]] = None) -> Dict:
    """Weekly Mon 03:00: suggest exposures from engagement (and A4 facts when a4_facts_field is set)."""
    return svc.run_proposals(user_ids)


def job_alerts(svc, rescan: bool = False) -> Dict:
    """Every 5 min: alert users about material articles on their exposures (rescan: the whole window again)."""
    return svc.run_alerts(rescan=rescan)


JOBS: Dict[str, Callable] = {"cluster": job_cluster, "recluster": job_recluster, "pi_topk": job_pi_topk,
                             "digests": job_digests, "tau": job_tau, "proposals": job_proposals,
                             "alerts": job_alerts}
PER_USER = ("pi_topk", "digests", "proposals")


def run_job(svc, name: str, **kwargs) -> Dict:
    """Run one job under a job_runs lease. Returns {job, run_id, ok, stats|error} or {skipped: True}."""
    if name not in JOBS:
        raise ValueError(f"unknown job {name!r}; one of {sorted(JOBS)}")
    run_id = svc.logs.job_start(name, svc.clock())
    if run_id is None:
        logger.warning(f"[Jobs] {name} is already running (lease held); skipped")
        return {"job": name, "skipped": True}
    try:
        stats = JOBS[name](svc, **kwargs)
        svc.logs.job_finish(run_id, svc.clock(), ok=True, stats=stats)
        logger.info(f"[Jobs] {name} ok: {stats}")
        return {"job": name, "run_id": run_id, "ok": True, "stats": stats}
    except Exception as e:
        svc.logs.job_finish(run_id, svc.clock(), ok=False, error=f"{type(e).__name__}: {e}")
        logger.error(f"[Jobs] {name} failed: {e}\n{traceback.format_exc()}")
        return {"job": name, "run_id": run_id, "ok": False, "error": f"{type(e).__name__}: {e}"}


# job name → the config field holding its cron expression (recluster is manual only)
SCHEDULED: Dict[str, str] = {"pi_topk": "job_pi_topk", "cluster": "job_cluster", "alerts": "job_alerts",
                             "tau": "job_tau", "proposals": "job_proposals", "digests": "job_digests"}


def schedule_table(cfg) -> Dict[str, str]:
    """{job: cron} for every scheduled job whose cron isn't empty."""
    return {name: getattr(cfg, field).strip() for name, field in SCHEDULED.items() if getattr(cfg, field).strip()}


def build_scheduler(svc, cfg=None):
    """
    A BackgroundScheduler (not started) with one CronTrigger job per non-empty cron in schedule_table, in cfg.tz.
    Each fire goes through run_job, so the job_runs lease still guards against a second worker; overlapping fires
    in this process are dropped (max_instances=1) and missed fires collapse into one run (coalesce).
    """
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    cfg = cfg or svc.cfg
    scheduler = BackgroundScheduler(timezone=cfg.tz)
    for name, cron in schedule_table(cfg).items():
        scheduler.add_job(run_job, CronTrigger.from_crontab(cron, timezone=cfg.tz), args=[svc, name], id=name,
                          name=f"pers:{name}", max_instances=1, coalesce=True, misfire_grace_time=300,
                          replace_existing=True)
    return scheduler


def scheduler_status(scheduler) -> Dict:
    """{running, jobs: {name: {cron trigger, next_run}}} for health and /admin/jobs; None → not running."""
    if scheduler is None:
        return {"running": False, "jobs": {}}
    return {
        "running": bool(scheduler.running),
        # next_run_time only exists once the scheduler has started
        "jobs": {job.id: {"trigger": str(job.trigger), "next_run": getattr(job, "next_run_time", None)}
                 for job in scheduler.get_jobs()},
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run one personalization job once")
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--user", action="append", dest="users", help=f"{' / '.join(PER_USER)} only; repeatable")
    parser.add_argument("--rescan", action="store_true", help="alerts only: evaluate the whole window again")
    args = parser.parse_args(argv)

    from personalization.service import PersonalizationService
    kwargs = {"user_ids": args.users} if args.job in PER_USER and args.users else {}
    if args.job == "alerts" and args.rescan:
        kwargs["rescan"] = True
    result = run_job(PersonalizationService(), args.job, **kwargs)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("ok") or result.get("skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
