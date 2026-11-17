# PyInstaller 설정: pyinstaller AlohaBOM.spec  →  dist/AlohaBOM.exe (파일 하나, 콘솔 창 없음)
a = Analysis(
    ["run_app.py"],
    datas=[("bom_console/assets", "bom_console/assets")],
    hiddenimports=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtCharts"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="AlohaBOM",
    icon="bom_console/assets/bom_app.ico",
    console=False,
    upx=False,
    version="version_info.txt",
)
