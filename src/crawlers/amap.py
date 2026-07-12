"""高德地图数据抓取模块

通过高德API获取门店信息 + Playwright抓取评论数据
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import httpx
from loguru import logger


@dataclass
class StoreInfo:
    """门店基础信息"""
    name: str
    address: str = ""
    poi_id: str = ""
    city: str = ""
    rating: float = 0.0          # 综合评分
    review_count: int = 0         # 总评论数
    navi_review_count: int = 0    # 导航评价数
    scene_review_count: int = 0   # 现场评价数
    return_rate: str = ""         # 回头率
    category_rank: str = ""       # 分类排名
    taste_score: float = 0.0      # 口味分
    env_score: float = 0.0        # 环境分
    service_score: float = 0.0    # 服务分
    local_review_count: int = 0   # 本地人评价数
    updated_at: str = ""


@dataclass
class ReviewItem:
    """单条评论"""
    user_name: str = ""
    user_level: str = ""
    rating: float = 0.0
    content: str = ""
    images: List[str] = field(default_factory=list)
    publish_time: str = ""
    taste_score: float = 0.0
    env_score: float = 0.0
    service_score: float = 0.0


@dataclass
class StoreReport:
    """门店监测报告"""
    store: StoreInfo
    new_reviews: List[ReviewItem] = field(default_factory=list)
    new_review_count: int = 0
    fetch_time: str = ""


class AmapCrawler:
    """高德地图数据抓取器"""

    BASE_API = "https://restapi.amap.com/v3"
    DETAIL_URL = "https://ditu.amap.com/detail/get/detail"

    def __init__(self, api_key: str, request_delay: float = 5.0):
        self.api_key = api_key
        self.request_delay = request_delay
        self.client = httpx.Client(timeout=30)

    def search_poi(self, name: str, city: str) -> Optional[StoreInfo]:
        """通过名称搜索POI"""
        params = {
            "key": self.api_key,
            "keywords": name,
            "city": city,
            "offset": 1,
            "output": "JSON",
        }
        resp = self.client.get(f"{self.BASE_API}/place/text", params=params)
        data = resp.json()

        if data.get("status") != "1" or not data.get("pois"):
            logger.warning(f"未找到门店: {name} ({city})")
            return None

        poi = data["pois"][0]
        biz = poi.get("biz_ext", {})
        deep = poi.get("deep_info", {})

        return StoreInfo(
            name=poi.get("name", name),
            address=poi.get("address", ""),
            poi_id=poi.get("id", ""),
            city=poi.get("cityname", city),
            rating=float(biz.get("rating", 0) or 0),
            review_count=int(deep.get("comment_number", 0) or 0),
        )

    def get_poi_detail(self, poi_id: str) -> dict:
        """获取POI详细信息（含扩展评分）"""
        params = {
            "key": self.api_key,
            "id": poi_id,
            "output": "JSON",
            "extensions": "all",
        }
        resp = self.client.get(f"{self.BASE_API}/place/detail", params=params)
        data = resp.json()

        if data.get("status") != "1" or not data.get("pois"):
            logger.warning(f"获取POI详情失败: {poi_id}")
            return {}

        poi = data["pois"][0]
        biz = poi.get("biz_ext", {})
        deep = poi.get("deep_info", {})

        return {
            "rating": float(biz.get("rating", 0) or 0),
            "taste_score": float(biz.get("taste_rating", 0) or 0),
            "env_score": float(biz.get("environment_rating", 0) or 0),
            "service_score": float(biz.get("service_rating", 0) or 0),
            "review_count": int(deep.get("comment_number", 0) or 0),
            "navi_review_count": int(deep.get("navi_review_num", 0) or 0),
            "scene_review_count": int(deep.get("scene_review_num", 0) or 0),
        }

    def fetch_store_report(self, name: str, city: str, poi_id: str = "") -> StoreReport:
        """获取门店完整监测报告"""
        store = None

        # 1. 搜索或获取POI基本信息
        if poi_id:
            detail = self.get_poi_detail(poi_id)
            store = StoreInfo(
                name=name, city=city, poi_id=poi_id,
                rating=detail.get("rating", 0),
                review_count=detail.get("review_count", 0),
                navi_review_count=detail.get("navi_review_count", 0),
                scene_review_count=detail.get("scene_review_count", 0),
                taste_score=detail.get("taste_score", 0),
                env_score=detail.get("env_score", 0),
                service_score=detail.get("service_score", 0),
            )
        else:
            store = self.search_poi(name, city)
            if store and store.poi_id:
                detail = self.get_poi_detail(store.poi_id)
                store.taste_score = detail.get("taste_score", 0)
                store.env_score = detail.get("env_score", 0)
                store.service_score = detail.get("service_score", 0)
                store.navi_review_count = detail.get("navi_review_count", 0)
                store.scene_review_count = detail.get("scene_review_count", 0)

        if not store:
            return StoreReport(store=StoreInfo(name=name, city=city))

        time.sleep(self.request_delay)

        # 2. 尝试获取最近评论（通过网页接口）
        new_reviews = self._fetch_recent_reviews(store.poi_id or "")

        # 3. 计算新增评论数
        prev_count = self._load_previous_count(store.poi_id or name)
        new_count = max(0, store.review_count - prev_count)

        self._save_current_count(store.poi_id or name, store.review_count)

        store.updated_at = datetime.now().isoformat()
        return StoreReport(
            store=store,
            new_reviews=new_reviews,
            new_review_count=new_count,
            fetch_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _fetch_recent_reviews(self, poi_id: str) -> List[ReviewItem]:
        """获取最近评论

        通过高德地图移动端JSON接口获取评论列表
        接口: https://m.amap.com/detail/api/comment/list
        """
        if not poi_id:
            return []

        reviews = []
        try:
            # 高德移动端评论接口
            url = "https://m.amap.com/detail/api/comment/list"
            params = {
                "poiid": poi_id,
                "page": 1,
                "pagesize": 20,
            }
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
                ),
                "Referer": "https://m.amap.com/",
            }
            resp = self.client.get(url, params=params, headers=headers)

            if resp.status_code == 200:
                data = resp.json()
                comment_list = (
                    data.get("data", {})
                    .get("comment_list", [])
                )

                for item in comment_list:
                    review = ReviewItem(
                        user_name=item.get("user_name", "匿名"),
                        user_level=item.get("user_level", ""),
                        rating=float(item.get("score", 0) or 0),
                        content=item.get("content", ""),
                        images=item.get("pics", []),
                        publish_time=item.get("create_time", ""),
                    )
                    reviews.append(review)

            logger.info(f"获取到 {len(reviews)} 条评论 (POI: {poi_id})")
        except Exception as e:
            logger.error(f"获取评论失败 (POI: {poi_id}): {e}")

        return reviews

    def _load_previous_count(self, store_key: str) -> int:
        """加载上次记录的总评论数"""
        try:
            count_file = Path("./data") / f"{self._safe_name(store_key)}_count.txt"
            if count_file.exists():
                return int(count_file.read_text().strip())
        except Exception:
            pass
        return 0

    def _save_current_count(self, store_key: str, count: int):
        """保存当前总评论数"""
        count_file = Path("./data") / f"{self._safe_name(store_key)}_count.txt"
        count_file.parent.mkdir(parents=True, exist_ok=True)
        count_file.write_text(str(count))

    @staticmethod
    def _safe_name(name: str) -> str:
        """生成安全的文件名"""
        return hashlib.md5(name.encode()).hexdigest()[:12]
