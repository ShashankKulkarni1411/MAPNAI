"""
MAPNAI — personalization/push.py
Push notifications through Expo's push service (continousexplanation.md §5.10).

  send      POST https://exp.host/--/api/v2/push/send with up to 100 messages; the answer is one *ticket* per
            message, in order: {"status": "ok", "id": …} or {"status": "error", "message": …, "details": {"error": …}}.
            A ticket only means Expo accepted the message.
  receipts  ~15 minutes later, POST …/push/getReceipts {"ids": [ticket ids]} → {"data": {id: {"status": …}}}: whether
            Apple / Google accepted it. "DeviceNotRegistered" (in a ticket or a receipt) means the app is gone from
            that device: the token is deactivated.

Message building and response reading are pure; ExpoPushClient does the HTTP (requests; the session is injectable).
"""

import re
from typing import Dict, Iterable, List, Optional, Sequence

from utils.logger import logger

TOKEN_RE = re.compile(r"^Expo(nent)?PushToken\[[^\]]+\]$")
DEVICE_GONE = "DeviceNotRegistered"
CHANNEL = "alerts"          # the Android notification channel the app creates (mobile/src/lib/push.ts)


def valid_token(token: str) -> bool:
    return bool(TOKEN_RE.match(str(token or "").strip()))


def alert_title(alert: Dict) -> str:
    """The notification's title: 'Breaking: …' for breaking alerts, '<who it's about>: …' for exposure alerts."""
    title = (alert.get("title") or "").strip() or "News for you"
    kind = alert.get("kind") or "exposure"
    if kind in ("breaking_for_you", "breaking_global"):
        return f"Breaking: {title}"
    who = alert.get("entity_name") or ""
    return f"{who}: {title}" if who and who.lower() not in title.lower() else title


def build_message(alert: Dict, token: str) -> Dict:
    """One Expo push message for one alert and one device token. Tapping it opens the story (data.article_id)."""
    return {
        "to": token,
        "title": alert_title(alert)[:178],
        "body": (alert.get("explanation") or "").strip()[:240],
        "data": {"article_id": alert.get("article_id"), "alert_id": alert.get("alert_id"),
                 "kind": alert.get("kind") or "exposure", "cluster_id": alert.get("cluster_id")},
        "sound": "default",
        "priority": "high",
        "channelId": CHANNEL,
    }


def chunks(items: Sequence, size: int) -> Iterable[List]:
    size = max(1, int(size))
    for i in range(0, len(items), size):
        yield list(items[i:i + size])


def ticket_error(ticket: Optional[Dict]) -> Optional[str]:
    """The error code of a ticket or receipt ('DeviceNotRegistered', 'MessageTooBig', …), None when it is ok."""
    if not ticket or ticket.get("status") == "ok":
        return None
    return ((ticket.get("details") or {}).get("error")) or ticket.get("message") or "error"


class ExpoPushClient:
    def __init__(self, cfg, session=None):
        self.cfg = cfg
        self._session = session

    @property
    def session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def _headers(self) -> Dict[str, str]:
        h = {"Accept": "application/json", "Accept-Encoding": "gzip, deflate", "Content-Type": "application/json"}
        if self.cfg.push_access_token:
            h["Authorization"] = f"Bearer {self.cfg.push_access_token}"
        return h

    def send(self, messages: Sequence[Dict]) -> List[Dict]:
        """One ticket per message, in order. A failed request gives an error ticket for each of its messages."""
        tickets: List[Dict] = []
        for batch in chunks(list(messages), self.cfg.push_batch):
            try:
                resp = self.session.post(self.cfg.push_url, json=batch, headers=self._headers(),
                                         timeout=self.cfg.push_timeout_s)
                body = resp.json() if resp.content else {}
                data = body.get("data")
                if resp.status_code >= 400 or not isinstance(data, list) or len(data) != len(batch):
                    reason = (body.get("errors") or [{}])[0].get("message") if isinstance(body, dict) else None
                    raise RuntimeError(f"HTTP {resp.status_code}: {reason or 'unexpected response'}")
                tickets.extend(data)
            except Exception as e:
                logger.warning(f"[Push] send failed for {len(batch)} messages: {e}")
                tickets.extend({"status": "error", "message": str(e)[:200], "details": {"error": "RequestFailed"}}
                               for _ in batch)
        return tickets

    def receipts(self, ids: Sequence[str]) -> Dict[str, Dict]:
        """{ticket id: receipt}; ids Expo doesn't know yet (or a failed request) are simply missing."""
        out: Dict[str, Dict] = {}
        for batch in chunks(list(ids), 1000):
            try:
                resp = self.session.post(self.cfg.push_receipts_url, json={"ids": batch}, headers=self._headers(),
                                         timeout=self.cfg.push_timeout_s)
                data = (resp.json() or {}).get("data") or {}
                if isinstance(data, dict):
                    out.update(data)
            except Exception as e:
                logger.warning(f"[Push] receipts failed for {len(batch)} tickets: {e}")
        return out
