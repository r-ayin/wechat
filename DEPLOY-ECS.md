# 部署到阿里云 ECS — 每日热点日报 HTML

> 目标：ECS 上每天自动产出 `output/hotspot-report-YYYY-MM-DD.html`（多条热点选题日报）。
> 链路全确定性，无 LLM 依赖：Brave Search 取数 → hot-scanner consume 评分 → daily_report 渲染。

## 日常路径依赖

- Python 3.10+（多数 ECS 自带；`python3 --version` 确认）
- git（可选，仅用于 `git pull` 更新代码）
- **无需** claude CLI、**无需** pip 包（纯标准库）

## 1. 取代码

优先 clone 内网 GitLab：
```bash
git clone https://code.alibaba-inc.com/qunbu/wechat.git /opt/wechat
```
ECS 不通 code-platform 时，从本机 rsync（需本机到 ECS 的 SSH）：
```bash
rsync -avz --exclude='__pycache__' --exclude='.git' --exclude='output' \
  /home/admin/workspace/wechat-main/ user@<ecs-ip>:/opt/wechat/
```

## 2. 配 Brave key（密钥绝不入库）

```bash
cat > /opt/wechat/.wechat-env <<'EOF'
export BRAVE_SEARCH_KEY=<你的 Brave API key>
EOF
chmod 600 /opt/wechat/.wechat-env
```
> `.wechat-env` 已在 `.gitignore`。key 明文传输过，建议在 Brave 控制台轮换一次。

验证取数（应返回有效 summary 条数 > 0）：
```bash
cd /opt/wechat
source .wechat-env
python3 scripts/brave_search.py --max-queries 2 --count 3 --output /tmp/t.json
cat /tmp/t.json | head
```

## 3. 首次手动跑

```bash
cd /opt/wechat
bash scripts/cron/daily-hotspot.sh
```
确认：
- `output/hotspot-report-<今天>.html` 生成且浏览器打开样式正常（卡片/五维条/分级标记）
- `output/state/scan-daily-<今天>.json` 有今日选题
- `output/cron/daily-<今天>.log` 无报错
- `topic-pool/scan-results.json` mtime 更新（高质量选题已注入共享池）

## 4. 挂 cron

```bash
crontab -e
# 加入（每天 09:30 本地时间，避开整点）
30 9 * * * /opt/wechat/scripts/cron/daily-hotspot.sh >> /opt/wechat/output/cron/cron.log 2>&1
```

## 链路说明

```
daily-hotspot.sh
  ├─ brave_search.py          # 取数：build_search_queries → Brave API → {query:summary}
  │   └─ output: /tmp/wechat-scan-{date}.json
  ├─ hot-scanner.py consume   # 评分
  │   ├─ min-score 0  → output/state/scan-daily-{date}.json  (当天全部选题，日报用)
  │   └─ min-score 6  → topic-pool/scan-results.json        (高质量注入共享池，自动去重)
  └─ daily_report.py          # 渲染 HTML
      └─ output: output/hotspot-report-{date}.html
```

**graceful fallback**：取数失败（无 key / Brave 不通 / 配额耗尽）→ 跳过 consume → 用共享池
`scan-results.json` 渲染 → 每天必有 HTML 落地。

## 故障排查

| 现象 | 排查 |
|------|------|
| 日报 0 卡片 | 查 `output/cron/daily-*.log`；取数是否失败；共享池是否为空 |
| Brave 401/403 | key 失效或配额耗尽 → 轮换 key，更新 `.wechat-env` |
| Brave 超时 | ECS 出网受限或 QPS 超限 → 调大 `--sleep`，或减小 `--max-queries` |
| HTML 空白页 | `scan-results.json` 损坏 → 备份后重跑 consume |

## 二期（可选）

接 DeepSeek/claude CLI（`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`，
`ANTHROPIC_MODEL=deepseek-v4-pro`）：用 LLM 把 Brave 片段炼成更丰富中文摘要再喂
consume，提升选题评分质量。日常日报不依赖。
