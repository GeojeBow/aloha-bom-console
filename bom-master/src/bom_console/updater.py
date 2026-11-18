"""자동 업데이트.

배포 방법: 공용 폴더(설정의 '업데이트 폴더', 예: N:\\...\\AlohaBOM\\release)에
  AlohaBOM.exe  와  version.json  ({"version": "0.2.0", "file": "AlohaBOM.exe", "notes": "..."})
을 올려 두면, 각자 PC의 exe가 켜질 때 버전을 비교해서 스스로 교체하고 다시 켜진다.
인터넷 연결은 필요 없다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__

DEFAULT_FILE = "AlohaBOM.exe"


def parse_version(v: str) -> tuple:
    out = []
    for part in str(v).strip().lstrip("vV").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out + [0] * (3 - len(out)))


@dataclass
class UpdateInfo:
    version: str
    exe: Path
    notes: str = ""


def check(update_dir: str, current: str = __version__) -> UpdateInfo | None:
    if not update_dir:
        return None
    d = Path(update_dir)
    vf = d / "version.json"
    try:
        data = json.loads(vf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ver = str(data.get("version", "0"))
    exe = d / data.get("file", DEFAULT_FILE)
    if parse_version(ver) > parse_version(current) and exe.is_file():
        return UpdateInfo(ver, exe, str(data.get("notes", "")))
    return None


def can_self_update() -> bool:
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def apply(info: UpdateInfo) -> bool:
    """새 exe를 내려받아 두고, 지금 프로세스가 끝나면 교체 후 다시 실행하는 배치 파일을 띄운다.

    True면 호출한 쪽은 즉시 프로그램을 종료해야 한다.
    """
    if not can_self_update():
        return False
    current = Path(sys.executable).resolve()
    staged = current.with_name(current.stem + ".new.exe")
    try:
        shutil.copy2(info.exe, staged)
    except OSError:
        return False
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"alohabom_update_{pid}.bat"
    bat.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        ":wait\r\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)\r\n'
        f'move /Y "{staged}" "{current}" >nul\r\n'
        f'start "" "{current}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)
    return True
