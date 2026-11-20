from pathlib import Path
import os
import sys
if os.environ.get("GT_ADDON_USE_INSTALLED") != "1":
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
