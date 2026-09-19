"""测试入口：python -m tests.run_tests"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ns = runpy.run_path(str(ROOT / "tests" / "test_group_buying.py"), run_name="__not_main__")
sys.exit(ns["main"]())
