from __future__ import annotations
import sys, pathlib
root = pathlib.Path(__file__).resolve().parent
shared_src = root / "shared" / "python" / "src"
if shared_src.is_dir() and str(shared_src) not in sys.path:
    sys.path.insert(0, str(shared_src))
