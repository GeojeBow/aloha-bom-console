"""One-click copy for 'missing / outdated' problems between 16 Prod DWG and 17 Work Packages.

Nothing is ever overwritten: if the destination file already exists the copy is refused."""
import csv
import dataclasses
import datetime as dt
import getpass
import os
import re
import shutil
import time
from dataclasses import dataclass

from .config import Config, config_dir

# code -> (source, target role, human description)
COPYABLE = {
    "WP_MISSING": ("prod", "WP", "Copy the Prod DWG BOM into its Work Package folder"),
    "WP_OUTDATED": ("prod", "WP", "Copy the latest Prod DWG BOM into the Work Package folder"),
    "WP_ONLY": ("wp", "PROD", "Copy the Work Package BOM into its Prod DWG folder"),
    "WP_AHEAD": ("wp", "PROD", "Copy the newer Work Package BOM into the Prod DWG folder"),
    "CN_NOT_IN_PROD": ("cn", "PROD", "Copy the DCN/ECN BOM revision into the Prod DWG folder"),
    "CN_NOT_IN_WP": ("cn", "WP", "Copy the DCN/ECN BOM revision into the Work Package folder"),
}


@dataclass
class CopyPlan:
    issue: object
    src: object             # BomFile
    target_role: str
    dest_dir: str           # may not exist yet (then it is created)
    old: object = None      # BomFile in the target that this copy supersedes (can be moved to Arch)
    how: str = ""           # how the destination folder was found

    @property
    def dest_path(self):
        return os.path.join(self.dest_dir, self.src.name) if self.dest_dir else ""

    @property
    def what(self):
        return COPYABLE[self.issue.code][2]


def can_copy(issue) -> bool:
    return issue.code in COPYABLE


def plan_copy(cfg: Config, res, issue):
    if issue.code not in COPYABLE:
        return None
    ks = res.keys[issue.key]
    source, target, _ = COPYABLE[issue.code]
    src = {"prod": ks.prod, "wp": ks.wp, "cn": issue.files[0] if issue.files else None}[source]
    if src is None or ks.baseline_of and source == "prod":
        return None           # sister hull: its Prod DWG reference belongs to another hull
    old = None
    if issue.code == "WP_OUTDATED" and ks.wp and ks.wp.loc == "ACTIVE":
        old = ks.wp
    if issue.code == "WP_AHEAD" and ks.prod and ks.prod.loc == "ACTIVE":
        old = ks.prod
    dest, how = find_folder(cfg, res, ks, target)
    return CopyPlan(issue, src, target, dest or "", old, how)


def _is_arch(name, cfg):
    low = name.lower()
    return any(low == t or low.startswith(t) for t in cfg["archive_tokens"])


def find_folder(cfg, res, ks, role):
    """Folder in `role` where this BOM belongs: where its other revisions live, else derived from a
    sibling BOM of the same hull, block group, phase and discipline."""
    own = [f for f in ks.files if f.role == role and f.loc in ("ACTIVE", "ARCHIVE")]
    own.sort(key=lambda f: (f.loc != "ACTIVE", -f.rev))
    for f in own:
        d = os.path.dirname(f.path)
        while _is_arch(os.path.basename(d), cfg) or re.fullmatch(r"[\d ._-]{6,}", os.path.basename(d)):
            d = os.path.dirname(d)       # climb out of Arch\2026 05 29\ etc.
        return d, f"same folder as {f.name}"
    sibs = [f for f in res.files if f.role == role and f.ship == ks.ship and f.loc == "ACTIVE"
            and f.block != ks.block and f.block[:1] == ks.block[:1]]
    for strict in (True, False):
        for f in sorted(sibs, key=lambda f: f.path):
            if f.phase != ks.phase or (strict and f.disc != ks.disc):
                continue
            folder = os.path.dirname(f.path)
            name = os.path.basename(folder)
            if f.block not in name:
                continue
            new = name.replace(f.block, ks.block)
            if not strict:
                new = re.sub(rf"(?<=[-_]){f.disc}(?=$|[-_ ])", ks.disc, new)
            return os.path.join(os.path.dirname(folder), new), f"named like the folder of {f.key}"
    return None, "no matching folder found — choose one"


def execute(cfg: Config, plan: CopyPlan, dest_dir: str, archive_old: bool):
    """Copy (and optionally archive the superseded file). Returns (new_file, moved_old_or_None)."""
    dest = os.path.join(dest_dir, plan.src.name)
    if os.path.exists(dest):
        raise FileExistsError(f"A file with this name already exists:\n{dest}\nNothing was copied.")
    arch_target = None
    if archive_old and plan.old:
        arch_dir = os.path.join(os.path.dirname(plan.old.path), "Arch")
        arch_target = os.path.join(arch_dir, plan.old.name)
        if os.path.exists(arch_target):
            raise FileExistsError(f"The Arch folder already holds:\n{arch_target}\nNothing was copied.")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(plan.src.path, dest)
    moved = None
    if arch_target:
        os.makedirs(os.path.dirname(arch_target), exist_ok=True)
        shutil.move(plan.old.path, arch_target)
        moved = dataclasses.replace(plan.old, path=arch_target, loc="ARCHIVE",
                                    rel=os.path.relpath(arch_target, str(cfg.root_path(plan.old.role))))
    new = dataclasses.replace(plan.src, role=plan.target_role, path=dest, loc="ACTIVE", mtime=time.time(),
                              rel=os.path.relpath(dest, str(cfg.root_path(plan.target_role))))
    _log(plan, dest, arch_target)
    return new, moved


def log_path():
    return config_dir() / "copy_log.csv"


def _log(plan, dest, arch_target):
    p = log_path()
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["When", "Who", "Issue", "BOM", "Copied from", "Copied to", "Old file moved to"])
        w.writerow([dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), getpass.getuser(), plan.issue.title,
                    plan.issue.key, plan.src.path, dest, arch_target or ""])
