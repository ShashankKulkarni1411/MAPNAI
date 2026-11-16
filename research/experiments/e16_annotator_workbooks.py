"""
E16: annotator workbooks for the two-annotator S4 design (research/PREREG.md §8, restored by §11).

Reads   research/annotation/export/{pilot,main}_{A1,A2}_<tag>.csv   (from e12; blind, no key columns)
Writes  research/annotation/export/to_annotators/<A1|A2>/{pilot,main}_<A>_<tag>.xlsx   (git-ignored)

Same items, same order, same label columns as the CSVs. Each label row is PRE-FILLED with the
"nothing wrong" defaults (addition 0, distortion 0, distortion_type blank, omission none,
faithful 1). `confidence` is left blank on purpose and is required on every row: it is the
annotator's mark that the row was read, so untouched rows can be told apart from real
"faithful" judgments (PREREG §11). Cells changed away from the default are highlighted.

Read back with  --to-csv FILLED.xlsx  to get  <sheet>_filled.csv  (item_id + labels, in the
CSV's order). The read-back refuses a file whose item set, source or rewrite text differs from
the export, and reports rows without a confidence (= not reviewed).
"""

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "research" / "annotation" / "export"
OUTDIR = EXPORT / "to_annotators"
GUIDE = ROOT / "research" / "annotation" / "GUIDELINES_D3.md"
SHEETS = ["pilot_A1", "pilot_A2", "main_A1", "main_A2"]
LABELS = ["addition", "distortion", "distortion_type", "omission", "faithful", "confidence", "note"]
DEFAULTS = {"addition": 0, "distortion": 0, "distortion_type": None, "omission": "none",
            "faithful": 1, "confidence": None, "note": None}
COLS = ["#", "item_id", "SOURCE (original news text)", "REWRITE (what the reader sees)"] + LABELS + ["check"]
WIDTH = {"#": 5, "item_id": 12, COLS[2]: 70, COLS[3]: 55, "addition": 10, "distortion": 10,
         "distortion_type": 15, "omission": 11, "faithful": 9, "confidence": 11, "note": 40, "check": 22}
csv.field_size_limit(10**9)

HOWTO = """HOW TO USE THIS WORKBOOK
1. Read the guideline below once (about 5 minutes). Keep it open while labelling.
2. Go to the "Items" sheet. Each row = one SOURCE text and one REWRITE of it.
3. Every row starts PRE-FILLED as "nothing wrong": addition 0, distortion 0, omission none, faithful 1.
   Read the SOURCE and the REWRITE, and change only what is wrong:
   - something added that the source does not support -> addition 1
   - something changed -> distortion 1, and pick a distortion_type
   - something important missing -> omission salient (a small detail missing -> omission minor)
   - if any of those makes the rewrite unfaithful -> faithful 0, and write in "note" the exact wrong words.
   Cells you change away from the default turn orange.
4. ALWAYS pick a confidence (1, 2 or 3) on EVERY row, even when you change nothing. That is how we know
   you checked the row. Do not just pick confidences without reading: an unread row left as "faithful"
   is a wrong label.
5. The "check" column turns green ("OK") when the row is complete and consistent; fix any red row.
   Progress is shown in cell B5 of this sheet.
6. About 1-2 minutes per item. Take breaks; at most about 60 items in one sitting.
   Work alone: no web search, no AI tools (ChatGPT, Gemini, Copilot...), no discussing items with the
   other annotator until you have BOTH finished.
7. Do not edit, sort or delete the item_id, SOURCE or REWRITE columns. Save as .xlsx and send it back.
   Write your name in cell B3 of this sheet.
"""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ws_norm(text):
    return " ".join(str(text or "").split())  # Excel may rewrite line endings on save


def read_csv(sheet, tag):
    with (EXPORT / f"{sheet}_{tag}.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build(sheet, tag):
    rows = read_csv(sheet, tag)
    annot = sheet.split("_")[1]
    out = OUTDIR / annot / f"{sheet}_{tag}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    n = len(rows) + 1
    wb = Workbook()

    info = wb.active
    info.title = "Instructions"
    phase = "pilot" if sheet.startswith("pilot") else "main batch"
    info["A1"] = f"MAPNAI faithfulness labelling: annotator {annot}, {phase} ({len(rows)} items)"
    info["A1"].font = Font(bold=True, size=14)
    info["A3"], info["A4"], info["A5"] = "Annotator name:", "Date finished:", "Rows done:"
    for c in ("A3", "A4", "A5"):
        info[c].font = Font(bold=True)
    for c in ("B3", "B4"):
        info[c].fill = PatternFill("solid", fgColor="FFF2CC")
    info["B5"] = f'=COUNTIF(Items!L2:L{n},"OK")&" of {len(rows)} OK"'
    r = 7
    for line in (HOWTO + "\n" + GUIDE.read_text(encoding="utf-8")).splitlines():
        info.cell(row=r, column=1, value=line).alignment = Alignment(wrap_text=True, vertical="top")
        if line.startswith(("#", "HOW TO")):
            info.cell(row=r, column=1).font = Font(bold=True)
        r += 1
    info.column_dimensions["A"].width = 30
    info.column_dimensions["B"].width = 120
    for rr in range(7, r):
        info.merge_cells(start_row=rr, start_column=1, end_row=rr, end_column=2)
        line = info.cell(row=rr, column=1).value or ""
        info.row_dimensions[rr].height = 15 * max(1, -(-len(line) // 140))

    ws = wb.create_sheet("Items")
    ws.append(COLS)
    head_fill, lab_fill = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="FFF2CC")
    for j, name in enumerate(COLS, 1):
        c = ws.cell(row=1, column=j)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[c.column_letter].width = WIDTH[name]
    ws.row_dimensions[1].height = 32
    top = Alignment(wrap_text=True, vertical="top")
    for i, row in enumerate(rows, 2):
        assert not any(row[k] for k in LABELS), f"{sheet}: export already has labels in {row['item_id']}"
        vals = [i - 1, row["item_id"], row["source"], row["rewrite"]] + [DEFAULTS[k] for k in LABELS]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.alignment = top
            if COLS[j - 1] in LABELS:
                c.fill = lab_fill
        ws.cell(row=i, column=len(COLS), value=(
            f'=IF(COUNTA(E{i},F{i},H{i},I{i})<4,"incomplete",'
            f'IF(J{i}="","to do: pick confidence",'
            f'IF(AND(F{i}&""="1",G{i}=""),"pick distortion_type",'
            f'IF(AND(F{i}&""="0",G{i}<>""),"clear distortion_type",'
            f'IF(I{i}&""<>IF(AND(E{i}&""="0",F{i}&""="0",H{i}<>"salient"),"1","0"),"faithful inconsistent",'
            f'IF(AND(I{i}&""="0",K{i}=""),"note required","OK"))))))')).alignment = top
        lines = max(len(row["source"]) / 75, len(row["rewrite"]) / 58, 2)
        ws.row_dimensions[i].height = min(409, 15 * (int(lines) + 1))
    for col, opts in (("E", "0,1"), ("F", "0,1"), ("G", "number,entity,role,polarity,modality,other"),
                      ("H", "none,minor,salient"), ("I", "0,1"), ("J", "1,2,3")):
        dv = DataValidation(type="list", formula1=f'"{opts}"', allow_blank=True,
                            error="Pick a value from the dropdown", showErrorMessage=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{n}")
    changed = PatternFill("solid", fgColor="F4B183")
    for col, cond in (("E", 'E2&""="1"'), ("F", 'F2&""="1"'), ("G", 'G2<>""'),
                      ("H", 'AND(H2<>"",H2<>"none")'), ("I", 'I2&""="0"')):
        ws.conditional_formatting.add(f"{col}2:{col}{n}", FormulaRule(formula=[cond], fill=changed))
    ok, bad, todo = (PatternFill("solid", fgColor=c) for c in ("C6EFCE", "FFC7CE", "EDEDED"))
    ws.conditional_formatting.add(f"L2:L{n}", FormulaRule(formula=['L2="OK"'], fill=ok))
    ws.conditional_formatting.add(f"L2:L{n}", FormulaRule(formula=['L2="to do: pick confidence"'], fill=todo))
    ws.conditional_formatting.add(f"L2:L{n}", FormulaRule(formula=['AND(L2<>"OK",L2<>"to do: pick confidence")'], fill=bad))
    ws.freeze_panes = "C2"
    wb.active = 0
    wb.save(out)
    return out, len(rows)


def to_csv(xlsx, tag):
    xlsx = Path(xlsx)
    sheet = next((s for s in SHEETS if xlsx.name.startswith(s)), None)
    if not sheet:
        sys.exit(f"cannot tell which sheet {xlsx.name} is (expected a name starting with {SHEETS})")
    ref = {r["item_id"]: r for r in read_csv(sheet, tag)}
    got = {}
    for row in load_workbook(xlsx)["Items"].iter_rows(min_row=2, values_only=True):
        if row[1]:
            iid = str(row[1])
            if iid in got:
                sys.exit(f"duplicate item_id {iid}")
            if iid not in ref:
                sys.exit(f"unknown item_id {iid}")
            if ws_norm(row[2]) != ws_norm(ref[iid]["source"]) or ws_norm(row[3]) != ws_norm(ref[iid]["rewrite"]):
                sys.exit(f"source/rewrite text edited in {iid}")
            got[iid] = ["" if v is None else v for v in row[4:11]]
    if set(got) != set(ref):
        sys.exit(f"missing items: {sorted(set(ref) - set(got))}")
    out = xlsx.with_name(f"{sheet}_{tag}_filled.csv")
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id"] + LABELS)
        for iid in ref:  # export order
            w.writerow([iid] + got[iid])
    unreviewed = [i for i in ref if got[i][5] in ("", None)]
    changed = sum(1 for i in ref if [got[i][k] for k in (0, 1, 3, 4)] != [0, 0, "none", 1])
    print(json.dumps({"out": str(out), "items": len(ref), "rows_without_confidence": len(unreviewed),
                      "rows_changed_from_default": changed, "first_unreviewed": unreviewed[:10]}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="gold-2026-11-01")
    ap.add_argument("--to-csv", metavar="FILLED_XLSX")
    a = ap.parse_args()
    if a.to_csv:
        to_csv(a.to_csv, a.tag)
    else:
        summary = {}
        for s in SHEETS:
            out, k = build(s, a.tag)
            summary[s] = {"xlsx": str(out.relative_to(ROOT)), "items": k,
                          "csv_sha256": sha256(EXPORT / f"{s}_{a.tag}.csv")}
            print(out, k, "items")
        print(json.dumps(summary, indent=1))
