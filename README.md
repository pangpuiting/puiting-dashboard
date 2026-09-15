# 新会住宅地块 · 竞品工作台（云端版）

Puiting 的 JCR2026-59（新会08）地块竞品监控工作台。**全云端运行，本机无需开机。**

线上地址：https://www.puiting.org

---

## 架构

```
GitHub Actions (每日 09:00 北京时间)
   ├─ scripts/fetch_data.py   抓江门房产平台官方 API（9 个项目）
   ├─ scripts/update_html.py  差分更新 index.html 数字字段
   ├─ scripts/smoke_test.py   36 项结构完整性校验
   └─ git commit + push
            ↓
   Cloudflare Pages 自动部署（push 触发）
            ↓
   www.puiting.org（全球 CDN）
```

## 目录

| 文件 | 作用 |
|---|---|
| `index.html` | 工作台单文件（数据在 `const D` 对象内） |
| `data.json` | 每日抓取的官方原始数据（快照留档，便于回溯） |
| `scripts/fetch_data.py` | 抓官方 API。纯标准库，3 路并发，超时 60s / 重试 3 次 |
| `scripts/update_html.py` | **核心**：解析现有 mSnap → 差分 → 更新各盘数字 |
| `scripts/smoke_test.py` | 校验结构完整性与数据一致性 |
| `.github/workflows/daily-update.yml` | 定时任务 |

## 自动化更新范围

**每日自动更新**（确定性数据，脚本负责）：

- `updatedAt` — 更新日期
- `mSnap` — 各盘官方累计快照（差分基准）
- 各竞品 `sel: {sold, total, pct}` — 官方累计网签
- 各竞品 `m.sold` — 本月累计差分（同月累加 / 跨月自动重置）

**需人工/助手每周更新**（含智能判断，脚本不碰）：

- `selNote` / `m.note` — 文案中的数字与解读
- `m.p` / `m.pw` — 周报均价（来自房天下/房协周榜，需检索）
- `statusBar` — 状态栏文案
- `market` — 市场快照（周报/月报数据）
- `rankHist` — 月度排名历史（美智月榜，跨月归档）
- `policies` — 政策动态（需核实链接有效性）

> 设计取舍：云端脚本只做「不会判断错」的事。文案里的数字会滞后于 `sel`/`m`，这是刻意的——
> 宁可文案稍旧，也不让流水线生成错误解读。

## 本地测试

```bash
cd puiting-cloud
python scripts/fetch_data.py --out data.json          # 抓最新数据（约 40s）
python scripts/update_html.py --dry-run               # 预览变更（不写文件）
python scripts/update_html.py                         # 实际更新
python scripts/smoke_test.py --html index.html        # 校验
```

Windows 下若输出为空，加 `-u`（无缓冲）和 `PYTHONIOENCODING=utf-8`。

## 部署步骤

### 1. 推送到 GitHub

```bash
git init && git add -A
git commit -m "init: cloud dashboard"
git remote add origin https://github.com/<user>/<repo>.git
git branch -M main && git push -u origin main
```

### 2. Cloudflare Pages 绑定

CF Dashboard → Workers & Pages → Create → Pages → Connect to Git → 选本仓库：

- Framework preset: **None**
- Build command: **留空**
- Build output directory: **`/`**（根目录）

部署后得到 `<project>.pages.dev`。

### 3. 域名切换

CF Dashboard → Pages 项目 → Custom domains → 添加 `www.puiting.org`。

⚠️ 切换前须在 **DNS** 中删除原有的 `www` CNAME（原指向 cloudflared 隧道），否则冲突。
CF Pages 会自动写入正确的 CNAME。

切换后原隧道可保留作备用（改回 CNAME 即可回滚）。

## 故障处理

| 症状 | 原因 | 处理 |
|---|---|---|
| Actions 报 `FAILED projects` | 官方 API 短暂不可用（常见 502） | 无需处理，下次运行自动恢复；数据保持上次值 |
| Actions 报 `mSnap not found` | index.html 格式被改动 | 检查 mSnap 块格式是否仍为 `sold:{...}` |
| 页面数据落后 | Actions 被禁用 | 仓库 Settings → Actions → Enable；或手动 Run workflow |
| 某盘被跳过 | 增量异常（>50 或倒退） | 查看 Actions 日志 WARN，确认官方口径后手动修正 mSnap |

## 关键常量

- 官方 API：`jmzjj.jiangmen.cn:8085`（须带浏览器 UA，否则 412）
- `jgid`: `d111693f-6943-4f13-858a-cd61ff9184fd`
- 数据延迟：官方累计口径延迟 1 天发布
- 保利西海岸 = 今古洲 + 御海 两项目合并（均价按已售套数加权）
