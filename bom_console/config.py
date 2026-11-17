"""설정 파일 (사용자별 JSON).

샘플 파일이 아직 없으므로 열 이름은 모두 '별칭 목록'으로 관리한다.
파일의 머리글 중 별칭과 일치하는 열을 자동으로 찾고, 맞지 않으면 설정 화면에서 별칭을 추가한다.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import APP_NAME

SOURCES = ("design", "sap", "purchase")
SOURCE_LABELS = {"design": "① 설계 Master", "sap": "② SAP", "purchase": "③ 구매"}

AREAS = ("ER", "Accommodation", "On-deck")
AREA_LABELS = {"ER": "ER area", "Accommodation": "Accommodation area", "On-deck": "On-deck area"}
UNASSIGNED = "미지정"

# 논리 필드 → 기본 별칭 (대소문자, 공백, 줄바꿈 무시하고 비교)
DEFAULT_ALIASES: dict[str, list[str]] = {
    "hull": ["hull", "hull no", "vessel", "ship", "호선", "선번"],
    "block": ["block", "block no", "blk", "블록", "블럭"],
    "item_no": ["item no", "item", "pos", "pos no", "position", "tag", "tag no", "bom item", "품번", "항목번호"],
    "code": ["material", "material no", "material code", "mat no", "mat code", "sap code", "part no",
             "part number", "자재코드", "자재번호", "자재 코드"],
    "name": ["description", "desc", "material description", "item description", "name", "품명", "자재명"],
    "spec": ["spec", "specification", "type", "model", "사양", "규격"],
    "qty": ["qty", "quantity", "q'ty", "req qty", "required qty", "bom qty", "수량", "소요량"],
    "unit": ["unit", "uom", "un", "base unit", "단위"],
    "drawing": ["drawing", "drawing no", "dwg", "dwg no", "도면", "도면번호"],
    "area": ["area", "zone", "구역"],
    "status": ["status", "po status", "purchase status", "진행상태", "구매상태", "상태"],
    "eta": ["eta", "eta date", "delivery date", "expected delivery", "입고예정일", "납기"],
    "po": ["po", "po no", "purchase order", "발주번호"],
}

FIELD_LABELS = {
    "hull": "호선", "block": "블록", "item_no": "품번(Item)", "code": "자재코드", "name": "품명",
    "spec": "사양", "qty": "수량", "unit": "단위", "drawing": "도면번호", "area": "구역",
    "status": "구매 상태", "eta": "ETA", "po": "PO 번호",
}

# 블록 → 구역 규칙 (정규식, 위에서부터 처음 맞는 것). 실제 블록 체계에 맞게 설정 화면에서 수정한다.
DEFAULT_AREA_RULES: list[list[str]] = [
    [r"^(ER|E|M|MR|EN)", "ER"],
    [r"^(AC|A|DH|H|L|LQ)", "Accommodation"],
    [r"^(OD|D|F|C|S|P|FW|AFT|B|R)", "On-deck"],
]


# 배포 폴더: 해리 OneDrive의 Claude 작업 폴더. 다른 사람 PC에서도 찾도록 OneDrive 환경변수 기준 경로도 함께 본다.
RELEASE_SUBPATH = Path("Claude_Schedule") / "00_Claude_Workspace" / "AlohaBOM"
RELEASE_FALLBACK = Path(r"C:\Users\yk09269\OneDrive - PHILLY SHIPYARD, INC") / RELEASE_SUBPATH


def default_update_dir() -> str:
    cands = [Path(os.environ[k]) / RELEASE_SUBPATH for k in ("OneDriveCommercial", "OneDrive") if os.environ.get(k)]
    cands.append(RELEASE_FALLBACK)
    for c in cands:
        if (c / "version.json").is_file():
            return str(c)
    return ""


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def exe_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


@dataclass
class AppConfig:
    folders: dict[str, str] = field(default_factory=lambda: {s: "" for s in SOURCES})
    patterns: str = "*.xlsx;*.xlsm;*.csv"
    scan_minutes: int = 5
    stale_days: int = 7
    history_db: str = ""          # 비우면 사용자 폴더. 팀이 같은 이력을 보려면 N: 공용 폴더로 지정
    report_dir: str = ""
    update_dir: str = ""          # 비우면 OneDrive\Claude_Schedule\00_Claude_Workspace\AlohaBOM 을 찾아 쓴다
    aliases: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_ALIASES.items()})
    area_rules: list[list[str]] = field(default_factory=lambda: [list(r) for r in DEFAULT_AREA_RULES])
    hulls: list[str] = field(default_factory=lambda: ["S040", "S041", "S042"])
    area_rules_confirmed: bool = False  # 기본 규칙은 추정값. 사용자가 설정에서 확인하면 True
    demo: bool = True             # 세 폴더가 비어 있으면 예시 데이터로 화면을 보여준다

    @property
    def history_path(self) -> Path:
        return Path(self.history_db) if self.history_db else app_dir() / "history.sqlite"

    @property
    def report_path(self) -> Path:
        p = Path(self.report_dir) if self.report_dir else Path.home() / "Documents" / "AlohaBOM Reports"
        return p

    @property
    def update_path(self) -> str:
        return self.update_dir or default_update_dir()

    def configured(self) -> bool:
        return all(self.folders.get(s) for s in SOURCES)


def config_path() -> Path:
    return app_dir() / "config.json"


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    cfg = AppConfig()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        # 새 버전에서 추가된 필드의 기본 별칭을 잃지 않도록 병합
        for k, v in DEFAULT_ALIASES.items():
            cfg.aliases.setdefault(k, list(v))
        for s in SOURCES:
            cfg.folders.setdefault(s, "")
    return cfg


def save_config(cfg: AppConfig, path: Path | None = None) -> None:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
