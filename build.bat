@echo off
rem Windows PC에서 exe를 직접 만들 때 (Python 3.11 이상 필요). 결과: dist\AlohaBOM.exe, dist\version.json
cd /d %~dp0
python -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements-dev.txt || goto :err
python tools\make_version.py || goto :err
pyinstaller --noconfirm AlohaBOM.spec || goto :err
echo.
echo 완료: dist\AlohaBOM.exe
pause
exit /b 0
:err
echo 빌드 실패
pause
exit /b 1
