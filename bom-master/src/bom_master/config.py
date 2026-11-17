"""User settings, stored as JSON under %APPDATA%\\BOMMaster."""
import json
import os
from pathlib import Path

from . import APP_ID


def _onedrive_release_dir() -> str:
    od = os.environ.get("OneDriveCommercial") or os.environ.get("OneDrive") or ""
    return str(Path(od) / "Claude_BOM" / "release") if od else ""


DEFAULTS = {
    "base": r"N:\Projects\040-042 Aloha-L\300 Engineering\03_360 Electrical",
    # source role -> sub folder of base
    "roots": {
        "PROD": "16 Prod DWG",
        "WP": "17 Work Packages",
        "DCN": "03 DCN",
        "ECN": "04 ECN",
    },
    "ships": {"1040": "S040", "1041": "S041", "1042": "S042"},
    # A path segment equal to / starting with one of these marks an old copy.
    "archive_tokens": ["arch", "archive", "old", "superseded", "obsolete", "backup", "history", "previous", "void"],
    # A file or folder containing one of these is a review / markup copy, not a BOM release.
    "comment_tokens": ["comment", "reviewed", "review", "markup", "redline", "-com-", "_com_", "-com.", "com-psg",
                       "com-osg", "deleted", "added"],
    # File names that match the BOM pattern but are not BOMs.
    "skip_name_tokens": ["cover sheet", "coversheet"],
    # Hulls without their own Prod DWG BOMs are checked against this hull's Prod DWG.
    "baseline_ship": "1040",
    # Material status that may legitimately repeat across BOMs (purchased items).
    "dup_exempt_status": ["P"],
    "compare_ignore_fields": [],
    # Top-level folders inside Prod DWG that hold work-in-progress, not released BOMs.
    "prod_staging_folders": ["0 Prod DWG Recovery Plan", "1 Under Review", "3. BOMs to proceed"],
    "update_dir": _onedrive_release_dir(),
    # Acknowledged minor alarms. Empty = this PC only; set a shared path to share them with the team.
    "ack_file": "",
    "sap_file": "",
    "purchase_file": "",
    "master_bom_file": "",         # 전장설계 Master BOM (hand-compiled) to verify against the folders
    "master_check_ignore": [],      # BOM columns not compared in the Master BOM check
    "workers": 8,
}


def config_dir() -> Path:
    d = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


class Config(dict):
    path = None

    @classmethod
    def load(cls) -> "Config":
        cfg = cls(json.loads(json.dumps(DEFAULTS)))
        cls.path = config_dir() / "config.json"
        if cls.path.exists():
            try:
                stored = json.loads(cls.path.read_text(encoding="utf-8"))
                for k, v in stored.items():
                    if k in cfg:
                        cfg[k] = v
            except (OSError, ValueError):
                pass
        if not cfg.get("update_dir"):
            cfg["update_dir"] = _onedrive_release_dir()
        return cfg

    def save(self):
        self.path.write_text(json.dumps(self, indent=2, ensure_ascii=False), encoding="utf-8")

    def root_path(self, role: str) -> Path:
        return Path(self["base"]) / self["roots"][role]

    def ship_label(self, ship_no: str) -> str:
        return self["ships"].get(ship_no, ship_no)
