"""n03: Excel workbooks for the two human labellers, and read-back of the filled files.

Build (system Python has openpyxl):
  python research2/n03_annotation_workbook.py build --tag 2026-11-15
    -> annotation/nv_labels_A1.xlsx, annotation/nv_labels_A2.xlsx (same 100 items, same order,
       no LLM scores, no click data), results/n03_workbooks_<tag>.json (hashes only)

Read back a filled workbook (validates every cell, writes a CSV next to it):
  python research2/n03_annotation_workbook.py read annotation/nv_labels_A1.xlsx
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from nv_common import ANNOT, DATA, RESULTS, ROOT, VALUES, read_jsonl, sha256_file, write_json

FIXED = ["item", "news_id", "headline", "abstract"]
HEADER = FIXED + VALUES + ["done", "notes"]
FIRST_SCORE_COL = len(FIXED) + 1                       # E
LAST_SCORE_COL = len(FIXED) + len(VALUES)              # K


def col(n: int) -> str:
    return chr(ord("A") + n - 1)


def instructions_rows() -> list:
    rows = []
    for line in (ROOT / "CODEBOOK.md").read_text(encoding="utf-8").splitlines():
        line = line.replace("**", "").rstrip()
        if line.startswith("|---"):
            continue
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        else:
            rows.append([line.lstrip("# ")])
    return rows


def build(tag: str) -> None:
    sample = __import__("json").loads((DATA / "human_sample.json").read_text(encoding="utf-8"))
    arts = {r["id"]: r for r in read_jsonl(DATA / "articles_to_score.jsonl")}
    ids = sample["ids"]
    ANNOT.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for who in ("A1", "A2"):
        wb = Workbook()
        ins = wb.active
        ins.title = "Instructions"
        ins.append([f"Labeller {who}. Read this sheet first, then fill the 'Labels' sheet."])
        ins["A1"].font = Font(bold=True, size=12)
        for r in instructions_rows():
            ins.append(r)
        for c, w in zip("ABCDE", (16, 60, 28, 34, 40)):
            ins.column_dimensions[c].width = w
        for row in ins.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        ws = wb.create_sheet("Labels")
        ws.append(HEADER)
        head_fill = PatternFill("solid", fgColor="DDEBF7")
        for cell in ws[1]:
            cell.font = Font(bold=True)
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        score_fill = PatternFill("solid", fgColor="FFF9E5")
        for i, nid in enumerate(ids, start=1):
            a = arts[nid]
            r = i + 1
            ws.append([i, nid, a["title"], a["abstract"] or "(none)"] + [None] * len(VALUES)
                      + [f'=IF(COUNT({col(FIRST_SCORE_COL)}{r}:{col(LAST_SCORE_COL)}{r})={len(VALUES)},"✓","")', None])
            for c in range(1, len(HEADER) + 1):
                ws.cell(r, c).alignment = Alignment(wrap_text=True, vertical="top",
                                                    horizontal="center" if FIRST_SCORE_COL <= c <= LAST_SCORE_COL + 1 else None)
            for c in range(FIRST_SCORE_COL, LAST_SCORE_COL + 1):
                ws.cell(r, c).fill = score_fill
        dv = DataValidation(type="whole", operator="between", formula1="1", formula2="5", allow_blank=True,
                            showErrorMessage=True, errorTitle="Score 1-5", error="Enter a whole number from 1 to 5.")
        ws.add_data_validation(dv)
        dv.add(f"{col(FIRST_SCORE_COL)}2:{col(LAST_SCORE_COL)}{len(ids) + 1}")
        widths = {"A": 6, "B": 9, "C": 42, "D": 70, "L": 6, "M": 30}
        for c in range(FIRST_SCORE_COL, LAST_SCORE_COL + 1):
            widths[col(c)] = 12
        for c, w in widths.items():
            ws.column_dimensions[c].width = w
        ws.freeze_panes = f"{col(FIRST_SCORE_COL)}2"
        wb.active = 1
        out = ANNOT / f"nv_labels_{who}.xlsx"
        wb.save(out)
        hashes[f"annotation/{out.name}"] = sha256_file(out)
        print("wrote", out)
    write_json(RESULTS / f"n03_workbooks_{tag}.json", {
        "meta": {"script": "research2/n03_annotation_workbook.py", "tag": tag,
                 "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        "n_items": len(ids), "sample_sha256": sha256_file(DATA / "human_sample.json"),
        "codebook_sha256": sha256_file(ROOT / "CODEBOOK.md"), "workbooks": hashes})


def read(path: Path) -> None:
    sample = __import__("json").loads((DATA / "human_sample.json").read_text(encoding="utf-8"))
    ws = load_workbook(path, data_only=False)["Labels"]
    rows = list(ws.iter_rows(min_row=1, values_only=True))
    assert list(rows[0][:len(HEADER)]) == HEADER, f"header changed: {rows[0]}"
    problems, out = [], []
    for i, r in enumerate(rows[1:], start=1):
        if r[1] is None:
            continue
        nid = r[1]
        if i > len(sample["ids"]) or sample["ids"][i - 1] != nid:
            problems.append(f"row {i + 1}: id {nid} out of order")
        rec = {"item": r[0], "news_id": nid}
        for k, v in zip(VALUES, r[FIRST_SCORE_COL - 1:LAST_SCORE_COL]):
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            if not isinstance(v, int) or not 1 <= v <= 5:
                problems.append(f"item {r[0]} ({nid}) {k}: {v!r}")
                v = None
            rec[k] = v
        rec["notes"] = r[LAST_SCORE_COL + 1] or ""
        out.append(rec)
    if len(out) != len(sample["ids"]):
        problems.append(f"{len(out)} rows, expected {len(sample['ids'])}")
    csv_path = path.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["item", "news_id"] + VALUES + ["notes"])
        w.writeheader()
        w.writerows(out)
    print(f"{path.name}: {len(out)} rows -> {csv_path.name}; {len(problems)} problem(s)")
    for p in problems[:50]:
        print("  ", p)
    sys.exit(1 if problems else 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--tag", required=True)
    r = sub.add_parser("read")
    r.add_argument("path", type=Path)
    args = ap.parse_args()
    build(args.tag) if args.cmd == "build" else read(args.path)


if __name__ == "__main__":
    main()
