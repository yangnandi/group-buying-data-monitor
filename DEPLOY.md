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
