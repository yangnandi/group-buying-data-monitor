# 部署文档 - 高德地图门店数据监测系统

## 环境要求

- Python 3.10+
- 高德地图 Web 服务 API Key
- 飞书自定义机器人 Webhook

## 1. 获取 API Key

### 高德地图 API Key
1. 访问 [高德开放平台](https://lbs.amap.com/)
2. 注册并登录
3. 进入「应用管理 → 我的应用」→「创建新应用」
4. 添加 Key，「服务平台」选择「Web服务」
5. 复制生成的 Key

### 飞书机器人 Webhook
1. 打开飞书，进入目标群聊
2. 群设置 → 群机器人 → 添加机器人 → 自定义机器人
3. 配置机器人名称和头像
4. 复制 Webhook 地址
5. （可选）设置「签名校验」，复制密钥

## 2. 安装部署

```bash
# 克隆项目
git clone <仓库地址>
cd group-buying-data-monitor

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp config.yaml config.local.yaml
```

## 3. 配置

编辑 `config.local.yaml`：

```yaml
stores:
  - name: "海底捞火锅"
    city: "北京"
    # poi_id 可选，留空自动搜索

amap:
  api_key: "你的高德API Key"      # 必填
  interval_minutes: 120            # 抓取间隔（分钟）
  time_range:
    start: "10:00"                 # 开始时间
    end: "20:00"                   # 结束时间

feishu:
  webhook_url: "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"  # 必填
  secret: ""                       # 飞书签名密钥（可选）
  at_users: []                     # @提醒的用户ID
```

## 4. 运行

```bash
# 测试运行一次
python -m src.main --once --config config.local.yaml

# 启动定时调度
python -m src.main --config config.local.yaml
```

## 5. 系统服务（可选）

### Windows 任务计划程序
1. 打开「任务计划程序」
2. 创建基本任务 → 触发器「每天」→ 操作「启动程序」
3. 程序：`python`，参数：`-m src.main --config config.local.yaml`

### Linux systemd
```ini
# /etc/systemd/system/amap-monitor.service
[Unit]
Description=Amap Store Monitor
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/group-buying-data-monitor
ExecStart=/usr/bin/python3 -m src.main --config config.local.yaml
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now amap-monitor
```

## 6. 数据文件

- `data/` — 评论计数缓存
- `logs/monitor.log` — 运行日志

## 7. 故障排查

| 问题 | 解决方案 |
|------|---------|
| 门店搜索不到 | 检查门店名称是否与高德地图一致 |
| API 调用超限 | 高德免费版日调用量 5000 次，增大 `request_delay` |
| 飞书推送失败 | 检查 Webhook URL 是否正确，签名密钥是否匹配 |

## 8. 评论明细说明（重要）

高德没有公开的评论 API。本项目评论数据的现状与限制：

- `restapi.amap.com/v3/place/*`（官方 Web 服务 API）**只提供门店基础信息、
  评分、总评论数**，不提供评论内容；
- 移动端 `m.amap.com/detail/api/comment/list` 会对非浏览器请求返回
  `text/html` 反爬页面（2026-09 实测），代码会识别该情况并记录 WARNING，
  此时评论明细为空（总评论数、评分、新增数量不受影响，仍然准确）。

需要拿到评论明细时，启用浏览器渲染（可选依赖）：

```bash
pip install playwright
playwright install chromium
# Windows PowerShell
$env:AMAP_USE_BROWSER="1"
# Linux/macOS
export AMAP_USE_BROWSER=1
```

未安装 Playwright 或渲染失败时只记录错误日志，不影响主流程。

## 9. 测试

仓库自带测试套件（不依赖外网，使用本地桩服务模拟高德与飞书接口）：

```bash
python -m tests.run_tests        # 单元测试 + 端到端集成测试
python -m tests.run_tests unit   # 仅单元测试（22 项）
python -m tests.run_tests e2e    # 仅端到端集成测试（22 项）
```

覆盖：

- 单元测试：详情接口回填总评论数/评分、缓存读写一致性、损坏缓存的降级与告警、
  反爬 HTML 的识别、飞书卡片内容、`data_dir` 自动创建、httpx 代理隔离；
- 端到端：搜索返回 poi_id 与"搜索无 id"两种场景下，连续两轮抓取的
  「总评论数 / 新增评论数 / 缓存命中 / 飞书推送内容」全链路。

端到端测试默认会强制本地 httpx 绕过系统代理（因为 127.0.0.1 的桩需要直连）；
设 `SMOKE_NO_TRUSTENV_FIX=1` 可关闭该夹具，用于单独验证代码自身的
`trust_env=False` 修复是否生效。

