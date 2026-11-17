"""Self-update: compare with <update_dir>\\version.json and swap the running exe for the newer one."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import VERSION


def _v(s):
    return tuple(int(x) for x in str(s).split(".") if x.isdigit())


def available_update(cfg):
    """Returns (version, exe_path, notes) when the release folder holds a newer build, else None."""
    if not getattr(sys, "frozen", False):
        return None
    rel = Path(cfg.get("update_dir") or "")
    vf = rel / "version.json"
    try:
        info = json.loads(vf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    new_exe = rel / info.get("file", "BOM_Master.exe")
    if _v(info.get("version", "0")) <= _v(VERSION) or not new_exe.exists():
        return None
    try:
        if Path(sys.executable).resolve() == new_exe.resolve():
            return None
    except OSError:
        pass
    return info.get("version"), new_exe, info.get("notes", "")


def apply_update(new_exe: Path):
    """Copy the new build next to the running exe and hand over to a helper script that swaps and restarts."""
    cur = Path(sys.executable)
    staged = cur.with_name(cur.stem + ".new.exe")
    shutil.copy2(new_exe, staged)
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"bom_master_update_{pid}.cmd"
    bat.write_text(
        "@echo off\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL && (timeout /t 1 /nobreak >NUL & goto wait)\r\n'
        f'move /y "{staged}" "{cur}" >NUL\r\n'
        f'start "" "{cur}"\r\n'
        'del "%~f0"\r\n',
        encoding="mbcs",
    )
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000, close_fds=True)  # CREATE_NO_WINDOW
