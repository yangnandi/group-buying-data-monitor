"""测试入口

    python -m tests.run_tests            单元测试 + 端到端集成测试
    python -m tests.run_tests unit       仅单元测试
    python -m tests.run_tests e2e        仅端到端集成测试
    python -m tests.test_e2e             直接跑端到端

全部使用本地桩服务，不依赖外网与真实 API Key。
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

which = sys.argv[1] if len(sys.argv) > 1 else "all"

codes = []
if which in ("all", "unit"):
    print("\n########## 单元测试 ##########")
    unit = runpy.run_path(str(ROOT / "tests" / "test_group_buying.py"),
                          run_name="__not_main__")
    codes.append(unit["main"]())
if which in ("all", "e2e"):
    print("\n########## 端到端集成测试 ##########")
    e2e = runpy.run_path(str(ROOT / "tests" / "test_e2e.py"),
                         run_name="__not_main__")
    codes.append(e2e["main"]())

sys.exit(0 if all(c == 0 for c in codes) else 1)
