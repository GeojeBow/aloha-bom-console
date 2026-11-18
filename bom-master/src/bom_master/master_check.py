"""전장설계 Master BOM check: the hand-compiled Master BOM file must equal what the folders say.

Reference ("folders") = for every BOM key, the lines of the latest 16 Prod DWG BOM the scan picked
(ks.prod; S041/S042 without own Prod DWG BOMs use the S040 Prod DWG, like the rest of the program).
Checked file ("Master") = the Excel file someone compiled by hand from those folders.

Every difference is reported: BOM missing / extra, revision differs, line missing / extra, value differs.
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import openpyxl

from .scanner import FIELD_IDS, FIELD_TITLE, _HEADER_LOOKUP, _norm_header, norm_value

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"

# kind -> (severity, English title, Korean title, what to do)
KINDS = {
    "BOM_MISSING": (ERROR, "BOM missing in manual Master", "수동 Master에 BOM 없음",
                    "Add this BOM (latest Prod DWG revision) to the Master BOM file."),
    "BOM_EXTRA": (ERROR, "BOM not in folders", "자동수집에 없는 BOM",
                  "Master lists a BOM that has no Prod DWG BOM. Remove it from Master, or put the BOM file in "
                  "16 Prod DWG."),
    "REV_DIFF": (ERROR, "Revision differs", "Revision 다름",
                 "Master was compiled from another revision. Update the BOM in Master to the latest Prod DWG "
                 "revision."),
    "LINE_MISSING": (ERROR, "Line missing in manual Master", "수동 Master에 라인 없음",
                     "Add the line to the Master BOM file."),
    "LINE_EXTRA": (ERROR, "Line not in folder BOM", "자동수집에 없는 라인",
                   "Remove the line from Master, or correct it to match the Prod DWG BOM."),
    "VALUE_DIFF": (ERROR, "Value differs", "값 다름",
                   "Correct the value in Master to the Prod DWG BOM value."),
    "DELETED_OMITTED": (INFO, "Deleted line left out (OK)", "삭제 라인 미포함 (정상)",
                        "Line is Mode = D in the Prod DWG BOM and not in Master. No action needed."),
}
SEV_RANK = {ERROR: 3, WARN: 2, INFO: 1, None: 0}

# extra header names for the Master file (on top of the BOM columns the scanner knows)
_ID_ALIASES = {
    "bom": ("bom", "bomno", "bomnumber", "bomname", "bomfile", "bomfilename", "filename", "file", "bomid",
            "bomkey"),
    "bom_rev": ("bomrev", "bomrevision", "rev", "revno", "filerev", "bomr"),
    "hull": ("hull", "hullno", "vessel", "ship", "shipname", "호선"),
}
_ID_LOOKUP = {a: f for f, al in _ID_ALIASES.items() for a in al}
# NB: "Revision" stays item_rev (the BOM column); only "Rev" / "BOM Rev" means the BOM revision.

BOM_IN_TEXT = re.compile(
    r"(?P<ship>\d{4}|S\d{3})[-_ ](?P<block>[A-Z0-9]{3,8})[-_ ](?P<phase>\d{1,2})[-_ ](?P<disc>[A-Z]{2})"
    r"(?:[-_ ]?R(?:EV)?[-_ .]?(?P<rev>\d+))?", re.I)
_REV_NUM = re.compile(r"(\d+)")


@dataclass
class Diff:
    kind: str
    key: str                     # BOM key, e.g. 1040-A310P-05-EO
    material: str = ""
    pos: str = ""
    field: str = ""              # VALUE_DIFF: field id
    folder_value: str = ""
    master_value: str = ""
    desc: str = ""
    master_ref: str = ""         # sheet!row in the Master file
    detail: str = ""

    @property
    def sev(self):
        return KINDS[self.kind][0]


@dataclass
class KeyCheck:
    key: str
    ship: str
    block: str
    phase: str
    disc: str
    folder_rev: int | None = None
    master_revs: list = field(default_factory=list)
    folder_lines: int = 0
    master_lines: int = 0
    basis: str = ""
    diffs: list = field(default_factory=list)

    @property
    def group(self):
        return self.block[:1]

    @property
    def in_folder(self):
        return self.folder_rev is not None

    @property
    def in_master(self):
        return self.master_lines > 0

    @property
    def worst(self):
        return max((d.sev for d in self.diffs), key=lambda s: SEV_RANK[s], default=None)

    @property
    def n_errors(self):
        return sum(1 for d in self.diffs if d.sev == ERROR)

    def bar(self, which):
        """(text, kind) for one tile bar. which: BOM / REV / LINES / VALUES. kind: OK / ERROR / NONE."""
        kinds = Counter(d.kind for d in self.diffs)
        if which == "BOM":
            if self.in_folder and self.in_master:
                return "In both", "OK"
            return ("Missing in Master", "ERROR") if self.in_folder else ("Not in folders", "ERROR")
        if not (self.in_folder and self.in_master):
            return "—", "NONE"
        if which == "REV":
            if not self.master_revs:
                return f"R{self.folder_rev} (Master has no rev)", "NONE"
            return (f"R{self.folder_rev} ≠ Master R{'/'.join(map(str, self.master_revs))}", "ERROR") \
                if kinds["REV_DIFF"] else (f"R{self.folder_rev}", "OK")
        if which == "LINES":
            m, x = kinds["LINE_MISSING"], kinds["LINE_EXTRA"]
            if m or x:
                return f"{m} missing · {x} extra", "ERROR"
            return f"{self.folder_lines} lines", "OK"
        n = kinds["VALUE_DIFF"]
        return (f"{n} values differ", "ERROR") if n else ("Values match", "OK")

    @property
    def status(self):
        if not self.in_master:
            return "Missing in Master"
        if not self.in_folder:
            return "Not in folders"
        return "Differs" if self.n_errors else "Matches"


@dataclass
class CheckResult:
    path: str
    mtime: float
    checked_at: float
    keys: dict                      # key -> KeyCheck
    sheets: list
    columns: dict                   # field id -> header text found
    warnings: list
    master_rows: int = 0

    def diffs(self, ships=None):
        out = []
        for k in self.keys.values():
            if ships is None or k.ship in ships:
                out.extend(k.diffs)
        return out


# ---------------------------------------------------------------- reading the Master file
def _ship4(text, cfg) -> str:
    """'1040', 'S040', 'S-040', '040' -> '1040' (a key of cfg['ships']); '' when unknown."""
    t = str(text or "").strip().upper()
    if not t:
        return ""
    ships = cfg["ships"]
    if t in ships:
        return t
    for code, lab in ships.items():
        if t.replace("-", "").replace(" ", "") == lab.upper():
            return code
    m = re.search(r"0?4\d", t)
    if m:
        cand = "1" + m.group(0)[-3:].rjust(3, "0")
        if cand in ships:
            return cand
    return ""


def _match_header(row):
    colmap, idmap = {}, {}
    for j, c in enumerate(row):
        n = _norm_header(c)
        if not n:
            continue
        if n in _ID_LOOKUP and _ID_LOOKUP[n] not in idmap:
            idmap[_ID_LOOKUP[n]] = j
        elif n in _HEADER_LOOKUP and _HEADER_LOOKUP[n] not in colmap:
            colmap[_HEADER_LOOKUP[n]] = j
    return colmap, idmap


def read_master(path: str, cfg) -> tuple[list, list, dict, list]:
    """Returns (rows, sheets_used, columns_found, warnings). Each row: field values + _key, _rev, _ref."""
    rows, sheets, columns, warnings = [], [], {}, []
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            it = ws.iter_rows(values_only=True)
            header, colmap, idmap = None, {}, {}
            for i, row in enumerate(it):
                cm, im = _match_header(row)
                if ("material" in cm and len(cm) >= 4) or len(cm) >= 7:
                    header, colmap, idmap = (i, row), cm, im
                    break
                if i > 30:
                    break
            if header is None:
                continue
            hi, hrow = header
            sheet_key = BOM_IN_TEXT.search(ws.title or "")
            can_key = "bom" in idmap or {"block", "phase", "discipline"} <= colmap.keys() or sheet_key
            if not can_key:
                warnings.append(f"Sheet '{ws.title}': no BOM column and no Block / Phase / Discipline columns — "
                                "lines cannot be assigned to a BOM, sheet skipped.")
                continue
            sheets.append(ws.title)
            for f, j in list(colmap.items()) + list(idmap.items()):
                columns.setdefault(f, str(hrow[j]).strip())
            blank, no_key = 0, 0
            for r_i, row in enumerate(it, start=hi + 2):
                def cell(j):
                    return norm_value(row[j]) if j is not None and j < len(row) else ""
                vals = {f: cell(j) for f, j in colmap.items()}
                ids = {f: cell(j) for f, j in idmap.items()}
                if not any(vals.values()):
                    blank += 1
                    if blank > 50:
                        break
                    continue
                blank = 0
                if not vals.get("material") and not vals.get("pos"):
                    continue                     # sub-total / title rows
                key, rev = _row_key(vals, ids, sheet_key, cfg)
                if not key:
                    no_key += 1
                    continue
                vals["_key"], vals["_rev"], vals["_ref"] = key, rev, f"{ws.title}!{r_i}"
                rows.append(vals)
            if no_key:
                warnings.append(f"Sheet '{ws.title}': {no_key} lines skipped — their BOM (hull-block-phase-"
                                "discipline) could not be determined.")
    finally:
        wb.close()
    if not sheets:
        warnings.append("No sheet with BOM columns (Material No., Quantity, Block/GB/Zone No., …) was found.")
    return rows, sheets, columns, warnings


def _row_key(vals, ids, sheet_key, cfg):
    rev = None
    m = BOM_IN_TEXT.search(ids.get("bom", "")) if ids.get("bom") else None
    if m:
        ship = _ship4(m.group("ship"), cfg) or m.group("ship")
        key = f"{ship}-{m.group('block').upper()}-{int(m.group('phase')):02d}-{m.group('disc').upper()}"
        rev = int(m.group("rev")) if m.group("rev") else None
    else:
        ship = _ship4(ids.get("hull"), cfg) or _ship4(vals.get("ship_no"), cfg)
        block, phase, disc = vals.get("block", "").upper(), vals.get("phase", ""), vals.get("discipline", "").upper()
        if sheet_key and not (block and phase and disc):
            ship = ship or _ship4(sheet_key.group("ship"), cfg)
            block, phase, disc = sheet_key.group("block").upper(), sheet_key.group("phase"), sheet_key.group("disc").upper()
            rev = int(sheet_key.group("rev")) if sheet_key.group("rev") else None
        if not (ship and block and phase and disc):
            return "", None
        try:
            phase = f"{int(float(phase)):02d}"
        except ValueError:
            pass
        key = f"{ship}-{block}-{phase}-{disc}"
    if ids.get("bom_rev"):
        mm = _REV_NUM.search(ids["bom_rev"])
        if mm:
            rev = int(mm.group(1))
    return key, rev


# ---------------------------------------------------------------- comparing
def _is_deleted(r):
    return r.get("mode", "").strip().upper() == "D"


def _pair_lines(f_rows, m_rows):
    """Pair folder and Master lines: same Material+Pos first, then same Material, then same Pos.
    Returns (pairs, folder_only, master_only)."""
    left_f, left_m = list(f_rows), list(m_rows)
    pairs = []
    for keyfn in (lambda r: (r.get("material", ""), r.get("pos", "")) if r.get("material") else None,
                  lambda r: r.get("material") or None,
                  lambda r: r.get("pos") or None):
        idx = defaultdict(list)
        for r in left_m:
            k = keyfn(r)
            if k is not None:
                idx[k].append(r)
        nf = []
        for r in left_f:
            k = keyfn(r)
            if k is not None and idx.get(k):
                mr = idx[k].pop(0)
                pairs.append((r, mr))
            else:
                nf.append(r)
        used = {id(m) for _, m in pairs}
        left_f, left_m = nf, [r for r in left_m if id(r) not in used]
    return pairs, left_f, left_m


def _same(fid, a, b):
    if a == b:
        return True
    try:
        return abs(float(a or 0) - float(b or 0)) < 1e-6      # 5 = 5.0 = 05
    except ValueError:
        pass
    return a.strip().upper() == b.strip().upper() if fid in ("unit", "mode", "discipline", "block") else False


def check(cfg, res, path: str, progress=None) -> CheckResult:
    """Compare the Master BOM file at `path` with the scan result `res` (analyzer.Result)."""
    if progress:
        progress("Reading the Master BOM file…")
    rows, sheets, columns, warnings = read_master(path, cfg)
    if progress:
        progress("Comparing with the folders…")
    ignore = set(cfg.get("master_check_ignore", [])) | {"ship_no"}
    compare = [f for f in FIELD_IDS if f in columns and f not in ignore]
    not_in_master = [FIELD_TITLE[f] for f in FIELD_IDS if f not in columns and f not in ignore]
    if not_in_master and sheets:
        warnings.append("Not compared (column not in the Master file): " + ", ".join(not_in_master))

    by_key = defaultdict(list)
    for r in rows:
        by_key[r["_key"]].append(r)
    keys = {}
    for ks in (res.keys.values() if res else []):
        if not ks.prod:
            continue
        kc = KeyCheck(ks.key, ks.ship, ks.block, ks.phase, ks.disc, folder_rev=ks.prod_rev,
                      folder_lines=sum(1 for r in ks.prod.rows if not _is_deleted(r)),
                      basis=(f"{cfg.ship_label(ks.prod.ship)} Prod DWG" if ks.baseline_of else "Prod DWG"))
        keys[ks.key] = kc
    for key, mrows in by_key.items():
        if key not in keys:
            p = key.split("-")
            keys[key] = KeyCheck(key, p[0], p[1], p[2], p[3] if len(p) > 3 else "")
        keys[key].master_lines = len(mrows)
        keys[key].master_revs = sorted({r["_rev"] for r in mrows if r["_rev"] is not None})

    for key, kc in keys.items():
        mrows = by_key.get(key, [])
        if not kc.in_folder:
            kc.diffs.append(Diff("BOM_EXTRA", key, master_ref=mrows[0]["_ref"] if mrows else "",
                                 detail=f"{len(mrows)} lines in Master"))
            continue
        frows = res.keys[key].prod.rows
        if not mrows:
            kc.diffs.append(Diff("BOM_MISSING", key, detail=f"R{kc.folder_rev}, {kc.folder_lines} lines"))
            continue
        if kc.master_revs and kc.master_revs != [kc.folder_rev]:
            kc.diffs.append(Diff("REV_DIFF", key, field="bom_rev", folder_value=f"R{kc.folder_rev}",
                                 master_value="/".join(f"R{r}" for r in kc.master_revs),
                                 master_ref=mrows[0]["_ref"]))
        pairs, f_only, m_only = _pair_lines(frows, mrows)
        for fr in f_only:
            kind = "DELETED_OMITTED" if _is_deleted(fr) else "LINE_MISSING"
            kc.diffs.append(Diff(kind, key, fr.get("material", ""), fr.get("pos", ""),
                                 desc=fr.get("desc1", ""), folder_value=fr.get("qty", ""),
                                 detail=f"Qty {fr.get('qty', '')} {fr.get('unit', '')}".strip()))
        for mr in m_only:
            kc.diffs.append(Diff("LINE_EXTRA", key, mr.get("material", ""), mr.get("pos", ""),
                                 desc=mr.get("desc1", ""), master_value=mr.get("qty", ""), master_ref=mr["_ref"],
                                 detail=f"Qty {mr.get('qty', '')} {mr.get('unit', '')}".strip()))
        for fr, mr in pairs:
            for fid in compare:
                a, b = fr.get(fid, ""), mr.get(fid, "")
                if not _same(fid, a, b):
                    kc.diffs.append(Diff("VALUE_DIFF", key, fr.get("material", "") or mr.get("material", ""),
                                         fr.get("pos", "") or mr.get("pos", ""), field=fid, folder_value=a,
                                         master_value=b, desc=fr.get("desc1", ""), master_ref=mr["_ref"]))
    return CheckResult(path=path, mtime=os.path.getmtime(path), checked_at=time.time(), keys=keys,
                       sheets=sheets, columns=columns, warnings=warnings, master_rows=len(rows))


def diff_row(d: Diff, cfg, kc: KeyCheck | None = None) -> dict:
    sev, en, ko, action = KINDS[d.kind]
    ship = d.key.split("-")[0]
    return {
        "sev": sev, "hull": cfg.ship_label(ship), "bom": d.key, "kind": f"{en} / {ko}", "material": d.material,
        "pos": d.pos, "desc": d.desc, "field": FIELD_TITLE.get(d.field, "BOM revision" if d.field == "bom_rev" else ""),
        "folder_value": d.folder_value, "master_value": d.master_value, "detail": d.detail,
        "master_ref": d.master_ref, "action": action, "basis": kc.basis if kc else "",
        "_kind": d.kind, "_key": d.key, "_kind:sev": sev,
    }


DIFF_COLS = [("sev", "Severity"), ("hull", "Hull"), ("bom", "BOM"), ("kind", "Difference / 차이"),
             ("material", FIELD_TITLE["material"]), ("pos", "Pos"), ("desc", FIELD_TITLE["desc1"]),
             ("field", "Column / 열"), ("folder_value", "자동수집 (correct) / Folders"),
             ("master_value", "수동 Master / Manual"), ("detail", "Detail"), ("master_ref", "Master cell / 위치"),
             ("action", "What to do / 조치")]
