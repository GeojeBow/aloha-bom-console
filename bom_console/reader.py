"""BOM 파일 읽기: 머리글 자동 탐지 + 별칭으로 열 찾기."""
from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

HULL_RE = re.compile(r"S[\s\-_.]*0?4[0-2]", re.I)


@dataclass
class BomItem:
    hull: str
    block: str
    item_no: str
    code: str
    name: str = ""
    spec: str = ""
    qty: float = 0.0
    unit: str = ""
    drawing: str = ""
    area: str = ""
    status: str = ""
    eta: str = ""
    po: str = ""
    sheet: str = ""
    row: int = 0

    def key(self) -> str:
        """같은 항목을 세 파일에서 짝짓는 기준.

        품번(Item no)이 있으면 호선+블록+품번, 없으면 호선+블록+자재코드.
        품번으로 짝지으면 자재코드가 바뀐 경우를 '코드 차이'로 잡을 수 있다.
        """
        ident = self.item_no or self.code
        return f"{self.hull}|{self.block}|{ident}".upper()


@dataclass
class ReadResult:
    path: Path
    items: list[BomItem] = field(default_factory=list)
    columns: dict[str, str] = field(default_factory=dict)   # 논리 필드 → 실제 머리글
    sheets_used: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def norm(s) -> str:
    return re.sub(r"[\s_.\-/()]+", " ", str(s or "")).strip().lower()


def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def _to_float(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else 0.0


def _match_columns(header: list, aliases: dict[str, list[str]]) -> dict[str, int]:
    """머리글 행에서 논리 필드별 열 위치를 찾는다. 정확히 일치를 먼저, 그다음 포함 관계."""
    cells = [norm(h) for h in header]
    found: dict[str, int] = {}
    used: set[int] = set()
    for exact in (True, False):
        for fld, names in aliases.items():
            if fld in found:
                continue
            al = [norm(a) for a in names]
            for i, c in enumerate(cells):
                if not c or i in used:
                    continue
                if (c in al) if exact else any(len(a) >= 3 and a in c for a in al):
                    found[fld] = i
                    used.add(i)
                    break
    return found


def _find_header(rows: list[list], aliases) -> tuple[int, dict[str, int]]:
    best = (-1, {})
    for i, row in enumerate(rows[:30]):
        m = _match_columns(row, aliases)
        if len(m) > len(best[1]):
            best = (i, m)
    return best


def _rows_from_file(path: Path) -> list[tuple[str, list[list]]]:
    if path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(path, newline="", encoding=enc) as f:
                    return [("csv", [r for r in csv.reader(f)])]
            except UnicodeDecodeError:
                continue
        raise ValueError(f"CSV 인코딩을 읽을 수 없습니다: {path.name}")
    wb = load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append((ws.title, [list(r) for r in ws.iter_rows(values_only=True)]))
    wb.close()
    return out


def hull_from_text(text: str) -> str:
    m = HULL_RE.search(text or "")
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(0))
    return f"S{int(digits):03d}"


def read_bom(path: str | Path, aliases: dict[str, list[str]], hulls: list[str] | None = None) -> ReadResult:
    """BOM 파일 하나를 읽는다. 머리글이 맞는 시트를 모두 읽고, 호선은 열 → 시트명 → 파일명 순서로 정한다."""
    path = Path(path)
    res = ReadResult(path=path)
    file_hull = hull_from_text(path.stem)
    for sheet, rows in _rows_from_file(path):
        hi, cols = _find_header(rows, aliases)
        if hi < 0 or not ({"code", "item_no"} & cols.keys()) or "qty" not in cols:
            continue
        res.sheets_used.append(sheet)
        header = rows[hi]
        for f, c in cols.items():
            res.columns.setdefault(f, _cell_str(header[c]))
        sheet_hull = hull_from_text(sheet)
        for r_i, row in enumerate(rows[hi + 1:], start=hi + 2):
            def g(f):
                c = cols.get(f)
                return row[c] if c is not None and c < len(row) else None
            code, item_no = _cell_str(g("code")), _cell_str(g("item_no"))
            if not code and not item_no:
                continue
            hull = hull_from_text(_cell_str(g("hull"))) or sheet_hull or file_hull
            if hulls and hull and hull not in hulls:
                continue
            res.items.append(BomItem(
                hull=hull, block=_cell_str(g("block")).upper(), item_no=item_no, code=code,
                name=_cell_str(g("name")), spec=_cell_str(g("spec")), qty=_to_float(g("qty")),
                unit=_cell_str(g("unit")).upper(), drawing=_cell_str(g("drawing")), area=_cell_str(g("area")),
                status=_cell_str(g("status")), eta=_cell_str(g("eta"))[:10], po=_cell_str(g("po")),
                sheet=sheet, row=r_i,
            ))
    if not res.sheets_used:
        res.warnings.append(f"{path.name}: 자재코드/품번과 수량 열을 찾지 못했습니다. 설정 > 열 이름에서 별칭을 추가해 주세요.")
    missing_hull = sum(1 for it in res.items if not it.hull)
    if missing_hull:
        res.warnings.append(f"{path.name}: {missing_hull}개 항목의 호선을 알 수 없습니다 (호선 열, 시트명, 파일명 모두에서 못 찾음).")
    return res
