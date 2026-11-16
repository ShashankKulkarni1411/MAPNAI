"""
E15b — annotator-friendly Excel version of the blind human-check sheet (research/PREREG.md §10).

Reads   research/annotation/export/humancheck_<tag>.csv  (from e15; 80 items, no judge labels)
Writes  research/annotation/export/humancheck_<tag>.xlsx (git-ignored: third-party text)

Same items, same order, same label columns. Adds: the guideline on its own sheet, wrapped text,
dropdowns for every label, and a live "check" column that flags incomplete/inconsistent rows.
Still blind: no judge label, model, style, gate decision or stratum is written.
Read back with --to-csv to get the filled labels in the e15 CSV layout.
"""

import argparse
import csv
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[2]
EXPORT = ROOT / "research" / "annotation" / "export"
GUIDE = ROOT / "research" / "annotation" / "GUIDELINES_D3.md"
LABELS = ["addition", "distortion", "distortion_type", "omission", "faithful", "confidence", "note"]
COLS = ["#", "item_id", "SOURCE (original news text)", "REWRITE (what the reader sees)"] + LABELS + ["check"]
WIDTH = {"#": 5, "item_id": 12, COLS[2]: 70, COLS[3]: 55, "addition": 10, "distortion": 10,
         "distortion_type": 15, "omission": 11, "faithful": 9, "confidence": 11, "note": 40, "check": 20}

HOWTO = """HOW TO USE THIS WORKBOOK
1. Read the guideline below once (about 5 minutes). Keep it open while labelling.
2. Go to the "Items" sheet. Each row = one SOURCE text and one REWRITE of it.
3. For each row, compare the REWRITE against the SOURCE only (no web search, no outside knowledge).
4. Fill the coloured columns using the dropdowns: addition, distortion, distortion_type (only if distortion = 1),
   omission, faithful, confidence. If faithful = 0, write in "note" the exact words of the rewrite that are wrong.
5. The "check" column turns green ("OK") when the row is complete and consistent; fix any red row.
6. About 1-2 minutes per item, 80 items. Do not discuss items with anyone until you have finished.
7. Save the file (keep .xlsx) and send it back. Write your name in cell B3 of this sheet.
"""


def build(tag):
    src = EXPORT / f"humancheck_{tag}.csv"
    out = EXPORT / f"humancheck_{tag}.xlsx"
    with src.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    wb = Workbook()

    info = wb.active
    info.title = "Instructions"
    info["A1"] = "MAPNAI faithfulness check — annotator workbook"
    info["A1"].font = Font(bold=True, size=14)
    info["A3"], info["A4"] = "Annotator name:", "Date finished:"
    for c in ("A3", "A4"):
        info[c].font = Font(bold=True)
    for c in ("B3", "B4"):
        info[c].fill = PatternFill("solid", fgColor="FFF2CC")
    r = 6
    for line in (HOWTO + "\n" + GUIDE.read_text(encoding="utf-8")).splitlines():
        info.cell(row=r, column=1, value=line).alignment = Alignment(wrap_text=True, vertical="top")
        if line.startswith(("#", "HOW TO")):
            info.cell(row=r, column=1).font = Font(bold=True)
        r += 1
    info.column_dimensions["A"].width = 30
    info.column_dimensions["B"].width = 120
    for rr in range(6, r):
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
        vals = [i - 1, row["item_id"], row["source"], row["rewrite"]] + [row[k] or None for k in LABELS]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.alignment = top
            if COLS[j - 1] in LABELS:
                c.fill = lab_fill
        ws.cell(row=i, column=len(COLS), value=(
            f'=IF(COUNTA(E{i},F{i},H{i},I{i},J{i})=0,"",'
            f'IF(COUNTA(E{i},F{i},H{i},I{i},J{i})<5,"incomplete",'
            f'IF(AND(F{i}&""="1",G{i}=""),"pick distortion_type",'
            f'IF(AND(F{i}&""="0",G{i}<>""),"clear distortion_type",'
            f'IF(I{i}&""<>IF(AND(E{i}&""="0",F{i}&""="0",H{i}<>"salient"),"1","0"),"faithful inconsistent",'
            f'IF(AND(I{i}&""="0",K{i}=""),"note required","OK"))))))')).alignment = top
        lines = max(len(row["source"]) / 75, len(row["rewrite"]) / 58, 2)
        ws.row_dimensions[i].height = min(409, 15 * (int(lines) + 1))
    n = len(rows) + 1
    for col, opts in (("E", "0,1"), ("F", "0,1"), ("G", "number,entity,role,polarity,modality,other"),
                      ("H", "none,minor,salient"), ("I", "0,1"), ("J", "1,2,3")):
        dv = DataValidation(type="list", formula1=f'"{opts}"', allow_blank=True,
                            error="Pick a value from the dropdown", showErrorMessage=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}{n}")
    ok, bad = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
    ws.conditional_formatting.add(f"L2:L{n}", FormulaRule(formula=['L2="OK"'], fill=ok))
    ws.conditional_formatting.add(f"L2:L{n}", FormulaRule(formula=['AND(L2<>"",L2<>"OK")'], fill=bad))
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:L{n}"
    wb.active = 0
    wb.save(out)
    print(out, len(rows), "items")


def to_csv(tag, xlsx):
    ws = load_workbook(xlsx, data_only=False)["Items"]
    out = EXPORT / f"humancheck_{tag}_filled.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item_id"] + LABELS)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[1]:
                w.writerow([row[1]] + ["" if v is None else v for v in row[4:11]])
    print(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="gold-2026-11-01")
    ap.add_argument("--to-csv", metavar="FILLED_XLSX")
    a = ap.parse_args()
    to_csv(a.tag, a.to_csv) if a.to_csv else build(a.tag)
