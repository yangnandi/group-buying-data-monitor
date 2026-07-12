"""主入口 - 高德地图门店数据监测系统

用法:
    python -m src.main              # 启动定时调度（默认）
    python -m src.main --once       # 执行一次后退出
    python -m src.main --config custom.yaml  # 指定配置文件
"""
import argparse
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scheduler import MonitorScheduler


def main():
    parser = argparse.ArgumentParser(description="高德地图门店数据监测系统")
    parser.add_argument("--once", action="store_true", help="只运行一次，不启动调度")
    parser.add_argument("--config", type=str, default=None, help="配置文件路径")
    args = parser.parse_args()

    monitor = MonitorScheduler(config_path=args.config)

    if args.once:
        print("执行单次数据抓取...")
        reports = monitor.run_once()
        print(f"完成！共处理 {len(reports)} 个门店")
    else:
        print("启动定时监测调度器...")
        print("按 Ctrl+C 停止")
        monitor.start()


if __name__ == "__main__":
    main()
