"""Cross-check the BOM files and build the per-ship master BOM."""
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .config import Config
from .scanner import BomFile, FIELD_IDS, FIELD_TITLE, content_hash

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
SEV_RANK = {ERROR: 3, WARN: 2, INFO: 1, None: 0}

# code -> (severity, title, corrective action)
ISSUE_TYPES = {
    "SAME_NAME_DIFF": (ERROR, "Same file name & revision, different content",
                       "Decide which copy is correct, overwrite the others, or issue a new revision."),
    "WP_CONTENT_DIFF": (ERROR, "Work Package BOM differs from Prod DWG (same revision)",
                        "Replace the Work Package copy with the Prod DWG BOM, or issue a new revision."),
    "CN_CONTENT_DIFF": (ERROR, "DCN/ECN BOM differs from Prod DWG / Work Package (same revision)",
                        "Align the DCN/ECN attachment, Prod DWG and Work Package copies."),
    "SAME_REV_DIFF": (WARN, "Re-saved copy of a revision has different content",
                      "A date-suffixed copy changed without a revision bump. Confirm which is valid and archive the other."),
    "HEADER_FORMAT": (WARN, "BOM sheet header is not in the standard format",
                      "Restore the standard 'Master Bom Sheet' header row."),
    "WP_OUTDATED": (ERROR, "Work Package holds an older revision",
                    "Copy the latest Prod DWG BOM into the Work Package and archive the old one."),
    "WP_AHEAD": (ERROR, "Work Package revision is newer than Prod DWG",
                 "Put the newer revision into 16 Prod DWG (Prod DWG must hold every released BOM)."),
    "WP_MISSING": (WARN, "BOM not found in any Work Package",
                   "Add the BOM to its Work Package if the package has been issued."),
    "WP_ONLY": (ERROR, "BOM exists in Work Package but not in Prod DWG",
                "Add the BOM to 16 Prod DWG or remove the stray copy."),
    "CN_NOT_IN_PROD": (ERROR, "DCN/ECN BOM revision missing from Prod DWG",
                       "Update 16 Prod DWG with the BOM revision issued by the DCN/ECN."),
    "CN_NOT_IN_WP": (ERROR, "DCN/ECN BOM revision missing from Work Package",
                     "Update the Work Package with the BOM revision issued by the DCN/ECN."),
    "PROD_LATEST_ARCHIVED": (WARN, "Latest revision only exists in an archive folder",
                             "Move the latest revision back to the active BOM folder, or confirm it was withdrawn."),
    "MULTI_ACTIVE": (WARN, "Several revisions left in the active folder",
                     "Move superseded revisions into the Arch folder."),
    "STAGING_ONLY": (WARN, "BOM only found in a work-in-progress folder",
                     "Release the BOM into its block 3-BOMS folder when approved."),
    "SHIP_MISMATCH": (ERROR, "Ship No. in the BOM lines is not the hull in the file name",
                      "Set Ship No. to the hull of the file before SAP upload (otherwise lines load to the wrong hull)."),
    "HEADER_MISMATCH": (ERROR, "Block / Phase / Discipline in the lines disagree with the file name",
                        "Correct Block / Phase / Discipline in the BOM lines or rename the file."),
    "DUP_MATERIAL_IN_FILE": (ERROR, "Material No. repeated inside one BOM",
                             "Merge or renumber the duplicate lines."),
    "DUP_MATERIAL_ACROSS": (ERROR, "Material No. used in more than one BOM",
                            "Each Material No. must belong to one BOM. Renumber or remove the duplicate."),
    "READ_ERROR": (ERROR, "BOM file could not be read", "Open the file, fix or re-save it."),
    "EMPTY_BOM": (WARN, "BOM has no lines", "Confirm the BOM is intentionally empty."),
}

WP_LABEL = {
    "SYNC": "In sync", "OUTDATED": "WP outdated", "MISMATCH": "Content differs", "MISSING": "Not in WP",
    "AHEAD": "WP ahead", "WP_ONLY": "WP only", "NO_PROD": "-",
}
CN_LABEL = {"NONE": "-", "MATCH": "Matches", "MISMATCH": "Differs", "MISSING": "Rev missing"}


@dataclass
class Issue:
    code: str
    key: str
    rev: str
    detail: str
    files: list = field(default_factory=list)   # BomFile objects involved
    ack: dict = None                            # set when a user acknowledged it as a known minor alarm

    @property
    def sev(self):
        return ISSUE_TYPES[self.code][0]

    @property
    def sig(self) -> str:
        """Stable identity of this exact problem. Includes each file's content fingerprint, so an
        acknowledgement stops applying as soon as one of the files changes."""
        files = "|".join(sorted(f"{f.path.lower()}#{f.content_hash[:12]}" for f in self.files))
        return f"{self.code}|{self.key}|{self.rev}|{files}"

    @property
    def title(self):
        return ISSUE_TYPES[self.code][1]

    @property
    def action(self):
        return ISSUE_TYPES[self.code][2]

    @property
    def ship(self):
        return self.key.split("-")[0]

    @property
    def roles(self):
        """The source folders this problem belongs to (for the four folder columns)."""
        c = self.code
        if c in ("WP_OUTDATED", "WP_AHEAD", "WP_CONTENT_DIFF", "WP_MISSING"):
            return {"WP"}
        if c in ("WP_ONLY", "PROD_LATEST_ARCHIVED", "STAGING_ONLY", "DUP_MATERIAL_ACROSS"):
            return {"PROD"}
        if c == "CN_CONTENT_DIFF":
            return {self.files[0].role}
        if c == "CN_NOT_IN_PROD":
            return {self.files[0].role, "PROD"}
        if c == "CN_NOT_IN_WP":
            return {self.files[0].role, "WP"}
        return {f.role for f in self.files}


ROLES = ("PROD", "WP", "DCN", "ECN")
ROLE_TITLE = {"PROD": "16 Prod DWG", "WP": "17 Work Package", "DCN": "03 DCN", "ECN": "04 ECN"}


@dataclass
class KeyStatus:
    key: str
    ship: str
    block: str
    phase: str
    disc: str
    files: list = field(default_factory=list)
    prod: BomFile = None
    prod_rev: int = None
    wp: BomFile = None
    wp_rev: int = None
    wp_status: str = "NO_PROD"
    cn_files: list = field(default_factory=list)
    cn_status: str = "NONE"
    issues: list = field(default_factory=list)
    baseline_of: str = None     # sister hull: key of the baseline hull BOM used as Prod DWG reference

    @property
    def open_issues(self):
        """Issues that still need attention (acknowledged minor alarms excluded)."""
        return [i for i in self.issues if not i.ack]

    @property
    def acked_issues(self):
        return [i for i in self.issues if i.ack]

    @property
    def worst(self):
        return max((i.sev for i in self.open_issues), key=lambda s: SEV_RANK[s], default=None)

    @property
    def group(self):
        return self.block[:1]

    def folder(self, role):
        """(text, kind) for one source folder. kind: OK / WARN / ERROR / NONE / ACK."""
        iss = [i for i in self.open_issues if role in i.roles]
        n_ack = sum(1 for i in self.acked_issues if role in i.roles)
        sev = max((i.sev for i in iss), key=lambda s: SEV_RANK[s], default=None)
        if not iss and n_ack:
            text, _kind = self._folder_text(role, None)
            text = "Missing" if text == "—" else text.replace("  ✓", "")
            return f"{text}  · {n_ack} ack'd", "ACK"
        return self._folder_text(role, sev, iss)

    def _folder_text(self, role, sev, iss=()):
        fl = [f for f in self.files if f.role == role and f.loc != "COMMENT"]
        if role == "PROD":
            if not self.prod:
                return ("Missing", sev or "ERROR") if self.wp or self.cn_files else ("—", "NONE")
            text = f"R{self.prod_rev}"
            if self.baseline_of:
                text += f" (via {self.prod.ship})"
            elif self.prod.loc == "STAGING":
                text += " WIP"
        elif role == "WP":
            if not self.wp:
                if self.wp_status == "MISSING":
                    return "Missing", sev or "WARN"
                return ("—", "NONE") if not iss else ("Missing", sev)
            text = {"OUTDATED": f"R{self.wp_rev} → R{self.prod_rev}", "AHEAD": f"R{self.wp_rev} > R{self.prod_rev}",
                    "MISMATCH": f"R{self.wp_rev} ≠"}.get(self.wp_status, f"R{self.wp_rev}")
        else:
            if not fl:
                return "—", "NONE"
            text = ", ".join(f"R{r}" for r in sorted({f.rev for f in fl}))
        if not sev:
            return f"{text}  ✓", "OK"
        n = len(iss)
        return f"{text}  · {n} {'issue' if n == 1 else 'issues'}", sev


@dataclass
class Result:
    files: list
    others: list
    scan_errors: list
    keys: dict          # key -> KeyStatus
    issues: list
    master: list        # list of dict rows
    scanned_at: float = field(default_factory=time.time)

    def ships(self):
        return sorted({k.ship for k in self.keys.values()})


def _pick(files, prefer=("ACTIVE", "ARCHIVE")):
    """Highest revision among files whose location is in `prefer`; ties -> first preferred location."""
    cand = [f for f in files if f.loc in prefer]
    if not cand:
        return None
    top = max(f.rev for f in cand)
    best = [f for f in cand if f.rev == top]
    best.sort(key=lambda f: (prefer.index(f.loc), -f.mtime))
    return best[0]


_HASHES = {}


def _hash(f: BomFile, ignore: frozenset) -> str:
    """Fingerprint of the standard SAP columns only (free-text note columns such as REMARK are ignored)."""
    k = (id(f), f.content_hash, ignore)
    h = _HASHES.get(k)
    if h is None:
        keep = [c for c in FIELD_IDS if c not in ignore]
        h = content_hash([{c: r.get(c, "") for c in keep} for r in f.rows])
        _HASHES[k] = h
    return h


def _same_content(a: BomFile, b: BomFile, ignore) -> bool:
    if a.error or b.error:
        return True
    if a.content_hash == b.content_hash:
        return True
    ig = frozenset(ignore)
    return _hash(a, ig) == _hash(b, ig)


def analyze(cfg: Config, files: list, others: list, scan_errors: list) -> Result:
    ignore = set(cfg.get("compare_ignore_fields", []))
    exempt = {s.upper() for s in cfg.get("dup_exempt_status", [])}
    baseline = cfg.get("baseline_ship", "")
    by_key = defaultdict(list)
    for f in files:
        by_key[f.key].append(f)
    prod_ships = {f.ship for f in files if f.role == "PROD"}
    keys, issues = {}, []

    def add(ks, code, rev, detail, fl):
        it = Issue(code, ks.key, rev, detail, list(fl))
        ks.issues.append(it)
        issues.append(it)

    def same(a, b, sister=False):
        ign = ignore | {"ship_no"} if sister else ignore
        return _same_content(a, b, ign)

    # hulls with their own Prod DWG BOMs first, so sister hulls can reference them
    order = sorted(by_key.items(), key=lambda kv: (kv[1][0].ship not in prod_ships, kv[0]))
    for key, fl in order:
        f0 = fl[0]
        ks = KeyStatus(key, f0.ship, f0.block, f0.phase, f0.disc, files=sorted(fl, key=lambda f: (f.role, f.rev, f.loc)))
        keys[key] = ks
        prod_files = [f for f in fl if f.role == "PROD"]
        wp_files = [f for f in fl if f.role == "WP"]
        ks.cn_files = [f for f in fl if f.role in ("DCN", "ECN") and f.loc != "COMMENT"]

        # sister hull without Prod DWG BOMs -> reference the baseline hull's Prod DWG
        sister = False
        if not prod_files and ks.ship not in prod_ships and baseline and ks.ship != baseline:
            base = keys.get(f"{baseline}-{ks.block}-{ks.phase}-{ks.disc}")
            if base:
                prod_files = [f for f in base.files if f.role == "PROD"]
                ks.baseline_of = base.key
                sister = True

        # ---- per-file sanity
        for f in fl:
            if f.loc == "COMMENT":
                continue
            if f.error:
                add(ks, "READ_ERROR", f"R{f.rev}", f"{f.role}: {f.error}", [f])
                continue
            if f.warn:
                add(ks, "HEADER_FORMAT", f"R{f.rev}", f"{f.role}: {f.warn} — {f.rel}", [f])
            if not f.rows:
                add(ks, "EMPTY_BOM", f"R{f.rev}", f"{f.role}: {f.rel}", [f])
                continue
            if f.loc == "ARCHIVE":
                continue
            ship_bad, bad = _header_mismatch(f)
            if ship_bad and folder_hull_matches(f):
                ship_bad = ""      # folder (e.g. xS041, S041-ECN) confirms the hull in the file name
            if ship_bad:
                add(ks, "SHIP_MISMATCH", f"R{f.rev}", f"{f.role}: {ship_bad} — {f.rel}", [f])
            if bad:
                add(ks, "HEADER_MISMATCH", f"R{f.rev}", f"{f.role}: {bad} — {f.rel}", [f])
            seen, dups = set(), set()
            for r in f.rows:
                m = r.get("material", "")
                if not m or r.get("mat_status", "").upper() in exempt or is_deleted(r):
                    continue
                if m in seen:
                    dups.add(m)
                seen.add(m)
            if dups:
                add(ks, "DUP_MATERIAL_IN_FILE", f"R{f.rev}",
                    f"{f.role}: {', '.join(sorted(dups)[:8])}{' ...' if len(dups) > 8 else ''}", [f])

        # ---- identical file name + revision anywhere -> identical content
        by_name = defaultdict(list)
        for f in fl:
            if f.loc != "COMMENT" and not f.error:
                by_name[f.name.lower()].append(f)
        for name, group in sorted(by_name.items()):
            if len(group) < 2:
                continue
            ref = sorted(group, key=lambda f: (f.role != "PROD", f.loc != "ACTIVE", -f.mtime))[0]
            diff = [f for f in group if f is not ref and not same(ref, f)]
            if diff:
                add(ks, "SAME_NAME_DIFF", f"R{ref.rev}",
                    f"{ref.name}: {ref.role}\\{ref.rel} vs " + "; ".join(f"{f.role}\\{f.rel}" for f in diff),
                    [ref] + diff)

        # ---- re-saved copies (date / initials suffix) of one revision inside the same source
        for role in ("PROD", "WP"):
            by_rev = defaultdict(list)
            for f in fl:
                if f.role == role and f.loc != "COMMENT" and not f.error:
                    by_rev[f.rev].append(f)
            for rev, group in sorted(by_rev.items()):
                names = {f.name.lower() for f in group}
                if len(names) < 2:
                    continue
                ref = sorted(group, key=lambda f: (f.loc != "ACTIVE", -f.mtime))[0]
                diff = [f for f in group if f.name.lower() != ref.name.lower() and not same(ref, f)]
                if diff:
                    add(ks, "SAME_REV_DIFF", f"R{rev}",
                        f"{role}: {ref.rel} vs " + "; ".join(f.rel for f in diff), [ref] + diff)

        # ---- Prod DWG: latest released revision
        released = [f for f in prod_files if f.loc in ("ACTIVE", "ARCHIVE")]
        staging = [f for f in prod_files if f.loc == "STAGING"]
        ks.prod = _pick(released)
        if ks.prod:
            ks.prod_rev = ks.prod.rev
            if not sister:
                if ks.prod.loc == "ARCHIVE":
                    add(ks, "PROD_LATEST_ARCHIVED", f"R{ks.prod_rev}", ks.prod.rel, [ks.prod])
                act_revs = sorted({f.rev for f in prod_files if f.loc == "ACTIVE"})
                if len(act_revs) > 1:
                    add(ks, "MULTI_ACTIVE", f"R{act_revs[-1]}",
                        f"Prod DWG active folder holds R{', R'.join(map(str, act_revs))}",
                        [f for f in prod_files if f.loc == "ACTIVE"])
        elif staging:
            ks.prod = _pick(staging, ("STAGING",))
            ks.prod_rev = ks.prod.rev
            add(ks, "STAGING_ONLY", f"R{ks.prod_rev}", ks.prod.rel, [ks.prod])
        ref_txt = f"{baseline} Prod DWG" if sister else "Prod DWG"

        # ---- Work Package sync
        ks.wp = _pick(wp_files)
        ks.wp_rev = ks.wp.rev if ks.wp else None
        if ks.prod is None:
            if ks.wp:
                ks.wp_status = "WP_ONLY"
                add(ks, "WP_ONLY", f"R{ks.wp_rev}", ks.wp.rel, [ks.wp])
        elif ks.wp is None:
            if not sister:
                ks.wp_status = "MISSING"
                add(ks, "WP_MISSING", f"R{ks.prod_rev}", f"Prod DWG latest R{ks.prod_rev}", [ks.prod])
        elif ks.wp_rev < ks.prod_rev:
            ks.wp_status = "OUTDATED"
            add(ks, "WP_OUTDATED", f"R{ks.wp_rev}→R{ks.prod_rev}",
                f"WP has R{ks.wp_rev} ({ks.wp.rel}); {ref_txt} latest is R{ks.prod_rev}", [ks.prod, ks.wp])
        elif ks.wp_rev > ks.prod_rev:
            ks.wp_status = "AHEAD"
            add(ks, "WP_AHEAD", f"R{ks.wp_rev}", f"WP R{ks.wp_rev} > {ref_txt} R{ks.prod_rev}", [ks.wp, ks.prod])
        elif same(ks.prod, ks.wp, sister):
            ks.wp_status = "SYNC"
        else:
            ks.wp_status = "MISMATCH"
            add(ks, "WP_CONTENT_DIFF", f"R{ks.wp_rev}", f"{ref_txt} {ks.prod.rel} vs WP {ks.wp.rel}",
                [ks.prod, ks.wp])
        if ks.wp:
            wp_act = sorted({f.rev for f in wp_files if f.loc == "ACTIVE"})
            if len(wp_act) > 1:
                add(ks, "MULTI_ACTIVE", f"R{wp_act[-1]}",
                    f"Work Package active folder holds R{', R'.join(map(str, wp_act))}",
                    [f for f in wp_files if f.loc == "ACTIVE"])

        # ---- DCN / ECN: optional, but whatever exists must be in Prod and WP with the same content
        if ks.cn_files:
            status = "MATCH"
            for cf in ks.cn_files:
                if cf.error:
                    continue
                p = [f for f in prod_files if f.rev == cf.rev and f.loc != "COMMENT" and not f.error]
                w = [f for f in wp_files if f.rev == cf.rev and f.loc != "COMMENT" and not f.error]
                if not p and not sister:
                    status = "MISSING"
                    add(ks, "CN_NOT_IN_PROD", f"R{cf.rev}", f"{cf.role}\\{cf.rel}", [cf])
                if not w:
                    status = "MISSING"
                    add(ks, "CN_NOT_IN_WP", f"R{cf.rev}", f"{cf.role}\\{cf.rel}", [cf])
                bad = [x for x in p + w if not same(cf, x, sister and x.role == "PROD")]
                if bad:
                    if status == "MATCH":
                        status = "MISMATCH"
                    add(ks, "CN_CONTENT_DIFF", f"R{cf.rev}",
                        f"{cf.role}\\{cf.rel} vs " + "; ".join(f"{x.role}\\{x.rel}" for x in bad), [cf] + bad)
            ks.cn_status = status

    # ---- Material No. must be unique across the latest BOMs of a ship (fabricated items)
    owner = defaultdict(list)
    for ks in keys.values():
        if ks.prod and ks.prod.rows and not getattr(ks, "baseline_of", None):
            for m in {r.get("material", "") for r in ks.prod.rows
                      if r.get("mat_status", "").upper() not in exempt and not is_deleted(r)}:
                if m:
                    owner[(ks.ship, m)].append(ks)
    clash = defaultdict(set)
    for (ship, m), kl in owner.items():
        if len(kl) > 1:
            for ks in kl:
                clash[ks.key].add((m, tuple(sorted(k.key for k in kl if k is not ks))))
    for key, items in clash.items():
        ks = keys[key]
        items = sorted(items)
        txt = "; ".join(f"{m} also in {', '.join(o)}" for m, o in items[:6])
        if len(items) > 6:
            txt += f" ... (+{len(items) - 6})"
        it = Issue("DUP_MATERIAL_ACROSS", key, f"R{ks.prod_rev}", txt, [ks.prod])
        ks.issues.append(it)
        issues.append(it)

    master = build_master(cfg, keys)
    issues.sort(key=lambda i: (-SEV_RANK[i.sev], i.key, i.code))
    return Result(files, others, scan_errors, keys, issues, master)


# hull number inside a folder name: S041, xS041, S041-ECN, 1041_E11GC_07_EO_1, DCN-041-...
_HULL_IN_FOLDER = re.compile(r"(?<![0-9])(?:S|1)?(04\d)(?![0-9])", re.I)


def folder_hulls(f: BomFile) -> set:
    """Hull numbers ('041') that appear in the folder names of the file's path."""
    out = set()
    for seg in f.rel.replace("/", "\\").split("\\")[:-1]:
        out.update(m.group(1) for m in _HULL_IN_FOLDER.finditer(seg))
    return out


def folder_hull_matches(f: BomFile) -> bool:
    return f.ship[-3:] in folder_hulls(f)


def _header_mismatch(f: BomFile):
    """Returns (ship problem, other column problems) comparing BOM lines with the file name."""
    probs = []
    checks = (("ship_no", f.ship, "Ship No."), ("block", f.block, "Block"),
              ("phase", f.phase, "Phase"), ("discipline", f.disc, "Discipline"))
    for fid, expect, label in checks:
        vals = Counter(r.get(fid, "") for r in f.rows if fid in r)
        bad = {v: n for v, n in vals.items() if v and v.upper().lstrip("0") != expect.upper().lstrip("0")}
        if bad:
            txt = ", ".join(f"{v} ({n} lines)" for v, n in sorted(bad.items())[:3])
            probs.append((fid, f"{label} {txt}; file name says {expect}"))
    ship = "; ".join(t for fid, t in probs if fid == "ship_no")
    other = "; ".join(t for fid, t in probs if fid != "ship_no")
    return ship, other


FOLDER_COLS = [("f_prod", "16 Prod DWG"), ("f_wp", "17 Work Package"), ("f_dcn", "03 DCN"), ("f_ecn", "04 ECN")]
FOLDER_FIELD = dict(zip(ROLES, (c for c, _ in FOLDER_COLS)))

_LEAD = ("material", "desc1")
MASTER_COLS = [("ship", "Hull"), ("bom", "BOM"), ("material", FIELD_TITLE["material"]),
               ("line_status", "Line Status"), ("desc1", FIELD_TITLE["desc1"])] + FOLDER_COLS + [
    ("overall", "Overall"), ("sap_status", "SAP Upload"), ("po_status", "Purchase Status"), ("eta", "ETA"),
] + [(f, FIELD_TITLE[f]) for f in FIELD_IDS if f not in _LEAD] + [("basis", "Basis"), ("source", "Source File")]

# "Mode" column of the SAP BOM sheet: A = added, C = changed, D = deleted line
LINE_STATUS = {"A": ("Added", "INFO"), "C": ("Changed", "WARN"), "D": ("Deleted", "ERROR"), "M": ("Modified", "WARN")}


def is_deleted(row: dict) -> bool:
    return row.get("mode", "").strip().upper() == "D"


def overall(ks):
    """(text, kind) summarising all four folders."""
    sev = ks.worst
    n_ack = len(ks.acked_issues)
    if not sev:
        return ("All folders OK" + (f" · {n_ack} ack'd" if n_ack else "")), "OK"
    n = len(ks.open_issues)
    return f"{'Needs correction' if sev == ERROR else 'Check'} ({n})", sev


def apply_acks(cfg: Config, res, acks: dict):
    """Mark acknowledged issues and rebuild the master rows (their folder colors depend on it)."""
    for i in res.issues:
        i.ack = acks.get(i.sig)
    res.master = build_master(cfg, res.keys)


def folder_fields(ks) -> dict:
    """Display text + color kind of the four folder columns and the overall column for one BOM."""
    out = {}
    for role in ROLES:
        text, kind = ks.folder(role)
        out[FOLDER_FIELD[role]] = text
        out["_kind:" + FOLDER_FIELD[role]] = kind
    out["overall"], out["_kind:overall"] = overall(ks)
    return out


def build_master(cfg: Config, keys: dict) -> list:
    out = []
    for ks in sorted(keys.values(), key=lambda k: k.key):
        if not ks.prod:
            continue
        common = {
            "ship": cfg.ship_label(ks.ship), "bom": ks.key, "bom_rev": f"R{ks.prod_rev}", "group": ks.group,
            "wp_status": WP_LABEL[ks.wp_status], "cn_status": CN_LABEL[ks.cn_status],
            "sap_status": "", "po_status": "", "eta": "", "source": ks.prod.path,
            "basis": (f"{cfg.ship_label(ks.prod.ship)} Prod DWG (no own Prod BOM)" if ks.baseline_of
                      else ("Prod DWG WIP folder" if ks.prod.loc == "STAGING" else "Prod DWG")),
            "_sev": ks.worst, "_key": ks.key,
        }
        common.update(folder_fields(ks))
        for r in ks.prod.rows:
            row = dict(common)
            for fid in FIELD_IDS:
                row[fid] = r.get(fid, "")
            st = LINE_STATUS.get(r.get("mode", "").strip().upper())
            row["line_status"], row["_kind:line_status"] = st if st else ("", "NONE")
            row["_deleted"] = is_deleted(r)
            out.append(row)
    return out


# ---------------------------------------------------------------- row diff (for the viewer and report)
def row_key(r: dict) -> str:
    return r.get("material") or f"pos:{r.get('pos', '')}"


def diff_rows(a_rows: list, b_rows: list):
    """Returns list of (kind, key, a_row, b_row, changed_fields). kind: CHANGED / ONLY_A / ONLY_B."""
    a = defaultdict(list)
    b = defaultdict(list)
    for r in a_rows:
        a[row_key(r)].append(r)
    for r in b_rows:
        b[row_key(r)].append(r)
    out = []
    for k in sorted(set(a) | set(b)):
        la, lb = a.get(k, []), b.get(k, [])
        for i in range(max(len(la), len(lb))):
            ra = la[i] if i < len(la) else None
            rb = lb[i] if i < len(lb) else None
            if ra is None:
                out.append(("ONLY_B", k, None, rb, []))
            elif rb is None:
                out.append(("ONLY_A", k, ra, None, []))
            else:
                ch = [f for f in sorted(set(ra) | set(rb)) if ra.get(f, "") != rb.get(f, "")]
                if ch:
                    out.append(("CHANGED", k, ra, rb, ch))
    return out
