"""명령줄 실행 (창 없이).

  AlohaBOM.exe --scan            세 폴더를 읽고 비교해서 이력에 기록 (Windows 작업 스케줄러에서 매일 실행)
  AlohaBOM.exe --report [폴더]   비교 후 엔지니어 리포트를 만든다
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import engine, report
from .config import load_config


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="AlohaBOM")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--report", nargs="?", const="", default=None)
    ap.add_argument("--split", action="store_true", help="구역별 파일로 나누기")
    a = ap.parse_args(argv)
    cfg = load_config()
    res = engine.run(cfg, record=True)
    log = cfg.history_path.with_suffix(".log")
    lines = [f"{res.at:%Y-%m-%d %H:%M:%S} scan"] + [f"  ! {e}" for e in res.errors] + [f"  - {w}" for w in res.warnings]
    if res.ok:
        for h in res.comparison.hulls():
            s1, s2 = res.comparison.stage_stats(h, "sap"), res.comparison.stage_stats(h, "purchase")
            lines.append(f"  {h}: SAP 차이 {s1['dev']}, 구매 차이 {s2['dev']}")
    if a.report is not None and res.ok:
        h = engine.history_for(cfg, res.demo)
        try:
            out = Path(a.report) if a.report else cfg.report_path
            paths = report.write_report(res.comparison, out, {s: str(f.path) for s, f in res.files.items()},
                                        h.item_info(), h.since_last_report(), split=a.split)
            h.record_report(";".join(map(str, paths)), report.report_keys(res.comparison))
            lines += [f"  report: {p}" for p in paths]
        finally:
            h.close()
    try:
        with open(log, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    if sys.stdout:  # 창 모드 exe에서는 stdout이 없다
        print("\n".join(lines))
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
