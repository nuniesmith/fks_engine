from __future__ import annotations
import sys, pathlib
root = pathlib.Path(__file__).resolve().parent
for p in (root/"shared"/"python"/"src", root/"src"):
    if p.is_dir():
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
