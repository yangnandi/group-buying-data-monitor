"""飞书机器人推送模块"""
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List

import httpx
from loguru import logger


class FeishuNotifier:
    """飞书自定义机器人通知"""

    def __init__(self, webhook_url: str, secret: str = "", at_users: List[str] = None):
        self.webhook_url = webhook_url
        self.secret = secret
        self.at_users = at_users or []

    def send_report(self, report_data: List[dict]) -> bool:
        """发送门店监测报告到飞书

        Args:
            report_data: 门店报告列表，每个元素为 StoreReport.asdict()
        """
        if not report_data:
            return True

        card = self._build_card(report_data)
        return self._send(card)

    def send_alert(self, title: str, content: str) -> bool:
        """发送告警消息"""
        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"⚠️ {title}"},
                    "template": "red",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
        return self._send(card)

    def _build_card(self, reports: List[dict]) -> dict:
        """构建飞书消息卡片"""
        elements = []
        now = time.strftime("%Y-%m-%d %H:%M:%S")

        # 标题
        elements.append({
            "tag": "markdown",
            "content": f"📊 **门店数据监测报告**\n更新时间：{now}",
        })
        elements.append({"tag": "hr"})

        for r in reports:
            store = r.get("store", {})
            new_count = r.get("new_review_count", 0)
            new_reviews = r.get("new_reviews", [])

            # 门店基本信息卡片
            elements.append(self._store_info_block(store, new_count, new_reviews))

            # 新增评论明细
            if new_reviews:
                elements.append({
                    "tag": "markdown",
                    "content": f"🆕 **新增 {len(new_reviews)} 条评论：**",
                })
                for review in new_reviews[:5]:  # 最多展示5条
                    stars = "⭐" * int(review.get("rating", 0))
                    elements.append({
                        "tag": "markdown",
                        "content": (
                            f"**{review.get('user_name', '匿名')}** {stars}\n"
                            f"{review.get('content', '')[:200]}"
                        ),
                    })
                if len(new_reviews) > 5:
                    elements.append({
                        "tag": "markdown",
                        "content": f"...等共 {len(new_reviews)} 条新评论",
                    })

            elements.append({"tag": "hr"})

        # @提醒
        if self.at_users:
            at_list = " ".join(f"<at user_id=\"{u}\"></at>" for u in self.at_users)
            elements.append({
                "tag": "markdown",
                "content": at_list,
            })

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "📊 门店数据监测"},
                    "template": "blue",
                },
                "elements": elements,
            },
        }

    def _store_info_block(self, store: dict, new_review_count: int,
                          new_reviews: list) -> dict:
        """构建门店信息块"""
        md_parts = [
            f"🏪 **{store.get('name', '未知门店')}**",
            f"📍 {store.get('address', '')}",
            f"⭐ 评分：{store.get('rating', 0)} | 📝 总评论：{store.get('review_count', 0)}",
        ]

        if store.get("taste_score"):
            md_parts.append(
                f"🍽 口味{store['taste_score']} | 🌿 环境{store.get('env_score', 0)} | 🛎 服务{store.get('service_score', 0)}"
            )

        if store.get("return_rate"):
            md_parts.append(f"🔄 回头率：{store['return_rate']}")

        if store.get("category_rank"):
            md_parts.append(f"🏆 排名：{store['category_rank']}")

        if new_review_count > 0:
            md_parts.append(f"🆕 新增评论：**{new_review_count}** 条")

        return {
            "tag": "markdown",
            "content": "\n".join(md_parts),
        }

    def _send(self, card: dict) -> bool:
        """发送消息到飞书"""
        try:
            payload = json.dumps(card, ensure_ascii=False)
            headers = {"Content-Type": "application/json"}

            # 签名校验
            if self.secret:
                timestamp = str(int(time.time()))
                sign = self._sign(timestamp)
                payload_with_sign = json.loads(payload)
                payload_with_sign["timestamp"] = timestamp
                payload_with_sign["sign"] = sign
                payload = json.dumps(payload_with_sign, ensure_ascii=False)

            resp = httpx.post(
                self.webhook_url,
                content=payload.encode("utf-8"),
                headers=headers,
                timeout=15,
            )
            result = resp.json()

            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("飞书推送成功")
                return True
            else:
                logger.error(f"飞书推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"飞书推送异常: {e}")
            return False

    def _sign(self, timestamp: str) -> str:
        """飞书签名计算"""
        sign_str = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            digestmod=hashlib.sha256,
        )
        return hmac_code.digest().hex()
