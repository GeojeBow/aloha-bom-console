"""설계 Master를 기준으로 SAP / 구매 BOM을 비교한다."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .config import AREAS, UNASSIGNED
from .reader import BomItem

STAGES = ("sap", "purchase")
STAGE_LABELS = {"sap": "② SAP", "purchase": "③ 구매"}
CATS = ("missing", "qty", "code", "extra")
CAT_LABELS = {
    "sap": {"missing": "SAP 미등록", "qty": "수량 차이", "code": "코드·사양 차이", "extra": "SAP에만 있음"},
    "purchase": {"missing": "미발주", "qty": "수량 차이", "code": "코드·사양 차이", "extra": "구매에만 있음"},
}
RECEIVED_RE = re.compile(r"입고|received|delivered|\bgr\b|완료|closed", re.I)


def aggregate(items: list[BomItem]) -> tuple[dict[str, BomItem], int]:
    """같은 key가 여러 줄이면 수량을 합친다 (블록 BOM이 여러 시트/줄로 나뉜 경우)."""
    out: dict[str, BomItem] = {}
    dups = 0
    for it in items:
        k = it.key()
        if k in out:
            dups += 1
            out[k].qty += it.qty
        else:
            out[k] = BomItem(**it.__dict__)
    return out, dups


def classify_area(block: str, explicit: str, rules: list[list[str]]) -> str:
    if explicit:
        e = explicit.strip().lower()
        for a in AREAS:
            if e.startswith(a.lower()[:3]) or a.lower() in e:
                return a
        if e in ("er", "engine room", "기관실"):
            return "ER"
        if e.startswith("acc") or "거주" in e:
            return "Accommodation"
        if "deck" in e or "갑판" in e:
            return "On-deck"
    for pattern, area in rules:
        try:
            if re.search(pattern, block or "", re.I):
                return area
        except re.error:
            continue
    return UNASSIGNED


def _code_norm(s: str) -> str:
    return re.sub(r"[\s\-]", "", s or "").lstrip("0").upper()


def judge(a: BomItem | None, o: BomItem | None) -> str:
    if a and not o:
        return "missing"
    if o and not a:
        return "extra"
    if a.code and o.code and _code_norm(a.code) != _code_norm(o.code):
        return "code"
    if a.unit and o.unit and a.unit != o.unit:
        return "code"
    if abs(a.qty - o.qty) > 1e-6:
        return "qty"
    return "ok"


def is_late(p: BomItem | None, today: dt.date) -> bool:
    if not p or not p.eta or RECEIVED_RE.search(p.status or ""):
        return False
    try:
        return dt.date.fromisoformat(p.eta[:10]) < today
    except ValueError:
        return False


@dataclass
class Row:
    key: str
    hull: str
    block: str
    area: str
    design: BomItem | None
    sap: BomItem | None
    purchase: BomItem | None
    cat: dict[str, str] = field(default_factory=dict)   # stage → ok/missing/qty/code/extra, 없으면 해당 없음
    late: bool = False

    @property
    def ref(self) -> BomItem:
        return self.design or self.sap or self.purchase

    def has_dev(self, stage: str | None = None) -> bool:
        stages = [stage] if stage else STAGES
        return any(self.cat.get(s) not in (None, "ok") for s in stages)

    def priority(self) -> str:
        if self.cat.get("sap") == "missing" or (self.late and self.design):
            return "높음"
        if any(self.cat.get(s) in ("qty", "code") for s in STAGES):
            return "중간"
        return "낮음"


@dataclass
class Comparison:
    rows: list[Row]
    warnings: list[str] = field(default_factory=list)

    def hulls(self) -> list[str]:
        return sorted({r.hull for r in self.rows if r.hull})

    def stage_stats(self, hull: str | None, stage: str, area: str | None = None) -> dict:
        c = {k: 0 for k in ("ok",) + CATS}
        base = 0
        late = 0
        for r in self.rows:
            if hull and r.hull != hull:
                continue
            if area and r.area != area:
                continue
            if r.design:
                base += 1
            v = r.cat.get(stage)
            if v:
                c[v] += 1
            if stage == "purchase" and r.late and r.design:
                late += 1
        dev = sum(c[k] for k in CATS)
        return {"base": base, "counts": c, "dev": dev, "pct": (c["ok"] / base * 100) if base else 0.0, "late": late}


def compare(design: list[BomItem], sap: list[BomItem], purchase: list[BomItem],
            area_rules: list[list[str]], today: dt.date | None = None) -> Comparison:
    today = today or dt.date.today()
    A, da = aggregate(design)
    B, db = aggregate(sap)
    C, dc = aggregate(purchase)
    warns = []
    for n, d in (("설계 Master", da), ("SAP", db), ("구매", dc)):
        if d:
            warns.append(f"{n}: 같은 항목이 여러 줄로 {d}건 중복되어 수량을 합쳤습니다.")
    rows = []
    for k in list(A.keys()) + [k for k in B if k not in A] + [k for k in C if k not in A and k not in B]:
        a, b, p = A.get(k), B.get(k), C.get(k)
        ref = a or b or p
        explicit = (a.area if a else "") or (b.area if b else "") or (p.area if p else "")
        r = Row(key=k, hull=ref.hull, block=ref.block, area=classify_area(ref.block, explicit, area_rules),
                design=a, sap=b, purchase=p)
        if a or b:
            r.cat["sap"] = judge(a, b)
        if a or p:
            r.cat["purchase"] = judge(a, p)
        r.late = is_late(p, today)
        rows.append(r)
    unassigned = sorted({r.block for r in rows if r.area == UNASSIGNED and r.has_dev()})
    if unassigned:
        shown = ", ".join(unassigned[:12]) + (" …" if len(unassigned) > 12 else "")
        warns.append(f"구역이 정해지지 않은 블록 {len(unassigned)}개: {shown}. 설정 > 구역 규칙에서 지정해 주세요.")
    return Comparison(rows=rows, warnings=warns)


def request_text(r: Row, stage: str) -> str:
    """엔지니어가 SAP팀 / 구매팀에 요청할 내용."""
    v = r.cat.get(stage)
    if v in (None, "ok"):
        return ""
    a, o = r.design, (r.sap if stage == "sap" else r.purchase)
    team = "SAP" if stage == "sap" else "구매"
    q = lambda x: f"{x.qty:g} {x.unit}".strip()
    if v == "missing":
        return (f"SAP 등록 요청: {a.code or a.item_no}, {q(a)}" if stage == "sap"
                else f"구매 진행 여부 확인: {a.code or a.item_no}, {q(a)}")
    if v == "qty":
        return f"{team} 수량 {o.qty:g} → {q(a)} {'수정' if stage == 'sap' else '정정'} 요청"
    if v == "code":
        return f"{team} 자재 {o.code} {o.unit} → {a.code} {a.unit} ({a.spec or a.name}) {'수정' if stage == 'sap' else '정정'} 요청"
    return f"설계 Master에 없는 항목. 설계에서 삭제됐다면 {'SAP 삭제' if stage == 'sap' else '구매 취소'} 요청"


def request_text_en(r: Row, stage: str) -> str:
    """같은 요청의 영문 (미국인 엔지니어용)."""
    v = r.cat.get(stage)
    if v in (None, "ok"):
        return ""
    a, o = r.design, (r.sap if stage == "sap" else r.purchase)
    team = "SAP" if stage == "sap" else "Purchasing"
    q = lambda x: f"{x.qty:g} {x.unit}".strip()
    if v == "missing":
        return (f"Request SAP registration: {a.code or a.item_no}, {q(a)}" if stage == "sap"
                else f"Confirm purchase status: {a.code or a.item_no}, {q(a)}")
    if v == "qty":
        return f"Correct {team} qty {o.qty:g} → {q(a)}"
    if v == "code":
        return f"Correct {team} material {o.code} {o.unit} → {a.code} {a.unit} ({a.spec or a.name})"
    return (f"Not in Design Master. If deleted from design, request "
            f"{'SAP deletion' if stage == 'sap' else 'PO cancellation'}")
