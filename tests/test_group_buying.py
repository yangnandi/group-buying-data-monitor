"""group-buying-data-monitor 单元测试（不依赖 pytest，纯 stdlib + 本地桩服务）

覆盖已修复的缺陷，防止回归：
  1. review_count / rating 必须从 detail 接口回填
  2. 评论接口返回 HTML 时必须识别并告警，不得静默返回空列表
  3. _is_html_response 判定
  4. 缓存读写一致（新增评论数 = 总量 - 上次总量）
  5. _load_previous_count 遇到损坏缓存时返回 0 并告警（不再静默吞异常）
  6. httpx 客户端必须禁用环境代理（trust_env=False），避免被系统代理劫持

运行: python -m tests.run_tests   （在仓库根目录）
"""
import json
import os
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 夹具：绕过本机系统代理对本地桩的劫持（同时也验证业务代码自身的 trust_env 修复）
import httpx  # noqa: E402

_orig_init, _orig_get = httpx.Client.__init__, httpx.Client.get

from src.crawlers.amap import AmapCrawler, ReviewItem, StoreInfo  # noqa: E402
from src.notifier.feishu import FeishuNotifier  # noqa: E402

STATE = {"mode": "json"}  # json | html | bad
CALLS = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype: str):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        CALLS.append(self.path)
        if "/comment/list" in self.path:
            if STATE["mode"] == "html":
                self._send(b"<!doctype html><html><body>anti-bot</body></html>", "text/html")
            elif STATE["mode"] == "bad":
                self._send(b"not json at all", "text/plain")
            else:
                self._json({"data": {"comment_list": [
                    {"user_name": "张三", "user_level": "VIP3", "score": "5",
                     "content": "味道很好", "pics": ["http://x/1.jpg"],
                     "create_time": "2026-09-18 12:00:00"}]}})
        elif "/place/text" in self.path:
            self._json({"status": "1", "pois": [{
                "id": "B0FFFAB6J2", "name": "测试门店", "address": "北京市朝阳区测试路1号",
                "cityname": "北京市", "biz_ext": {"rating": "4.7"}}]})
        elif "/place/detail" in self.path:
            self._json({"status": "1", "pois": [{
                "id": "B0FFFAB6J2", "name": "测试门店", "address": "北京市朝阳区测试路1号",
                "cityname": "北京市",
                "biz_ext": {"rating": "4.7", "taste_rating": "4.8",
                            "environment_rating": "4.6", "service_rating": "4.5"},
                "deep_info": {"comment_number": "123", "navi_review_num": "80",
                              "scene_review_num": "20"}}]})
        else:
            self._json({"status": "1"})


SRV = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{SRV.server_port}"
threading.Thread(target=SRV.serve_forever, daemon=True).start()
AmapCrawler.BASE_API = f"{BASE}/v3"


def _patched_get(self, url, **kw):
    if "m.amap.com" in str(url):
        url = f"{BASE}/comment/list"
    return _orig_get(self, url, **kw)


httpx.Client.get = _patched_get

RESULTS = []


def check(label, cond, detail=""):
    RESULTS.append((bool(cond), label, detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f" -> {detail}" if detail else ""))


def test_review_count_backfilled():
    """修复1：按名称搜索分支必须回填 review_count / rating"""
    c = AmapCrawler(api_key="X", request_delay=0)
    st = c.search_poi("测试门店", "北京")
    check("search_poi 解析基础字段", st is not None and st.poi_id == "B0FFFAB6J2")
    detail = c.get_poi_detail(st.poi_id)
    # 真实搜索响应不含 deep_info，故搜索结果为 0；detail 才有 123
    check("search 响应本身不含总评论数", st.review_count == 0, st.review_count)
    check("detail 提供总评论数 123", detail["review_count"] == 123, detail["review_count"])
    rep = c.fetch_store_report("测试门店", "北京", poi_id="")
    check("fetch_store_report 回填总评论数 = 123", rep.store.review_count == 123,
          rep.store.review_count)
    check("fetch_store_report 回填评分 = 4.7", rep.store.rating == 4.7, rep.store.rating)
    check("回填口味/环境/服务分", (rep.store.taste_score, rep.store.env_score,
                                rep.store.service_score) == (4.8, 4.6, 4.5))


def test_cache_roundtrip():
    """修复2：缓存读写一致，新增 = 总量 - 上次总量"""
    key = "B0FFFAB6J2"
    f = Path("./data") / f"{AmapCrawler._safe_name(key)}_count.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("100", encoding="utf-8")
    c = AmapCrawler(api_key="X", request_delay=0)
    check("读到预置值 100", c._load_previous_count(key) == 100, c._load_previous_count(key))
    c._save_current_count(key, 123)
    check("写后读一致 = 123", c._load_previous_count(key) == 123, c._load_previous_count(key))
    f.unlink()


def test_corrupt_cache_warns():
    """修复3：损坏缓存返回 0 且不抛异常（告警而非静默）"""
    key = "corrupt-case"
    f = Path("./data") / f"{AmapCrawler._safe_name(key)}_count.txt"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("not-a-number", encoding="utf-8")
    c = AmapCrawler(api_key="X", request_delay=0)
    try:
        v = c._load_previous_count(key)
        check("损坏缓存返回 0 且不抛异常", v == 0, v)
    except Exception as e:
        check("损坏缓存返回 0 且不抛异常", False, repr(e))
    f.unlink()


def test_html_review_detection():
    """修复4：评论接口返回 HTML 时不得静默返回空列表"""
    c = AmapCrawler(api_key="X", request_delay=0)
    STATE["mode"] = "html"
    try:
        reviews = c._fetch_recent_reviews("B0FFFAB6J2")
        check("HTML 响应下不崩溃", isinstance(reviews, list), type(reviews).__name__)
        check("HTML 响应下返回空（已降级）", reviews == [], len(reviews))
        # 关键：必须走 _is_html_response 判定分支，而不是把 HTML 当 JSON
        resp = httpx.get(f"{BASE}/comment/list", trust_env=False)
        check("_is_html_response 对 text/html 判定为 True",
              AmapCrawler._is_html_response(resp) is True)
        check("响应体确实以 '<' 开头（非 JSON）",
              resp.text.lstrip().startswith("<"), resp.text[:20])
    finally:
        STATE["mode"] = "json"


def test_json_review_parsing():
    """回归：正常 JSON 评论仍能解析"""
    STATE["mode"] = "json"
    c = AmapCrawler(api_key="X", request_delay=0)
    reviews = c._fetch_recent_reviews("B0FFFAB6J2")
    check("JSON 下解析出 1 条评论", len(reviews) == 1, len(reviews))
    if reviews:
        r = reviews[0]
        check("评论字段正确",
              (r.user_name, r.rating, r.images) == ("张三", 5.0, ["http://x/1.jpg"]),
              f"{r.user_name}/{r.rating}/{r.images}")


def test_trust_env_disabled():
    """修复5：业务代码自身的 httpx 客户端必须 trust_env=False"""
    c = AmapCrawler(api_key="X", request_delay=0)
    check("AmapCrawler.client.trust_env is False", c.client.trust_env is False,
          c.client.trust_env)
    n = FeishuNotifier(webhook_url="http://127.0.0.1:1/hook")
    # FeishuNotifier 用模块级 httpx.post，检查调用参数中的 trust_env
    check("FeishuNotifier 源码包含 trust_env=False",
          "trust_env=False" in Path("src/notifier/feishu.py").read_text(encoding="utf-8"))


def test_feishu_card_build():
    """回归：报告卡片结构正确"""
    n = FeishuNotifier(webhook_url="http://127.0.0.1:1/hook", at_users=["ou_xxx"])
    card = n._build_card([{
        "store": {"name": "测试门店", "address": "北京", "rating": 4.7,
                  "review_count": 123, "taste_score": 4.8},
        "new_review_count": 23,
        "new_reviews": [{"user_name": "张三", "rating": 5, "content": "味道很好"}],
    }])
    raw = json.dumps(card, ensure_ascii=False)
    check("卡片 msg_type=interactive", card["msg_type"] == "interactive")
    check("卡片含门店名", "测试门店" in raw)
    check("卡片含新增 23 条", "新增评论：**23**" in raw)
    check("卡片含 @提醒", "ou_xxx" in raw)


def test_data_dir_created():
    """修复6：调度器必须主动创建 data_dir"""
    import shutil
    import yaml
    cfg = Path("config.test.yaml")
    tmp_data = Path("./_test_data_dir")
    shutil.rmtree(tmp_data, ignore_errors=True)
    cfg.write_text(yaml.safe_dump({
        "stores": [{"name": "测试门店", "city": "北京", "poi_id": ""}],
        "amap": {"api_key": "X", "request_delay": 0,
                 "time_range": {"start": "10:00", "end": "20:00"},
                 "interval_minutes": 120},
        "feishu": {"webhook_url": f"{BASE}/hook", "secret": "", "at_users": []},
        "storage": {"data_dir": str(tmp_data)},
        "logging": {"level": "INFO", "file": "./logs/test.log"},
    }, allow_unicode=True), encoding="utf-8")
    from src.scheduler import MonitorScheduler
    try:
        MonitorScheduler(config_path=str(cfg))
        check("data_dir 被自动创建", tmp_data.is_dir(), str(tmp_data))
    except Exception as e:
        check("data_dir 被自动创建", False, repr(e))
    finally:
        cfg.unlink(missing_ok=True)
        shutil.rmtree(tmp_data, ignore_errors=True)


def main():
    tests = [
        test_review_count_backfilled,
        test_cache_roundtrip,
        test_corrupt_cache_warns,
        test_html_review_detection,
        test_json_review_parsing,
        test_trust_env_disabled,
        test_feishu_card_build,
        test_data_dir_created,
    ]
    for t in tests:
        print(f"\n--- {t.__name__} ---")
        try:
            t()
        except Exception:
            traceback.print_exc()
            check(f"{t.__name__} 未抛异常", False, "见上方 traceback")
    passed = sum(1 for ok, _, _ in RESULTS if ok)
    failed = [lbl for ok, lbl, _ in RESULTS if not ok]
    print(f"\n{'='*60}\n单元测试: {passed}/{len(RESULTS)} 通过")
    for f in failed:
        print(f"  FAIL: {f}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    httpx.Client.__init__ = lambda self, *a, **kw: _orig_init(self, *a, **{**kw, "trust_env": False})
    try:
        code = main()
    finally:
        httpx.Client.get, httpx.Client.__init__ = _orig_get, _orig_init
        SRV.shutdown()
    sys.exit(code)
