"""Acknowledged ("known minor") alarms, kept in a JSON file so they survive rescans.

Point `ack_file` in Settings at a shared folder so the whole team sees the same acknowledgements."""
import datetime as dt
import getpass
import json
import os
from pathlib import Path

from .config import config_dir


def ack_path(cfg) -> Path:
    p = (cfg.get("ack_file") or "").strip()
    return Path(p) if p else config_dir() / "acknowledged.json"


def load(cfg) -> dict:
    try:
        return json.loads(ack_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(cfg, data: dict):
    p = ack_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def acknowledge(cfg, issues, note: str) -> dict:
    """Re-read the file first so acknowledgements made by others in the meantime are kept."""
    data = load(cfg)
    stamp = {"by": getpass.getuser(), "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "note": note.strip()}
    for i in issues:
        data[i.sig] = dict(stamp, code=i.code, bom=i.key, rev=i.rev, title=i.title)
    _write(cfg, data)
    return data


def unacknowledge(cfg, issues) -> dict:
    data = load(cfg)
    for i in issues:
        data.pop(i.sig, None)
    _write(cfg, data)
    return data
