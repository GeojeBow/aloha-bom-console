"""엔지니어용 Deviation 리포트 (엑셀).

받는 사람은 항상 구역 담당 엔지니어 (ER / Accommodation / On-deck, 세 호선 모두 담당).
엔지니어가 SAP팀·구매팀에 follow-up 하도록 항목마다 두 팀에 요청할 내용을 따로 적는다.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .compare import CAT_LABELS, STAGES, Comparison, Row, request_text, request_text_en
from .config import AREA_LABELS, AREAS, UNASSIGNED

NAVY = "0D3B4F"
FILL_HEAD = PatternFill("solid", fgColor=NAVY)
FILL_GROUP = PatternFill("solid", fgColor="E3ECF1")
FILL_BAD = PatternFill("solid", fgColor="F8DEDB")
FILL_BASE = PatternFill("solid", fgColor="DCEDF2")
FILL_REPLY = PatternFill("solid", fgColor="FFF8E1")
PRIO_FILL = {"높음": PatternFill("solid", fgColor="F4C7C1"), "중간": PatternFill("solid", fgColor="FBE3B8"),
             "낮음": PatternFill("solid", fgColor="EEF1F4")}
THIN = Side(style="thin", color="C9D3DB")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
F_HEAD = Font(name="맑은 고딕", bold=True, color="FFFFFF", size=10)
F_BODY = Font(name="맑은 고딕", size=10)
F_BOLD = Font(name="맑은 고딕", size=10, bold=True)
F_RED = Font(name="맑은 고딕", size=10, bold=True, color="B3261E")
F_TITLE = Font(name="맑은 고딕", size=16, bold=True, color=NAVY)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="top")
PRIO_ORDER = {"높음": 0, "중간": 1, "낮음": 2}
CAT_EN = {
    "sap": {"missing": "Not in SAP", "qty": "Qty mismatch", "code": "Code/spec mismatch", "extra": "Only in SAP"},
    "purchase": {"missing": "Not ordered", "qty": "Qty mismatch", "code": "Code/spec mismatch", "extra": "Only in Purchasing"},
}

COLUMNS = [  # (머리글 한글/영문, 폭)
    ("No", 5), ("우선순위\nPriority", 9), ("호선\nHull", 7), ("블록\nBlock", 7), ("품번\nItem No", 18),
    ("품명 / 사양\nDescription / Spec", 28), ("최초 발견\nFirst Found", 11), ("리포트 횟수\nTimes Reported", 10),
    ("① 설계 기준 자재코드\nDesign Master Material", 14), ("① 설계 기준 수량\nDesign Master Qty", 11),
    ("② SAP 자재코드\nSAP Material", 13), ("② SAP 수량\nSAP Qty", 9),
    ("③ 구매 자재코드\nPurchasing Material", 13), ("③ 구매 수량\nPurchasing Qty", 10),
    ("③ 구매 상태 / ETA\nPO Status / ETA", 16),
    ("SAP팀에 요청할 것\nAction to SAP Team", 40), ("구매팀에 요청할 것\nAction to Purchasing Team", 40),
    ("조치 상태\nStatus", 12), ("조치 내용 (회신)\nAction Taken (Reply)", 30), ("완료일\nDone Date", 11),
]
PRIO_EN = {"높음": "높음 High", "중간": "중간 Med", "낮음": "낮음 Low"}
NONE = "없음 None"


def _fmt_qty(x) -> str:
    return "" if x is None else f"{x.qty:g}"


def _diff(a, o, attr) -> bool:
    if a is None or o is None:
        return True
    return str(getattr(a, attr)).lstrip("0").upper() != str(getattr(o, attr)).lstrip("0").upper()


def _rows_for(cmp: Comparison, area: str) -> list[Row]:
    rows = [r for r in cmp.rows if r.area == area and r.has_dev()]
    return sorted(rows, key=lambda r: (r.hull, r.block, PRIO_ORDER[r.priority()], r.ref.item_no or r.ref.code))


def _write_area_sheet(ws, area: str, rows: list[Row], info: dict, meta: dict) -> None:
    ws.sheet_view.showGridLines = False
    ws["A1"] = f"{AREA_LABELS.get(area, area)} 담당 엔지니어 follow-up 목록  /  Engineer Follow-up List"
    ws["A1"].font = F_TITLE
    ws["A2"] = (f"기준 Baseline: 설계 Master {meta['design']}  ·  비교 Compared: SAP {meta['sap']}  ·  구매 Purchasing {meta['purchase']}  ·  "
                f"발행 Issued {meta['issued']}  ·  {len(rows):,}건 items")
    ws["A2"].font = Font(name="맑은 고딕", size=9, color="5D6B78")
    ws["A3"] = ("설계 Master를 정답으로 보고 SAP·구매에서 다른 값을 빨간색으로 표시했습니다. 각 팀에 요청 후 노란 칸에 조치 결과를 적어 회신해 주세요.  /  "
                "Design Master is the reference; values in SAP or Purchasing that differ are in red. "
                "Follow up with each team, then fill in the yellow columns and send this file back.")
    ws["A3"].font = Font(name="맑은 고딕", size=9, color="5D6B78")
    hr = 5
    for i, (name, width) in enumerate(COLUMNS, start=1):
        c = ws.cell(row=hr, column=i, value=name)
        c.font, c.fill, c.border = F_HEAD, FILL_HEAD, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[hr].height = 46
    dv = DataValidation(type="list", formula1='"미조치 Open,요청함 Requested,진행 중 In progress,완료 Done,해당 없음 N/A"',
                        allow_blank=True)
    ws.add_data_validation(dv)

    r_i, n, group = hr + 1, 0, None
    for r in rows:
        g = (r.hull, r.block)
        if g != group:
            group = g
            cnt = sum(1 for x in rows if (x.hull, x.block) == g)
            c = ws.cell(row=r_i, column=1, value=f"{r.hull}  ·  Block {r.block}  ·  {cnt}건 items")
            for col in range(1, len(COLUMNS) + 1):
                ws.cell(row=r_i, column=col).fill = FILL_GROUP
                ws.cell(row=r_i, column=col).border = BORDER
            c.font = F_BOLD
            r_i += 1
        n += 1
        a, b, p = r.design, r.sap, r.purchase
        first, count = None, 0
        for s in STAGES:
            if r.cat.get(s) not in (None, "ok"):
                f, k = info.get((r.key, s), (None, 0))
                first = min(filter(None, [first, f]), default=None)
                count = max(count, k)
        ref = r.ref
        prio = r.priority()
        def req(stage):
            en, ko = request_text_en(r, stage), request_text(r, stage)
            return f"{en}\n{ko}" if en else ""
        nth = count + 1
        vals = [
            n, PRIO_EN[prio], r.hull, r.block, ref.item_no, f"{ref.name}\n{ref.spec}".strip(),
            first or "", f"{nth}회째 ({nth}{'nd' if nth == 2 else 'rd' if nth == 3 else 'th'})" if count else "신규 New",
            a.code if a else NONE, _fmt_qty(a) or NONE,
            b.code if b else NONE, _fmt_qty(b) or NONE,
            p.code if p else NONE, _fmt_qty(p) or NONE,
            f"{p.status}\n{p.eta}".strip() if p else "",
            req("sap"), req("purchase"), "미조치 Open", "", "",
        ]
        for col, v in enumerate(vals, start=1):
            c = ws.cell(row=r_i, column=col, value=v)
            c.font, c.border, c.alignment = F_BODY, BORDER, WRAP
        ws.cell(row=r_i, column=1).alignment = CENTER
        ws.cell(row=r_i, column=2).fill = PRIO_FILL[prio]
        ws.cell(row=r_i, column=2).alignment = CENTER
        if count >= 2:
            ws.cell(row=r_i, column=8).font = F_RED
        for col in (9, 10):
            ws.cell(row=r_i, column=col).fill = FILL_BASE if a else FILL_BAD
        for (cc, cq), o in (((11, 12), b), ((13, 14), p)):
            if a is None or o is None:
                ws.cell(row=r_i, column=cc).fill = FILL_BAD
                ws.cell(row=r_i, column=cq).fill = FILL_BAD
            else:
                if _diff(a, o, "code") or (a.unit and o.unit and a.unit != o.unit):
                    ws.cell(row=r_i, column=cc).fill = FILL_BAD
                    ws.cell(row=r_i, column=cc).font = F_RED
                if abs(a.qty - o.qty) > 1e-6:
                    ws.cell(row=r_i, column=cq).fill = FILL_BAD
                    ws.cell(row=r_i, column=cq).font = F_RED
        if r.late:
            ws.cell(row=r_i, column=15).font = F_RED
        for col in (18, 19, 20):
            ws.cell(row=r_i, column=col).fill = FILL_REPLY
        dv.add(ws.cell(row=r_i, column=18))
        r_i += 1
    ws.freeze_panes = ws.cell(row=hr + 1, column=6)
    ws.auto_filter.ref = f"A{hr}:{get_column_letter(len(COLUMNS))}{max(r_i - 1, hr)}"
    ws.print_title_rows = f"{hr}:{hr}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _write_summary(ws, cmp: Comparison, areas: list[str], info: dict, meta: dict, since: dict | None) -> None:
    ws.sheet_view.showGridLines = False
    ws["A1"] = "전장 BOM Deviation 리포트  /  Electrical BOM Deviation Report"
    ws["A1"].font = F_TITLE
    lines = [
        ("발행 Issued", meta["issued"]),
        ("기준 Baseline", f"① 설계 Master (Design Master)  {meta['design']}"),
        ("비교 대상 Compared", f"② SAP  {meta['sap']}   /   ③ 구매 (Purchasing)  {meta['purchase']}"),
        ("파일 확인 Files", "리포트 생성 직전에 세 폴더를 다시 확인한 최신 파일 기준 / Latest files, re-checked right before this report"),
    ]
    if since:
        lines.append(("지난 리포트 이후 Since last report",
                      f"{since['day']} 이후 since  ·  해결 Resolved {since['resolved']:,}  ·  미해결 Open {since['open']:,}  ·  신규 New {since['new']:,}"))
    for i, (k, v) in enumerate(lines, start=3):
        ws.cell(row=i, column=1, value=k).font = F_BOLD
        ws.cell(row=i, column=2, value=v).font = F_BODY
    r0 = 4 + len(lines)
    head = ["담당 구역\nArea", "follow-up 항목\nItems", "SAP팀 요청\nTo SAP Team", "구매팀 요청\nTo Purchasing",
            "우선순위 높음\nHigh Priority", "2회 이상 반복\nRepeated (2+)", "ETA 지난 미입고\nOverdue ETA"]
    for i, h in enumerate(head, start=1):
        c = ws.cell(row=r0, column=i, value=h)
        c.font, c.fill, c.border = F_HEAD, FILL_HEAD, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r0].height = 46
    for j, area in enumerate(areas, start=1):
        rows = [r for r in cmp.rows if r.area == area and r.has_dev()]
        rep = sum(1 for r in rows if max((info.get((r.key, s), (None, 0))[1] for s in STAGES), default=0) >= 1)
        vals = [AREA_LABELS.get(area, area), len(rows), sum(1 for r in rows if r.has_dev("sap")),
                sum(1 for r in rows if r.has_dev("purchase")), sum(1 for r in rows if r.priority() == "높음"),
                rep, sum(1 for r in rows if r.late and r.design)]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r0 + j, column=i, value=v)
            c.font, c.border = F_BODY, BORDER
            if i > 1:
                c.number_format = "#,##0"
    r1 = r0 + len(areas) + 3
    ws.cell(row=r1 - 1, column=1, value="호선 × 종류별 건수 (설계 Master 기준)  /  Count by Hull and Type (vs. Design Master)").font = F_BOLD
    head2 = ["호선\nHull"] + [f"SAP · {CAT_LABELS['sap'][c]}\n{CAT_EN['sap'][c]}" for c in ("missing", "qty", "code", "extra")] + \
            [f"구매 · {CAT_LABELS['purchase'][c]}\n{CAT_EN['purchase'][c]}" for c in ("missing", "qty", "code", "extra")]
    for i, h in enumerate(head2, start=1):
        c = ws.cell(row=r1, column=i, value=h)
        c.font, c.fill, c.border = F_HEAD, FILL_HEAD, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r1].height = 46
    for j, hull in enumerate(cmp.hulls(), start=1):
        s1, s2 = cmp.stage_stats(hull, "sap"), cmp.stage_stats(hull, "purchase")
        vals = [hull] + [s1["counts"][c] for c in ("missing", "qty", "code", "extra")] + \
               [s2["counts"][c] for c in ("missing", "qty", "code", "extra")]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r1 + j, column=i, value=v)
            c.font, c.border = F_BODY, BORDER
    for i, w in enumerate([30, 18, 18, 18, 18, 18, 18, 18, 18], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def write_report(cmp: Comparison, out_dir: Path, files: dict[str, str], info: dict | None = None,
                 since: dict | None = None, split: bool = False, now: dt.datetime | None = None) -> list[Path]:
    """리포트를 만들고 만든 파일 경로 목록을 돌려준다. split=True면 구역별 파일로 나눈다."""
    now = now or dt.datetime.now()
    info = info or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"issued": now.strftime("%Y-%m-%d %H:%M"), **{k: Path(v).name for k, v in files.items()}}
    areas = list(AREAS) + ([UNASSIGNED] if any(r.area == UNASSIGNED and r.has_dev() for r in cmp.rows) else [])
    stamp = now.strftime("%Y%m%d_%H%M")
    paths = []
    if split:
        for area in areas:
            wb = Workbook()
            ws = wb.active
            ws.title = area[:31]
            _write_area_sheet(ws, area, _rows_for(cmp, area), info, meta)
            p = out_dir / f"BOM_Deviation_{area.replace(' ', '')}_{stamp}.xlsx"
            wb.save(p)
            paths.append(p)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "요약"
        _write_summary(ws, cmp, areas, info, meta, since)
        for area in areas:
            _write_area_sheet(wb.create_sheet(area[:31]), area, _rows_for(cmp, area), info, meta)
        p = out_dir / f"BOM_Deviation_Report_{stamp}.xlsx"
        wb.save(p)
        paths.append(p)
    return paths


def report_keys(cmp: Comparison) -> list[str]:
    return [r.key for r in cmp.rows if r.has_dev()]
