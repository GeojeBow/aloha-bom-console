"""스캔 → 읽기 → 비교 → 이력 기록을 한 번에."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .compare import Comparison, compare
from .config import SOURCE_LABELS, SOURCES, AppConfig, app_dir
from .history import History
from .reader import ReadResult, read_bom
from .scanner import SourceFile, newest_file


@dataclass
class RunResult:
    files: dict[str, SourceFile | None]
    reads: dict[str, ReadResult] = field(default_factory=dict)
    comparison: Comparison | None = None
    new_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    demo: bool = False
    at: dt.datetime = field(default_factory=dt.datetime.now)

    @property
    def ok(self) -> bool:
        return self.comparison is not None

    @property
    def warnings(self) -> list[str]:
        w = []
        for r in self.reads.values():
            w += r.warnings
        if self.comparison:
            w += self.comparison.warnings
        return w


def source_folders(cfg: AppConfig) -> tuple[dict[str, str], bool]:
    """설정된 폴더. 아직 설정 전이고 예시 모드면 예시 데이터 폴더를 쓴다."""
    if cfg.configured() or not cfg.demo:
        return dict(cfg.folders), False
    from .sample import ensure_demo
    return ensure_demo(), True


def history_for(cfg: AppConfig, demo: bool) -> History:
    return History(app_dir() / "demo" / "history.sqlite" if demo else cfg.history_path)


def scan(cfg: AppConfig) -> tuple[dict[str, SourceFile | None], bool]:
    folders, demo = source_folders(cfg)
    return {s: newest_file(folders.get(s, ""), cfg.patterns, s) for s in SOURCES}, demo


def run(cfg: AppConfig, record: bool = True, today: dt.date | None = None) -> RunResult:
    files, demo = scan(cfg)
    res = RunResult(files=files, demo=demo)
    for s in SOURCES:
        f = files[s]
        if not f:
            res.errors.append(f"{SOURCE_LABELS[s]} 폴더에서 BOM 파일을 찾지 못했습니다.")
            continue
        try:
            res.reads[s] = read_bom(f.path, cfg.aliases, cfg.hulls)
        except Exception as e:  # 열려 있는 파일, 손상된 파일 등
            res.errors.append(f"{SOURCE_LABELS[s]} 파일을 읽지 못했습니다 ({f.path.name}): {e}")
    if len(res.reads) < 3:
        return res
    res.comparison = compare(res.reads["design"].items, res.reads["sap"].items, res.reads["purchase"].items,
                             cfg.area_rules, today=today)
    if record:
        h = history_for(cfg, demo)
        try:
            if demo:
                from .sample import seed_history
                seed_history(h, res.comparison, today)
            for s in SOURCES:
                f = files[s]
                if h.mark_file_seen(s, str(f.path), f.mtime, f.size):
                    res.new_files.append(s)
            h.record(res.comparison, {s: str(files[s].path) for s in SOURCES})
        finally:
            h.close()
    return res
