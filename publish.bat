@echo off
rem ============================================================
rem  AlohaBOM 빌드 + 배포 (해리 PC에서 실행)
rem  1) exe를 만들고  2) 배포 폴더에 AlohaBOM.exe 와 version.json 을 올린다.
rem  사용자는 배포 폴더의 AlohaBOM.exe 를 한 번만 복사해 가면,
rem  이후에는 실행할 때마다 이 폴더의 version.json 을 보고 자동 업데이트된다.
rem  새 버전 배포 전: bom_console\__init__.py 의 __version__ 숫자를 올린다.
rem ============================================================
chcp 65001 >nul
cd /d %~dp0
set "RELEASE=%OneDriveCommercial%\Claude_Schedule\00_Claude_Workspace\AlohaBOM"
if "%OneDriveCommercial%"=="" set "RELEASE=C:\Users\yk09269\OneDrive - PHILLY SHIPYARD, INC\Claude_Schedule\00_Claude_Workspace\AlohaBOM"

if not exist .venv (python -m venv .venv || goto :err)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements-dev.txt || goto :err
python -m pytest -q tests || goto :err
python tools\make_version.py "%~1" || goto :err
pyinstaller --noconfirm AlohaBOM.spec || goto :err

if not exist "%RELEASE%" mkdir "%RELEASE%"
copy /Y dist\AlohaBOM.exe "%RELEASE%\AlohaBOM.exe" >nul || goto :err
copy /Y dist\version.json "%RELEASE%\version.json" >nul || goto :err
echo.
echo 배포 완료: %RELEASE%
type "%RELEASE%\version.json"
pause
exit /b 0
:err
echo.
echo 실패했습니다. 위 메시지를 확인해 주세요.
pause
exit /b 1
