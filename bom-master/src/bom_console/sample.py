"""예시 데이터: 실제 파일이 연결되기 전에도 화면과 리포트를 확인할 수 있도록.

세 파일의 머리글을 일부러 서로 다르게 만들어 열 이름 자동 인식을 함께 확인한다.
"""
from __future__ import annotations

import datetime as dt
import random

from openpyxl import Workbook

from .config import app_dir

BLOCKS = {
    "ER": ["E11", "E12", "E13", "E14", "E15", "M21", "M22"],
    "Accommodation": ["A31", "A32", "A33", "A34", "DH1", "DH2"],
    "On-deck": ["D41", "D42", "D43", "D44", "D45", "F51", "F52"],
}
KINDS = [
    ("JB", "Junction box", "IP56 12-way", "EA", (1, 8)), ("LF", "LED flood light", "150W Ex e", "EA", (1, 6)),
    ("LT", "LED tube light", "2x18W IP66", "EA", (2, 20)), ("CG", "Cable gland", "M25 Brass Ni", "EA", (10, 80)),
    ("CB", "Cable", "3C 2.5sq LSZH", "M", (40, 400)), ("CT", "Cable tray", "300W HDG", "M", (6, 60)),
    ("MC", "MCT frame", "6-module", "SET", (1, 3)), ("LC", "Local control station", "2PB Ex d", "EA", (1, 4)),
    ("SK", "Socket outlet", "230V 16A IP56", "EA", (1, 10)), ("DB", "Distribution board", "24-way 440V", "EA", (1, 2)),
    ("EM", "Emergency light", "1x8W 3h", "EA", (1, 8)), ("CP", "Cable penetration", "D100 A60", "EA", (2, 12)),
]
PROFILE = {"S040": (0.10, 0.06, 0.02, 0.20), "S041": (0.16, 0.07, 0.025, 0.33), "S042": (0.26, 0.05, 0.02, 0.55)}
STATUS = ["PR 접수", "PO 발행", "제작 중", "선적", "입고 완료"]
N_PER_HULL = 1200


def _gen(today: dt.date):
    R = random.Random(42)
    design, sap, pur = [], [], []
    all_blocks = [b for bs in BLOCKS.values() for b in bs]
    for hull, (sm, sq, sc, pm) in PROFILE.items():
        for i in range(1, N_PER_HULL + 1):
            k = R.choice(KINDS)
            blk = R.choice(all_blocks)
            item = f"E-{k[0]}-{blk}-{i:04d}"
            code = str(70010000 + R.randint(0, 89999))
            qty = R.randint(*k[4])
            row = dict(hull=hull, block=blk, item=item, code=code, name=k[1], spec=k[2], qty=qty, unit=k[3],
                       dwg=f"S04X-360-{blk}-01")
            design.append(row)
            r = R.random()
            if r < sm:
                s_row = None
            elif r < sm + sq:
                s_row = dict(row, qty=max(1, qty + R.choice([-1, 1]) * max(1, round(qty * R.uniform(.1, .4)))))
            elif r < sm + sq + sc:
                s_row = dict(row, code=str(int(code) + R.randint(1, 9)))
            else:
                s_row = dict(row)
            if s_row:
                sap.append(s_row)
            r = R.random()
            if (s_row is None and R.random() < .9) or r < pm:
                continue
            p_row = dict(row)
            if r < pm + .06:
                p_row["qty"] = max(1, qty + R.choice([-1, 1]) * max(1, round(qty * R.uniform(.1, .4))))
            elif r < pm + .08:
                p_row["code"] = str(int(code) + R.randint(1, 9))
            p_row["status"] = R.choice(STATUS)
            p_row["eta"] = (today + dt.timedelta(days=R.randint(-60, 90))).isoformat()
            p_row["po"] = f"45{R.randint(10000000, 99999999)}"
            pur.append(p_row)
        # 설계에서 빠졌는데 SAP/구매에 남은 항목
        for j in range(int(N_PER_HULL * .02)):
            k = R.choice(KINDS)
            blk = R.choice(all_blocks)
            row = dict(hull=hull, block=blk, item=f"E-{k[0]}-{blk}-9{j:03d}", code=str(70010000 + R.randint(0, 89999)),
                       name=k[1], spec=k[2], qty=R.randint(*k[4]), unit=k[3], dwg="")
            sap.append(row)
            if R.random() < .6:
                pur.append(dict(row, status="PO 발행", eta=(today + dt.timedelta(days=30)).isoformat(), po="4500000000"))
    return design, sap, pur


def ensure_demo(today: dt.date | None = None) -> dict[str, str]:
    today = today or dt.date.today()
    root = app_dir() / "demo"
    folders = {s: str(root / s) for s in ("design", "sap", "purchase")}
    marker = root / "design" / "전장설계_Master_BOM_rev37.xlsx"
    if marker.exists():
        return folders
    for s in folders:
        (root / s).mkdir(parents=True, exist_ok=True)
    design, sap, pur = _gen(today)

    wb = Workbook()
    wb.remove(wb.active)
    for hull in PROFILE:
        ws = wb.create_sheet(hull)
        ws.append([f"{hull} Electrical Master BOM", None, None, "rev.37"])
        ws.append([])
        ws.append(["Block", "Item No", "Material Code", "Description", "Spec", "Q'ty", "Unit", "Drawing No"])
        for r in design:
            if r["hull"] == hull:
                ws.append([r["block"], r["item"], r["code"], r["name"], r["spec"], r["qty"], r["unit"], r["dwg"]])
    wb.save(marker)

    wb = Workbook()
    ws = wb.active
    ws.title = "SAP BOM"
    ws.append(["Hull No", "Block", "Item", "Material", "Material Description", "Quantity", "Base Unit"])
    for r in sap:
        ws.append([r["hull"], r["block"], r["item"], r["code"], f'{r["name"]} {r["spec"]}', r["qty"], r["unit"]])
    wb.save(root / "sap" / f"SAP_BOM_{today:%Y%m%d}.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "구매현황"
    ws.append(["Vessel", "BLK", "Pos No", "Mat No", "Description", "Req Qty", "UoM", "PO No", "Status", "ETA"])
    for r in pur:
        ws.append([r["hull"], r["block"], r["item"], r["code"], r["name"], r["qty"], r["unit"], r["po"], r["status"], r["eta"]])
    wb.save(root / "purchase" / f"구매BOM_{(today - dt.timedelta(days=5)):%Y%m%d}.xlsx")
    return folders


def seed_history(h, cmp, today: dt.date | None = None) -> None:
    """예시 모드에서 추이 그래프가 비어 보이지 않도록 지난 60일 이력을 만들어 넣는다."""
    from .compare import STAGES
    today = today or dt.date.today()
    if h.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]:
        return
    R = random.Random(7)
    now_counts: dict[tuple, int] = {}
    for r in cmp.rows:
        for s in STAGES:
            v = r.cat.get(s)
            if v and v != "ok":
                k = (r.hull, s, r.area, v)
                now_counts[k] = now_counts.get(k, 0) + 1
    days = [today - dt.timedelta(days=i) for i in range(60, 0, -1)]
    reports = {today - dt.timedelta(days=d) for d in (42, 28, 14)}
    rev_day = today - dt.timedelta(days=21)
    factor, factors = 1.45, []
    for d in days:
        recent = any(0 <= (d - r).days < 11 for r in reports)
        factor *= 1 - (0.016 if recent else 0.003) + (R.random() - .5) * 0.01
        if d == rev_day:
            factor *= 1.09
        factors.append(factor)
    scale = 1 / factors[-1] * 1.02
    with h.db:
        for d, f in zip(days, factors):
            day = d.isoformat()
            h.db.execute("INSERT INTO runs(ts, day, design, sap, purchase) VALUES(?,?,?,?,?)",
                         (day + "T07:00:00", day, "", "", ""))
            h.db.executemany("INSERT INTO daily VALUES(?,?,?,?,?,?)",
                             [(day,) + k + (round(n * f * scale),) for k, n in now_counts.items()])
        for r in sorted(reports):
            h.db.execute("INSERT INTO reports(ts, day, path, items) VALUES(?,?,?,?)",
                         (r.isoformat() + "T09:00:00", r.isoformat(), "(예시)", 0))
        for i, d in enumerate(days):
            if i % 4 == 1:
                h.db.execute("INSERT OR REPLACE INTO seen_files VALUES(?,?,?,?,?)",
                             (f"demo-sap-{i}", 0, 0, d.isoformat(), "sap"))
            if i % 7 == 3:
                h.db.execute("INSERT OR REPLACE INTO seen_files VALUES(?,?,?,?,?)",
                             (f"demo-pur-{i}", 0, 0, d.isoformat(), "purchase"))
        first = [r.isoformat() for r in sorted(reports)]
        for r in cmp.rows:
            for s in STAGES:
                if r.cat.get(s) not in (None, "ok"):
                    n = R.choice([0, 1, 1, 2, 2, 3])
                    fs = first[3 - n] if n else (today - dt.timedelta(days=R.randint(1, 10))).isoformat()
                    h.db.execute("INSERT OR REPLACE INTO item_state(key, stage, cat, first_seen, last_seen, report_count) "
                                 "VALUES(?,?,?,?,?,?)", (r.key, s, r.cat[s], fs, fs, n))
        # 지난 리포트 이후 해결된 항목 (예시)
        last = first[-1]
        for i in range(int(len(cmp.rows) * .12)):
            h.db.execute("INSERT OR IGNORE INTO item_state(key, stage, cat, first_seen, last_seen, resolved, report_count) "
                         "VALUES(?,?,?,?,?,?,?)", (f"DEMO|RESOLVED|{i}", "sap", "qty", first[0], last, today.isoformat(), 1))
