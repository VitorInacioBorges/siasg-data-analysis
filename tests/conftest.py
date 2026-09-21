"""Puts src/ on the import path, the same way `python src/main.py` does."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
