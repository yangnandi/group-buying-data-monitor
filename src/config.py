"""配置管理模块"""
import os
import yaml
from pathlib import Path
from typing import Any, Dict


def load_config(path: str = None) -> Dict[str, Any]:
    """加载YAML配置文件"""
    if path is None:
        path = Path(__file__).parent.parent / "config.yaml"
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    _validate(config)
    return config


def _validate(config: Dict[str, Any]):
    """校验必要配置"""
    if not config.get("amap", {}).get("api_key"):
        raise ValueError("请配置 amap.api_key（高德地图API Key）")
    if not config.get("feishu", {}).get("webhook_url"):
        raise ValueError("请配置 feishu.webhook_url（飞书机器人Webhook）")
    if not config.get("stores"):
        raise ValueError("请至少配置一个门店 stores")
