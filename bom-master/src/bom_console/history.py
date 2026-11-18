"""비교 이력 (SQLite).

- daily: 날짜 × 호선 × 단계 × 구역 × 종류별 건수. 하루에 여러 번 비교하면 마지막 결과로 덮어쓴다.
- item_state: 항목 × 단계별 최초 발견일, 해결일, 리포트에 올라간 횟수.
- reports: 리포트 발송 기록.
N: 공용 폴더에 두면 여러 사람이 같은 이력을 본다 (SQLite는 동시에 한 명만 쓰도록 짧은 트랜잭션만 사용).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .compare import CATS, STAGES, Comparison

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, ts TEXT, day TEXT, design TEXT, sap TEXT, purchase TEXT);
CREATE TABLE IF NOT EXISTS daily(day TEXT, hull TEXT, stage TEXT, area TEXT, cat TEXT, n INTEGER,
    PRIMARY KEY(day, hull, stage, area, cat));
CREATE TABLE IF NOT EXISTS item_state(key TEXT, stage TEXT, cat TEXT, first_seen TEXT, last_seen TEXT,
    resolved TEXT, report_count INTEGER DEFAULT 0, PRIMARY KEY(key, stage));
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, ts TEXT, day TEXT, path TEXT, items INTEGER);
CREATE TABLE IF NOT EXISTS seen_files(path TEXT PRIMARY KEY, mtime REAL, size INTEGER, first_seen TEXT, source TEXT);
"""


class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), timeout=15)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- 기록 ----
    def record(self, cmp: Comparison, files: dict[str, str], now: dt.datetime | None = None) -> None:
        now = now or dt.datetime.now()
        day = now.date().isoformat()
        with self.db:
            self.db.execute("INSERT INTO runs(ts, day, design, sap, purchase) VALUES(?,?,?,?,?)",
                            (now.isoformat(timespec="seconds"), day, files.get("design", ""),
                             files.get("sap", ""), files.get("purchase", "")))
            self.db.execute("DELETE FROM daily WHERE day=?", (day,))
            agg: dict[tuple, int] = {}
            for r in cmp.rows:
                for s in STAGES:
                    v = r.cat.get(s)
                    if v and v != "ok":
                        k = (day, r.hull, s, r.area, v)
                        agg[k] = agg.get(k, 0) + 1
            self.db.executemany("INSERT INTO daily VALUES(?,?,?,?,?,?)", [k + (n,) for k, n in agg.items()])
            # 항목 상태
            open_now = {(r.key, s): r.cat[s] for r in cmp.rows for s in STAGES if r.cat.get(s) not in (None, "ok")}
            existing = {(k, s): resolved for k, s, resolved in
                        self.db.execute("SELECT key, stage, resolved FROM item_state")}
            for (k, s), cat in open_now.items():
                if (k, s) in existing:
                    self.db.execute("UPDATE item_state SET cat=?, last_seen=?, resolved=NULL WHERE key=? AND stage=?",
                                    (cat, day, k, s))
                else:
                    self.db.execute("INSERT INTO item_state(key, stage, cat, first_seen, last_seen) VALUES(?,?,?,?,?)",
                                    (k, s, cat, day, day))
            for (k, s), resolved in existing.items():
                if (k, s) not in open_now and not resolved:
                    self.db.execute("UPDATE item_state SET resolved=? WHERE key=? AND stage=?", (day, k, s))

    def record_report(self, path: str, keys: list[str], now: dt.datetime | None = None) -> None:
        now = now or dt.datetime.now()
        with self.db:
            self.db.execute("INSERT INTO reports(ts, day, path, items) VALUES(?,?,?,?)",
                            (now.isoformat(timespec="seconds"), now.date().isoformat(), path, len(keys)))
            self.db.executemany("UPDATE item_state SET report_count = report_count + 1 WHERE key=? AND resolved IS NULL",
                                [(k,) for k in keys])

    def mark_file_seen(self, source: str, path: str, mtime: float, size: int) -> bool:
        """처음 보는 파일이면 True."""
        cur = self.db.execute("SELECT mtime, size FROM seen_files WHERE path=?", (path,)).fetchone()
        if cur and abs(cur[0] - mtime) < 1e-3 and cur[1] == size:
            return False
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO seen_files VALUES(?,?,?,?,?)",
                            (path, mtime, size, dt.datetime.now().isoformat(timespec="seconds"), source))
        return True

    # ---- 조회 ----
    def daily_series(self, stage: str, hull: str | None = None, area: str | None = None,
                     days: int = 90) -> list[tuple[str, int]]:
        q = "SELECT day, SUM(n) FROM daily WHERE stage=?"
        args: list = [stage]
        if hull:
            q += " AND hull=?"
            args.append(hull)
        if area:
            q += " AND area=?"
            args.append(area)
        q += " GROUP BY day ORDER BY day"
        rows = self.db.execute(q, args).fetchall()
        all_days = [d for (d,) in self.db.execute("SELECT DISTINCT day FROM runs ORDER BY day")]
        got = dict(rows)
        return [(d, got.get(d, 0)) for d in all_days][-days:]

    def previous_total(self, stage: str, hull: str | None, before_day: str) -> int | None:
        d = self.db.execute("SELECT MAX(day) FROM runs WHERE day < ?", (before_day,)).fetchone()[0]
        if not d:
            return None
        q = "SELECT COALESCE(SUM(n),0) FROM daily WHERE day=? AND stage=?"
        args = [d, stage]
        if hull:
            q += " AND hull=?"
            args.append(hull)
        return self.db.execute(q, args).fetchone()[0]

    def report_days(self) -> list[str]:
        return [d for (d,) in self.db.execute("SELECT DISTINCT day FROM reports ORDER BY day")]

    def file_days(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for src, ts in self.db.execute("SELECT source, first_seen FROM seen_files"):
            out.setdefault(src, []).append(ts[:10])
        return out

    def item_info(self) -> dict[tuple[str, str], tuple[str, int]]:
        """(key, stage) → (최초 발견일, 리포트 횟수) — 미해결 항목만."""
        return {(k, s): (f, n) for k, s, f, n in
                self.db.execute("SELECT key, stage, first_seen, report_count FROM item_state WHERE resolved IS NULL")}

    def since_last_report(self) -> dict | None:
        row = self.db.execute("SELECT day FROM reports ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        day = row[0]
        resolved = self.db.execute("SELECT COUNT(*) FROM item_state WHERE report_count>0 AND resolved IS NOT NULL AND resolved>=?",
                                   (day,)).fetchone()[0]
        still = self.db.execute("SELECT COUNT(*) FROM item_state WHERE report_count>0 AND resolved IS NULL").fetchone()[0]
        new = self.db.execute("SELECT COUNT(*) FROM item_state WHERE first_seen>? AND resolved IS NULL", (day,)).fetchone()[0]
        return {"day": day, "resolved": resolved, "open": still, "new": new}
