# BOM Master — 전장 호선별 BOM Master 관리 프로그램 (S040 / S041 / S042)

## 실행
`release\BOM_Master.exe` 를 더블클릭. (설치 불필요)
- 처음 실행 시 N: 드라이브 4개 폴더를 자동 스캔합니다. 첫 스캔은 파일을 모두 읽어서 오래 걸리고(약 30분), 이후에는 **바뀐 파일만** 다시 읽어 약 3분이면 끝납니다.
- 마지막 스캔 결과는 저장돼 있어 프로그램을 열면 바로 보입니다. 최신화하려면 **Scan folders**를 누르세요.

## 화면
| 화면 | 용도 |
|---|---|
| Dashboard | 4대 폴더 상태 카드 + 블록 맵. 타일의 **P W D E** 막대 = 16 Prod DWG / 17 WP / 03 DCN / 04 ECN 상태(초록=정상, 노랑=확인, 빨강=수정 필요, 회색=파일 없음). 타일 클릭 → BOM 상세 |
| BOM 상세 | 위: 폴더×리비전 타임라인(같은 색=같은 내용). 아래: **What differs** — 다른 파일 쌍 목록과 줄 단위 Diff(바뀐 칸은 ~~이전값~~ → **새값**) |
| Master BOM | 최신 Prod DWG BOM 전 품목 + 16 Prod DWG / 17 WP / 03 DCN / 04 ECN 상태 열 + SAP / 구매 열 |
| Sync Matrix | BOM별 4대 폴더 리비전·상태 비교 |

**두 파일 비교 (BOM 상세):** 타임라인의 파일에서 `Set as A` → 다른 파일에서 `Set as B` → `Compare A ↔ B`.
결과는 "B가 A 대비 빠진 줄 / 추가된 줄 / 바뀐 줄" 숫자 카드 + 바뀐 열 목록 + 줄 단위 표(카드 클릭 = 해당 종류만 보기).
`Reset comparisons` = A·B 선택과 직접 추가한 비교를 지우고 자동 비교 목록으로 복귀.

**Copy to fix:** Prod DWG ↔ WP 누락·구버전, DCN/ECN 리비전 누락 오류에서 파일을 맞는 폴더로 복사.
① 복사 내용(FROM / TO 폴더, 새 폴더 생성 여부, 구버전 Arch 이동 선택) 확인 → ② "복사 됩니다. 내용 정확히 확인하셨습니까?" 재확인.
같은 이름 파일이 있으면 복사 거부(덮어쓰기 없음). 기록: Settings → Open copy log. S041/S042에는 S040 파일을 복사하지 않음.

**Acknowledge as minor:** 확인 완료한 알람을 "Acknowledged"로 분리(파일은 그대로). 오류/경고 집계·색에서 빠지고
Action List의 `Acknowledged (minor)` 보기와 리포트의 별도 시트에만 표시. 관련 파일 내용이 바뀌면 자동으로 다시 알람.
저장 위치: Settings → Acknowledged alarms file (공유 경로를 지정하면 팀 전체가 같은 목록 사용).

**삭제 줄:** BOM의 `Mode` 열이 `D`인 줄은 Deleted — Master BOM·리포트에서 빨간 취소선으로 표시 (A = Added, C = Changed).
삭제 줄은 Material No. 중복 검사에서 제외. Master BOM 상단에서 삭제 줄 보기/숨기기/만 보기 선택.

모든 표: 머리글의 **▾** = 엑셀식 열 필터(값 검색·체크), 머리글 우클릭 = 필터 전체 해제.
| Action List | 시정조치 목록. 더블클릭 → 파일 비교(Diff) 또는 BOM 이력 |
| File Inventory | 찾은 모든 BOM 파일과 분류(ACTIVE / ARCHIVE / COMMENT / STAGING) |
| SAP & Purchasing | SAP·구매 master 파일 지정 (비교 로직은 파일 양식 확인 후 추가) |
| Settings | 폴더 경로, 분류 규칙 |

상단 **S040 / S041 / S042** 버튼으로 호선 필터, **Export report**로 시정조치용 Excel 리포트를 만듭니다.

## 판정 규칙
1. **16 Prod DWG = 기준(100%).** 블록 BOM 폴더(`3-BOMS\...`)에 있는 파일이 ACTIVE, `Arch` / `old` 등 폴더는 ARCHIVE, `Comment` / `Reviewed` / `COM-PSG` / `Deleted` 사본은 COMMENT(검토본, 비교 제외), `0 Prod DWG Recovery Plan` / `1 Under Review` / `3. BOMs to proceed`는 STAGING(작업 중).
2. BOM의 최신 리비전 = Prod DWG의 ACTIVE·ARCHIVE 파일 중 가장 높은 Rev.
3. **같은 파일명 + 같은 Rev**는 어느 폴더에 있든 내용이 같아야 함 → 다르면 ERROR.
   날짜/이니셜 접미사만 다른 사본(`R1` vs `R1_20260429`)이 내용이 다르면 WARN.
4. **Work Package**는 Prod DWG 최신 Rev와 같은 Rev, 같은 내용이어야 함.
5. **DCN / ECN** BOM은 없어도 되지만, 있으면 같은 Rev가 Prod DWG와 WP에 있고 내용이 같아야 함.
6. BOM 줄의 Ship No. / Block / Phase / Discipline은 파일명과 일치해야 함.
   단, Ship No.가 달라도 **폴더 이름의 호선 번호**(예: `xS041`, `S041-ECN`, `1041_…`, `DCN-041-…`)가 파일명 호선과 같으면 정상으로 봄.
7. Material No.는 BOM 안에서, 그리고 같은 호선의 BOM 사이에서 중복되면 안 됨 (단, 구매품 `P`는 제외).
8. 내용 비교는 표준 SAP 20개 열 기준 (REMARK 등 메모 열은 비교 제외, Diff 화면에서는 표시).
9. S041 / S042는 16 Prod DWG에 자체 BOM이 없어 **S040 Prod DWG를 기준**으로 비교 (Ship No.는 비교 제외).

## 업데이트 / 배포
```
powershell -ExecutionPolicy Bypass -File build.ps1 -Notes "변경 내용"
```
`src\bom_master\__init__.py`의 VERSION을 올린 뒤 실행하면 `release\`에 새 exe와 `version.json`이 생깁니다.
다른 위치에 복사해 쓰는 exe는 실행 시 `release\version.json`을 확인해 자동으로 새 버전으로 교체 후 재시작합니다.
(업데이트 폴더는 Settings에서 변경 가능)

## 폴더 구조
```
Claude_BOM\
  release\        배포 exe + version.json (자동 업데이트 기준)
  src\            소스 (Python 3.13, PySide6, openpyxl)
    main.py       진입점
    cli_check.py  GUI 없이 스캔·분석 결과 출력 (테스트용)
    bom_master\   scanner / analyzer / report / updater / gui
  build.ps1       빌드 + 배포
```
설정: `%APPDATA%\BOMMaster\config.json` · 캐시: `%LOCALAPPDATA%\BOMMaster\`
