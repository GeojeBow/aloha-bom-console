"""SAP → 구매 link and 'where it broke' (설계 Master stays the reference)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bom_console.compare import compare  # noqa: E402
from bom_console.reader import BomItem  # noqa: E402


def it(code, qty, no):
    return BomItem(hull="S040", block="E410P", item_no=no, code=code, qty=qty, unit="EA")


def test_broken():
    d = [it("A", 1, "1"), it("B", 2, "2"), it("C", 3, "3"), it("D", 4, "4"), it("E", 5, "5"), it("F", 6, "6")]
    s = [it("A", 1, "1"), it("B", 9, "2"), it("C", 3, "3"), it("D", 8, "4"), it("E", 7, "5")]
    p = [it("A", 1, "1"), it("B", 9, "2"), it("C", 1, "3"), it("D", 4, "4"), it("E", 1, "5")]
    cmp = compare(d, s, p, [])
    got = {r.design.code: r.broken() for r in cmp.rows}
    assert got == {"A": "ok", "B": "sap", "C": "purchase", "D": "sap_only", "E": "both", "F": "sap"}, got
    ls = cmp.link_stats("S040")
    assert ls["link"] == 3 and ls["broken"] == {"sap": 2, "purchase": 1, "sap_only": 1, "both": 1}, ls
