"""E17: A1/A2 adjudication on the main gold set.

  python e17_adjudication.py sheet   -> builds adjudication workbook of disagreements + pre-adjudication kappa JSON
  python e17_adjudication.py merge   -> reads filled workbook, writes adjudicated gold CSV (agreements + FINAL labels)

A disagreement = any of addition / distortion / omission / faithful differs.
FINAL_* columns are filled jointly by the annotators (or a third human adjudicator).
"""
import collections, csv, json, sys
from pathlib import Path
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

R = Path(__file__).resolve().parents[1]
TA = R / "annotation/export/to_annotators"
A1 = TA / "A1/_A1-ShaunakOP.xlsx"
A2 = TA / "A2/main_A2_gold-2026-11-01op2.xlsx"
OUT = R / "annotation/export/adjudication"
SHEET = OUT / "adjudication_main_gold-2026-11-01.xlsx"
FIELDS = ["addition", "distortion", "distortion_type", "omission", "faithful", "confidence"]
KEYF = ["addition", "distortion", "omission", "faithful"]


def load(p):
    ws = openpyxl.load_workbook(p, data_only=True)["Items"]
    hdr = [c.value for c in ws[1]]
    out = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(hdr, r))
        if d.get("item_id"):
            out[d["item_id"]] = {k: ("" if v is None else str(v)) for k, v in d.items()}
    return out


def kappa(x, y):
    n = len(x); po = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = collections.Counter(x), collections.Counter(y)
    pe = sum(cx[c] * cy[c] for c in cx) / n / n
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def sheet():
    a, b = load(A1), load(A2)
    ids = sorted(set(a) & set(b), key=lambda j: int(b[j]["#"]))
    assert len(ids) == len(a) == len(b), "item sets differ"
    stats = {f: {"kappa": round(kappa([a[j][f] for j in ids], [b[j][f] for j in ids]), 4),
                 "disagree": sum(a[j][f] != b[j][f] for j in ids)} for f in FIELDS}
    dis = [j for j in ids if any(a[j][f] != b[j][f] for f in KEYF)]
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump({"n": len(ids), "n_disagree": len(dis), "a1": A1.name, "a2": A2.name, "pre_adjudication": stats},
              open(OUT / "kappa_pre_adjudication.json", "w"), indent=2)

    wb = openpyxl.Workbook(); ins = wb.active; ins.title = "Instructions"
    for line in [
        "Adjudication: A1 and A2 together (or a third adjudicator).",
        f"{len(dis)} items where A1 and A2 differ on addition / distortion / omission / faithful.",
        "For each row: read SOURCE and REWRITE, read both notes, agree the correct label using the guideline + addendum v1.1.",
        "Fill every FINAL_* column (yellow). FINAL_distortion_type only if FINAL_distortion = 1.",
        "FINAL_faithful must be 0 if any of: addition=1, distortion=1, omission=salient.",
        "Write a one-line reason in FINAL_reason. Do NOT change the A1_/A2_ columns.",
        "If you cannot agree, set FINAL_faithful to 'unresolved' and explain.",
    ]:
        ins.append([line])
    ins.column_dimensions["A"].width = 120

    ws = wb.create_sheet("Adjudicate")
    cols = ["#", "item_id", "SOURCE", "REWRITE", "differs_on"]
    for who in ("A1", "A2"):
        cols += [f"{who}_{f}" for f in ["addition", "distortion", "distortion_type", "omission", "faithful", "note"]]
    fin = ["FINAL_addition", "FINAL_distortion", "FINAL_distortion_type", "FINAL_omission", "FINAL_faithful", "FINAL_reason"]
    ws.append(cols + fin)
    for j in dis:
        row = [b[j]["#"], j, b[j]["SOURCE (original news text)"], b[j]["REWRITE (what the reader sees)"],
               ", ".join(f for f in KEYF if a[j][f] != b[j][f])]
        for d in (a[j], b[j]):
            row += [d["addition"], d["distortion"], d["distortion_type"], d["omission"], d["faithful"], d["note"]]
        ws.append(row + [""] * len(fin))
    n = len(dis) + 1
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]: c.font = Font(bold=True)
    first_fin = len(cols) + 1
    for r in ws.iter_rows(min_row=2, max_row=n):
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")
            if c.column >= first_fin: c.fill = yellow
    widths = {"C": 60, "D": 60, "E": 18}
    for i, name in enumerate(cols + fin, 1):
        L = openpyxl.utils.get_column_letter(i)
        ws.column_dimensions[L].width = widths.get(L, 40 if name.endswith(("note", "reason")) else 11)
    ws.freeze_panes = "F2"
    L = lambda k: openpyxl.utils.get_column_letter(first_fin + k)
    for k, opts in [(0, '"0,1"'), (1, '"0,1"'),
                    (2, '"entity,number,role,modality,polarity,other"'),
                    (3, '"none,minor,salient"'), (4, '"0,1,unresolved"')]:
        dv = DataValidation(type="list", formula1=opts, allow_blank=True); ws.add_data_validation(dv)
        dv.add(f"{L(k)}2:{L(k)}{n}")
    wb.save(SHEET)
    print(f"{len(dis)} disagreements -> {SHEET}"); print(json.dumps(stats, indent=1))


def merge():
    a, b = load(A1), load(A2)
    src = Path(sys.argv[2]) if len(sys.argv) > 2 else SHEET
    ws = openpyxl.load_workbook(src, data_only=True)["Adjudicate"]
    hdr = [c.value for c in ws[1]]
    fin = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        d = dict(zip(hdr, ["" if v is None else str(v) for v in r]))
        miss = [f for f in ["FINAL_addition", "FINAL_distortion", "FINAL_omission", "FINAL_faithful"] if not d[f]]
        if miss: sys.exit(f"item {d['item_id']} (#{d['#']}) missing {miss}")
        fin[d["item_id"]] = d
    rows = []
    for j in sorted(a, key=lambda j: int(b[j]["#"])):
        if j in fin:
            d = fin[j]
            rows.append({"item_id": j, "addition": d["FINAL_addition"], "distortion": d["FINAL_distortion"],
                         "distortion_type": d["FINAL_distortion_type"], "omission": d["FINAL_omission"],
                         "faithful": d["FINAL_faithful"], "source": "adjudicated", "reason": d["FINAL_reason"]})
        else:
            rows.append({"item_id": j, **{f: a[j][f] for f in ["addition", "distortion", "omission", "faithful"]},
                         "distortion_type": a[j]["distortion_type"] or b[j]["distortion_type"],
                         "source": "agreed", "reason": ""})
    p = OUT / "gold_adjudicated_main-2026-11-01.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"{len(rows)} rows ({len(fin)} adjudicated) -> {p}")


if __name__ == "__main__":
    {"sheet": sheet, "merge": merge}[sys.argv[1] if len(sys.argv) > 1 else "sheet"]()
