"""Master BOM check on a small fake project: planted differences must all be found, nothing else."""
import os
import sys
from collections import Counter
from pathlib import Path

from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("APPDATA", str(Path(__file__).resolve().parent / "_appdata"))

from bom_master import master_check as mc  # noqa: E402
from bom_master.analyzer import analyze  # noqa: E402
from bom_master.config import Config  # noqa: E402
from bom_master.scanner import COLUMNS, discover, load_all  # noqa: E402

HEAD = [t for _, t in COLUMNS]


def line(ship, block, mat, pos, qty, desc, mode=""):
    v = dict(material=mat, release_date="", ship_no=ship, inst_dwg="", mfg_dwg="", pos=pos, mat_status="",
             qty=qty, unit="EA", desc1=desc, desc2="", quality="", element="", weight="", item_rev="",
             mode=mode, class_cert="", block=block, phase="05", discipline="EO")
    return [v[f] for f, _ in COLUMNS]


def write(path, rows, head=HEAD, extra_cols=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "BOM"
    ws.append(["Master Bom Sheet"])
    ws.append((extra_cols or []) + head)
    for r in rows:
        ws.append(r)
    wb.save(path)


BOMS = {
    "A310P": [("M-100", "10", 4, "Cable tray"), ("M-101", "20", 2, "Junction box"), ("M-102", "30", 1, "Lamp")],
    "E410P": [("M-200", "10", 8, "Cable gland"), ("M-201", "20", 3, "Socket", "D")],
    "B220S": [("M-300", "10", 5, "Switch")],
}


def make_project(tmp: Path):
    base = tmp / "proj"
    for blk, ls in BOMS.items():
        rows = [line("1040", blk, *l) for l in ls]
        rev = {"A310P": 3, "E410P": 1, "B220S": 2}[blk]
        write(base / "16 Prod DWG" / blk / f"1040-{blk}-05-EO-R{rev}.xlsx", rows)
    # S041 has a Work Package copy only -> checked against S040 Prod DWG
    write(base / "17 Work Packages" / "1041" / "1041-A310P-05-EO-R3.xlsx",
          [line("1040", "A310P", *l) for l in BOMS["A310P"]])
    for d in ("03 DCN", "04 ECN"):
        (base / d).mkdir(parents=True, exist_ok=True)
    return base


def make_master(path: Path):
    rows = []
    # A310P S040: correct except qty of M-101 and an extra line; rev given as R3
    for l in BOMS["A310P"]:
        q = 5 if l[0] == "M-101" else l[2]
        rows.append(["1040-A310P-05-EO", "R3"] + line("1040", "A310P", l[0], l[1], q, l[3]))
    rows.append(["1040-A310P-05-EO", "R3"] + line("1040", "A310P", "M-999", "40", 1, "Extra item"))
    # E410P: compiled from R0 (rev differs), deleted line left out (fine)
    rows.append(["1040-E410P-05-EO", "R0"] + line("1040", "E410P", "M-200", "10", 8, "Cable gland"))
    # B220S missing from Master entirely
    # S041 A310P: one line missing
    for l in BOMS["A310P"][:2]:
        rows.append(["S041-A310P-05-EO", "3"] + line("1041", "A310P", l[0], l[1], l[2], l[3]))
    # a BOM that does not exist in the folders
    rows.append(["1040-Z999P-05-EO", "R1"] + line("1040", "Z999P", "M-500", "10", 1, "Ghost"))
    write(path, rows, extra_cols=["BOM", "BOM Rev"])


def test_master_check(tmp_path):
    base = make_project(tmp_path)
    cfg = Config.load()
    cfg["base"] = str(base)
    files, others, errs = discover(cfg)
    load_all(cfg, files)
    res = analyze(cfg, files, others, errs)
    master = tmp_path / "Master.xlsx"
    make_master(master)
    chk = mc.check(cfg, res, str(master))
    got = Counter((d.key, d.kind) for k in chk.keys.values() for d in k.diffs)
    assert got == Counter({
        ("1040-A310P-05-EO", "VALUE_DIFF"): 1,
        ("1040-A310P-05-EO", "LINE_EXTRA"): 1,
        ("1040-E410P-05-EO", "REV_DIFF"): 1,
        ("1040-E410P-05-EO", "DELETED_OMITTED"): 1,
        ("1040-B220S-05-EO", "BOM_MISSING"): 1,
        ("1041-A310P-05-EO", "LINE_MISSING"): 1,
        ("1040-Z999P-05-EO", "BOM_EXTRA"): 1,
    }), got
    vd = next(d for d in chk.keys["1040-A310P-05-EO"].diffs if d.kind == "VALUE_DIFF")
    assert (vd.material, vd.field, vd.folder_value, vd.master_value) == ("M-101", "qty", "2", "5")
    assert chk.keys["1041-A310P-05-EO"].basis.startswith("S040")
    assert {k.status for k in chk.keys.values()} >= {"Differs", "Missing in Master", "Not in folders"}
    from bom_master.report import build_master_check_report
    out = build_master_check_report(cfg, chk, str(tmp_path / "check.xlsx"))
    assert Path(out).exists()


def test_key_from_columns_without_bom_column(tmp_path):
    """No BOM column: hull comes from Ship No., BOM from Block / Phase / Discipline."""
    base = make_project(tmp_path)
    cfg = Config.load()
    cfg["base"] = str(base)
    files, others, errs = discover(cfg)
    load_all(cfg, files)
    res = analyze(cfg, files, others, errs)
    master = tmp_path / "Master2.xlsx"
    rows = [line("1040", blk, *l) for blk, ls in BOMS.items() for l in ls]
    rows += [line("S041", "A310P", *l) for l in BOMS["A310P"]]
    write(master, rows)
    chk = mc.check(cfg, res, str(master))
    bad = [(d.key, d.kind) for k in chk.keys.values() for d in k.diffs]
    assert bad == [], bad
