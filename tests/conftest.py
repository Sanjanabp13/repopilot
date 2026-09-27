from __future__ import annotations

import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "sample_project"
if str(FIXTURE_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURE_DIR))
