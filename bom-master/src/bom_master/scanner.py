"""Find BOM workbooks under the four source folders and read them (with a local cache)."""
import datetime as _dt
import hashlib
import json
import os
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import openpyxl

from .config import Config, cache_dir

PARSER_VERSION = 2   # bump when the parsed payload changes, so cached files are re-read

# 1040-A310P-05-EO-R3.xlsx, 1040-A410P-05-EO-R1-20250813.xlsx, 1040-A310P-05-EO-R1_JR_Reviewed.xlsx
BOM_NAME = re.compile(
    r"^(?P<ship>\d{4})-(?P<block>[A-Z0-9]{3,8})-(?P<phase>\d{2})-(?P<disc>[A-Z]{2})"
    r"[-_ ]?R(?:EV)?[-_ .]?(?P<rev>\d+)(?P<suffix>[^.]*)\.(?P<ext>xlsx|xlsm)$",
    re.I,
)

# Canonical BOM columns (SAP "Master Bom Sheet" layout). Header text -> field id.
COLUMNS = [
    ("material", "Material No."),
    ("release_date", "Date of Release"),
    ("ship_no", "Ship No."),
    ("inst_dwg", "Inst Dwg. No."),
    ("mfg_dwg", "Mfg Dwg. No."),
    ("pos", "BOM Item Position No."),
    ("mat_status", "Plant Specific Material Status"),
    ("qty", "Quantity"),
    ("unit", "Unit"),
    ("desc1", "Description 1"),
    ("desc2", "Description 2"),
    ("quality", "Quality of Material"),
    ("element", "Element No."),
    ("weight", "Weight"),
    ("item_rev", "Revision"),
    ("mode", "Mode"),
    ("class_cert", "Class Cert"),
    ("block", "Block/GB/Zone No."),
    ("phase", "Phase No."),
    ("discipline", "Discipline Code"),
]
FIELD_IDS = [c[0] for c in COLUMNS]
FIELD_TITLE = dict(COLUMNS)


def _norm_header(h) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


_HEADER_LOOKUP = {_norm_header(t): f for f, t in COLUMNS}
_HEADER_LOOKUP.update({
    "materialno": "material", "materialnumber": "material", "material": "material",
    "plantspecificmaterialstat": "mat_status", "plantspecificmaterialstatus": "mat_status",
    "elementno": "element", "blockgbzoneno": "block", "blockno": "block",
    "phaseno": "phase", "disciplinecode": "discipline", "itemrevision": "item_rev",
})


def norm_value(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            return str(int(v))
        return repr(round(float(v), 6)).rstrip("0").rstrip(".")
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%m/%d/%Y")
    s = str(v).replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s{2,}", " ", s)


@dataclass
class BomFile:
    role: str            # PROD / WP / DCN / ECN
    path: str
    rel: str             # path relative to the role root
    name: str
    ship: str
    block: str
    phase: str
    disc: str
    rev: int
    suffix: str
    loc: str = "ACTIVE"  # ACTIVE / ARCHIVE / COMMENT / STAGING
    size: int = 0
    mtime: float = 0.0
    content_hash: str = ""
    rows: list = field(default_factory=list)   # list[dict field->str]
    extra_headers: list = field(default_factory=list)
    sheet: str = ""
    error: str = ""
    warn: str = ""

    @property
    def key(self) -> str:
        return f"{self.ship}-{self.block}-{self.phase}-{self.disc}"

    @property
    def keyrev(self) -> str:
        return f"{self.key}-R{self.rev}"

    @property
    def folder(self) -> str:
        return os.path.dirname(self.path)


def classify_location(cfg: Config, role: str, rel: str, suffix: str) -> str:
    parts = [p.lower() for p in rel.replace("/", "\\").split("\\")]
    folders, fname = parts[:-1], parts[-1]
    ctoks = cfg["comment_tokens"]
    if any(t in fname for t in ctoks) or any(t in suffix.lower() for t in ctoks) or \
            any(any(f == t or f.startswith(t) for t in ctoks) for f in folders):
        return "COMMENT"
    atoks = cfg["archive_tokens"]
    for f in folders:
        words = re.split(r"[^a-z0-9]+", f)
        if any(f == t or f.startswith(t) for t in atoks) or any(w in atoks for w in words if w):
            return "ARCHIVE"
    if role == "PROD" and folders:
        staging = [s.lower() for s in cfg["prod_staging_folders"]]
        if folders[0] in staging:
            return "STAGING"
    return "ACTIVE"


def _list_dir(path):
    """One network round trip: sub folders + (name, size, mtime) of Excel files."""
    dirs, xls = [], []
    with os.scandir(path) as it:
        for e in it:
            try:
                if e.is_dir(follow_symlinks=False):
                    if not e.name.startswith(("~", "$")):
                        dirs.append(e.path)
                elif e.name.lower().endswith((".xlsx", ".xlsm")) and not e.name.startswith("~$"):
                    st = e.stat()
                    xls.append((e.name, st.st_size, st.st_mtime))
            except OSError:
                continue
    return dirs, xls


def discover(cfg: Config, progress=None, cancel=None):
    """Walk the four source folders in parallel (network shares are latency bound).
    Returns (list[BomFile], list[str] other_xlsx, list[str] errors)."""
    found, others, errors = [], [], []
    tops = {}
    for role in ("PROD", "WP", "DCN", "ECN"):
        top = str(cfg.root_path(role))
        if os.path.isdir(top):
            tops[role] = top
        else:
            errors.append(f"{role}: folder not reachable - {top}")

    n_dirs = 0
    with ThreadPoolExecutor(max_workers=max(8, int(cfg.get("workers", 8)) * 3)) as ex:
        pending = {ex.submit(_list_dir, top): (role, top) for role, top in tops.items()}
        while pending:
            if cancel and cancel():
                ex.shutdown(cancel_futures=True)
                break
            done = next(as_completed(pending))
            role, path = pending.pop(done)
            n_dirs += 1
            try:
                dirs, xls = done.result()
            except OSError as e:
                errors.append(f"{role}: {e}")
                continue
            for d in dirs:
                pending[ex.submit(_list_dir, d)] = (role, d)
            top = tops[role]
            for fn, size, mtime in xls:
                full = os.path.join(path, fn)
                rel = os.path.relpath(full, top)
                m = BOM_NAME.match(fn)
                if not m or any(t in fn.lower() for t in cfg.get("skip_name_tokens", [])):
                    others.append(f"{role}\\{rel}")
                    continue
                g = m.groupdict()
                suffix = g["suffix"].strip(" -_")
                bf = BomFile(role=role, path=full, rel=rel, name=fn, ship=g["ship"], block=g["block"].upper(),
                             phase=g["phase"], disc=g["disc"].upper(), rev=int(g["rev"]), suffix=suffix,
                             size=size, mtime=mtime)
                bf.loc = classify_location(cfg, role, rel, suffix)
                found.append(bf)
            if progress and n_dirs % 25 == 0:
                progress(f"Scanning folders… {n_dirs:,} folders, {len(found):,} BOM files found")
    if progress:
        progress(f"Scanned {n_dirs:,} folders, {len(found):,} BOM files found")
    found.sort(key=lambda f: (f.role, f.rel))
    return found, others, errors


# ---------------------------------------------------------------- reading
class Cache:
    def __init__(self):
        self.path = cache_dir() / "bomcache.sqlite"
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS f(path TEXT PRIMARY KEY, size INT, mtime REAL, payload TEXT)")
        self.db.commit()

    def get(self, bf: BomFile):
        with self.lock:
            r = self.db.execute("SELECT size, mtime, payload FROM f WHERE path=?", (bf.path,)).fetchone()
        if r and r[0] == bf.size and abs(r[1] - bf.mtime) < 1e-3:
            p = json.loads(r[2])
            # older parser results stay valid unless the file failed to parse back then
            if p.get("v", 1) == PARSER_VERSION or not p.get("error"):
                return p
        return None

    def put(self, bf: BomFile, payload: dict):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO f VALUES(?,?,?,?)",
                            (bf.path, bf.size, bf.mtime, json.dumps(payload, ensure_ascii=False)))

    def commit(self):
        with self.lock:
            self.db.commit()


def _read_workbook(path: str) -> dict:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = wb.worksheets
        ordered = sorted(sheets, key=lambda s: 0 if "bom" in s.title.lower() else 1)
        for ws in ordered:
            it = ws.iter_rows(values_only=True)
            header_idx, colmap, extra, buffered, warn = None, {}, [], [], ""
            for i, row in enumerate(it):
                buffered.append(row)
                norm = [_norm_header(c) for c in row]
                hits = {n: j for j, n in enumerate(norm) if n in _HEADER_LOOKUP}
                has_mat = any(_HEADER_LOOKUP[n] == "material" for n in hits)
                if (has_mat and len(hits) >= 5) or len(hits) >= 8:
                    header_idx = i
                    for n, j in hits.items():
                        colmap.setdefault(_HEADER_LOOKUP[n], j)
                    if not has_mat and norm and not norm[0]:
                        colmap["material"] = 0          # header cell left blank
                        warn = "Material No. header cell is blank"
                    extra = [(j, str(row[j]).strip()) for j, n in enumerate(norm)
                             if n and n not in _HEADER_LOOKUP]
                    break
                if i > 15:
                    break
            if header_idx is None:
                continue
            rows, blank_run = [], 0
            for row in it:
                vals = {f: norm_value(row[j]) if j < len(row) else "" for f, j in colmap.items()}
                for j, h in extra:
                    vals["x:" + h] = norm_value(row[j]) if j < len(row) else ""
                if not any(vals.values()):
                    blank_run += 1
                    if blank_run > 20:
                        break
                    continue
                blank_run = 0
                rows.append(vals)
            return {"sheet": ws.title, "rows": rows, "extra": [h for _, h in extra], "error": "", "warn": warn}
        return {"sheet": "", "rows": [], "extra": [], "error": "No sheet with a 'Material No.' header found", "warn": ""}
    finally:
        wb.close()


def content_hash(rows: list) -> str:
    """Order-independent fingerprint of the BOM lines (all columns)."""
    lines = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
    return hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()


def load_all(cfg: Config, files: list, progress=None, cancel=None):
    cache = Cache()
    todo = []
    for bf in files:
        hit = cache.get(bf)
        if hit is not None:
            _apply(bf, hit)
        else:
            todo.append(bf)
    done = len(files) - len(todo)
    if progress:
        progress(f"Reading {len(todo)} changed files ({done} from cache)", done, len(files))

    def work(bf):
        try:
            payload = _read_workbook(bf.path)
        except Exception as e:  # noqa: BLE001 - any unreadable workbook is reported, not fatal
            payload = {"sheet": "", "rows": [], "extra": [], "error": f"{type(e).__name__}: {e}", "warn": ""}
        payload["hash"] = content_hash(payload["rows"]) if payload["rows"] else ""
        payload["v"] = PARSER_VERSION
        return bf, payload

    with ThreadPoolExecutor(max_workers=int(cfg.get("workers", 8))) as ex:
        futs = [ex.submit(work, bf) for bf in todo]
        for fut in as_completed(futs):
            if cancel and cancel():
                ex.shutdown(cancel_futures=True)
                break
            bf, payload = fut.result()
            _apply(bf, payload)
            cache.put(bf, payload)
            done += 1
            if progress:
                progress(bf.name, done, len(files))
    cache.commit()


def _apply(bf: BomFile, p: dict):
    bf.rows = p["rows"]
    bf.sheet = p["sheet"]
    bf.extra_headers = p["extra"]
    bf.error = p["error"]
    bf.warn = p.get("warn", "")
    bf.content_hash = p.get("hash", "")
