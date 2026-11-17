"""빌드 전에 실행: exe 속성용 version_info.txt 와 배포용 version.json 을 만든다."""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
ver = re.search(r'__version__ = "([^"]+)"', (root / "bom_console" / "__init__.py").read_text(encoding="utf-8")).group(1)
nums = (ver.split(".") + ["0", "0", "0"])[:4]
t = ", ".join(nums)
(root / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({t}), prodvers=({t})),
  kids=[StringFileInfo([StringTable('041204B0', [
    StringStruct('CompanyName', 'Aloha-L Electrical'),
    StringStruct('FileDescription', 'Aloha-L BOM 콘솔'),
    StringStruct('FileVersion', '{ver}'),
    StringStruct('ProductName', 'Aloha-L BOM 콘솔'),
    StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1042, 1200])])]
)
""", encoding="utf-8")
notes = sys.argv[1] if len(sys.argv) > 1 else ""
dist = root / "dist"
dist.mkdir(exist_ok=True)
(dist / "version.json").write_text(json.dumps({"version": ver, "file": "AlohaBOM.exe", "notes": notes},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
print(ver)
