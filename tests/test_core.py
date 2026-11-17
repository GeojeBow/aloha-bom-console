import datetime as dt

from openpyxl import Workbook, load_workbook

from bom_console.compare import compare, request_text
from bom_console.config import DEFAULT_ALIASES, DEFAULT_AREA_RULES
from bom_console.history import History
from bom_console.reader import BomItem, read_bom
from bom_console.report import write_report
from bom_console.scanner import newest_file
from bom_console.updater import parse_version


def item(hull="S040", block="E11", no="P1", code="700", qty=1, unit="EA", **kw):
    return BomItem(hull=hull, block=block, item_no=no, code=code, qty=qty, unit=unit, **kw)


def test_reader_finds_header_below_title_and_hull_from_sheet(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "S041"
    ws.append(["Electrical BOM", None, "rev.3"])
    ws.append([])
    ws.append(["BLK", "Pos No", "Mat No", "Description", "Req\nQty", "UoM"])
    ws.append(["e11", "P-1", 70001234, "Junction box", "4", "ea"])
    ws.append([None, None, None, None, None, None])
    p = tmp_path / "bom.xlsx"
    wb.save(p)
    res = read_bom(p, DEFAULT_ALIASES)
    assert res.sheets_used == ["S041"]
    assert len(res.items) == 1
    it = res.items[0]
    assert (it.hull, it.block, it.item_no, it.code, it.qty, it.unit) == ("S041", "E11", "P-1", "70001234", 4.0, "EA")


def test_reader_csv_cp949_and_hull_column(tmp_path):
    p = tmp_path / "sap.csv"
    p.write_bytes("호선,블록,품번,자재코드,수량\nS-042,A31,X1,123,2\n".encode("cp949"))
    res = read_bom(p, DEFAULT_ALIASES)
    assert res.items[0].hull == "S042" and res.items[0].qty == 2


def test_reader_warns_when_columns_missing(tmp_path):
    wb = Workbook()
    wb.active.append(["foo", "bar"])
    p = tmp_path / "x.xlsx"
    wb.save(p)
    assert read_bom(p, DEFAULT_ALIASES).warnings


def test_compare_categories_against_design():
    design = [item(no="P1"), item(no="P2", qty=5), item(no="P3", code="700"), item(no="P4"), item(no="P5", block="D41")]
    sap = [item(no="P1"), item(no="P2", qty=3), item(no="P3", code="701"), item(no="P9")]
    pur = [item(no="P1", status="PO", eta="2026-01-01"), item(no="P2", qty=5)]
    c = compare(design, sap, pur, DEFAULT_AREA_RULES, today=dt.date(2026, 11, 17))
    cat = {r.ref.item_no: r.cat for r in c.rows}
    assert cat["P1"] == {"sap": "ok", "purchase": "ok"}
    assert cat["P2"] == {"sap": "qty", "purchase": "ok"}
    assert cat["P3"]["sap"] == "code"
    assert cat["P4"] == {"sap": "missing", "purchase": "missing"}
    assert cat["P9"] == {"sap": "extra"}
    rows = {r.ref.item_no: r for r in c.rows}
    assert rows["P1"].late and rows["P5"].area == "On-deck" and rows["P1"].area == "ER"
    assert rows["P4"].priority() == "높음"
    assert "2" not in request_text(rows["P2"], "sap") or "→ 5" in request_text(rows["P2"], "sap")
    st = c.stage_stats("S040", "sap")
    assert st["base"] == 5 and st["dev"] == 5 and st["counts"]["ok"] == 1


def test_duplicate_rows_are_summed():
    c = compare([item(qty=2), item(qty=3)], [item(qty=5)], [item(qty=5)], DEFAULT_AREA_RULES)
    assert c.rows[0].cat == {"sap": "ok", "purchase": "ok"} and c.warnings


def test_unassigned_block_warns():
    c = compare([item(block="ZZ9")], [], [], DEFAULT_AREA_RULES)
    assert c.rows[0].area == "미지정" and any("구역" in w for w in c.warnings)


def test_history_tracks_resolution_and_report_count(tmp_path):
    h = History(tmp_path / "h.sqlite")
    d1 = compare([item(no="P1"), item(no="P2")], [item(no="P1")], [item(no="P1"), item(no="P2")], DEFAULT_AREA_RULES)
    h.record(d1, {}, now=dt.datetime(2026, 11, 1, 8))
    h.record_report("r.xlsx", ["S040|E11|P2"], now=dt.datetime(2026, 11, 1, 9))
    assert h.item_info()[("S040|E11|P2", "sap")] == ("2026-11-01", 1)
    d2 = compare([item(no="P1"), item(no="P2")], [item(no="P1"), item(no="P2")], [item(no="P1"), item(no="P2")], DEFAULT_AREA_RULES)
    h.record(d2, {}, now=dt.datetime(2026, 11, 2, 8))
    assert ("S040|E11|P2", "sap") not in h.item_info()
    assert h.since_last_report()["resolved"] == 1
    assert [n for _, n in h.daily_series("sap")] == [1, 0]
    assert h.previous_total("sap", None, "2026-11-02") == 1


def test_report_has_area_sheets_and_requests(tmp_path):
    c = compare([item(no="P1", qty=5), item(no="P2", block="A31")], [item(no="P1", qty=3)], [], DEFAULT_AREA_RULES)
    (p,) = write_report(c, tmp_path, {"design": "d.xlsx", "sap": "s.xlsx", "purchase": "p.xlsx"})
    wb = load_workbook(p)
    assert wb.sheetnames == ["요약", "ER", "Accommodation", "On-deck"]
    texts = [str(v) for row in wb["ER"].iter_rows(values_only=True) for v in row if v]
    assert any("SAP 수량 3 → 5 EA 수정 요청" in t and "Correct SAP qty 3 → 5 EA" in t for t in texts)
    assert wb["ER"].cell(row=5, column=2).value == "우선순위\nPriority"
    split = write_report(c, tmp_path / "s", {"design": "d", "sap": "s", "purchase": "p"}, split=True)
    assert len(split) == 3


def test_newest_file_ignores_excel_lock_files(tmp_path):
    import os, time
    a = tmp_path / "a.xlsx"
    a.write_text("x")
    b = tmp_path / "~$b.xlsx"
    b.write_text("x")
    os.utime(b, (time.time() + 100, time.time() + 100))
    assert newest_file(tmp_path, "*.xlsx", "sap").path == a


def test_version_compare():
    assert parse_version("0.10.0") > parse_version("0.9.9") and parse_version("v1.2") == (1, 2, 0)
