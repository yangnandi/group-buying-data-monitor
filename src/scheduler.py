"""定时任务调度模块"""
import sys
import time
from dataclasses import asdict
from datetime import datetime, time as dt_time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from .config import load_config
from .crawlers.amap import AmapCrawler, StoreReport
from .notifier.feishu import FeishuNotifier


class MonitorScheduler:
    """数据监测调度器"""

    def __init__(self, config_path: str = None):
        self.config = load_config(config_path)
        self.crawler = AmapCrawler(
            api_key=self.config["amap"]["api_key"],
            request_delay=self.config["amap"].get("request_delay", 5),
        )
        self.notifier = FeishuNotifier(
            webhook_url=self.config["feishu"]["webhook_url"],
            secret=self.config["feishu"].get("secret", ""),
            at_users=self.config["feishu"].get("at_users", []),
        )
        self.scheduler = BackgroundScheduler()
        self._setup_logging()

    def _setup_logging(self):
        """配置日志"""
        log_cfg = self.config.get("logging", {})
        log_file = log_cfg.get("file", "./logs/monitor.log")
        log_level = log_cfg.get("level", "INFO")

        # 确保日志目录存在
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

        # 修复：data_dir 取自 storage 配置，而前面只创建了日志目录；
        # 首次部署时 data/ 不存在，抓取数据会因目录缺失而失败。
        data_dir = self.config.get("storage", {}).get("data_dir", "./data")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

        logger.remove()
        logger.add(
            log_file,
            rotation="10 MB",
            retention="30 days",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )
        logger.add(sys.stderr, level=log_level)

        # 确保数据目录存在
        data_dir = self.config.get("storage", {}).get("data_dir", "./data")
        Path(data_dir).mkdir(parents=True, exist_ok=True)

    def run_once(self) -> list:
        """执行一次完整抓取"""
        stores = self.config.get("stores", [])
        if not stores:
            logger.warning("没有配置门店")
            return []

        reports = []
        for store_cfg in stores:
            name = store_cfg.get("name", "")
            city = store_cfg.get("city", "")
            poi_id = store_cfg.get("poi_id", "")

            if not name:
                continue

            logger.info(f"正在获取数据: {name} ({city})")
            try:
                report = self.crawler.fetch_store_report(name, city, poi_id)
                reports.append(report)
                logger.info(
                    f"完成: {name} | 评分:{report.store.rating} | "
                    f"评论:{report.store.review_count} | 新增:{report.new_review_count}"
                )
            except Exception as e:
                logger.error(f"获取失败 [{name}]: {e}")
                self.notifier.send_alert(
                    "数据抓取失败",
                    f"门店 **{name}** 数据抓取异常：\n```\n{e}\n```",
                )

            # 平台请求间隔
            time.sleep(self.crawler.request_delay)

        # 发送报告
        if reports:
            report_dicts = [asdict(r) for r in reports]
            self.notifier.send_report(report_dicts)

        return reports

    def start(self):
        """启动定时调度"""
        amap_cfg = self.config.get("amap", {})

        # 解析时间范围
        time_range = amap_cfg.get("time_range", {})
        start_h, start_m = map(int, time_range.get("start", "10:00").split(":"))
        end_h, end_m = map(int, time_range.get("end", "20:00").split(":"))

        # 间隔分钟
        interval = amap_cfg.get("interval_minutes", 120)

        # 添加定时任务
        self.scheduler.add_job(
            self.run_once,
            trigger=CronTrigger(
                hour=f"{start_h}-{end_h}",
                minute=f"*/{interval}",
            ),
            id="amap_monitor",
            name="高德地图监测",
        )

        self.scheduler.start()
        logger.info(
            f"调度器已启动: {start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}, "
            f"间隔 {interval} 分钟"
        )

        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("收到停止信号，正在关闭...")
            self.scheduler.shutdown()
