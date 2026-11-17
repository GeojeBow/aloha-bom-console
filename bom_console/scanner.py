"""각 폴더에서 가장 최신 BOM 파일을 고른다."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    source: str
    path: Path
    mtime: float
    size: int

    @property
    def signature(self) -> tuple:
        return (str(self.path), self.mtime, self.size)

    @property
    def modified(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self.mtime)

    def age_days(self, now: dt.datetime | None = None) -> float:
        return ((now or dt.datetime.now()) - self.modified).total_seconds() / 86400


def newest_file(folder: str | Path, patterns: str, source: str) -> SourceFile | None:
    """폴더(하위 폴더 제외)에서 패턴에 맞는 파일 중 수정 시각이 가장 늦은 것. 엑셀 임시파일(~$)은 제외."""
    folder = Path(folder)
    if not folder.is_dir():
        return None
    best: SourceFile | None = None
    for pat in [p.strip() for p in patterns.split(";") if p.strip()]:
        for f in folder.glob(pat):
            if not f.is_file() or f.name.startswith("~$"):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if best is None or st.st_mtime > best.mtime:
                best = SourceFile(source, f, st.st_mtime, st.st_size)
    return best
