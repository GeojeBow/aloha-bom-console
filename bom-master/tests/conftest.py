import sys
from pathlib import Path

# test the shipped copies in bom-master/src (not the legacy bom_console in the repo root)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
for m in [m for m in sys.modules if m == "bom_console" or m.startswith("bom_console.")]:
    del sys.modules[m]
