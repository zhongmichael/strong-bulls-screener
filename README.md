# 📈 多周期强势股选股器（Strong Bulls Screener）

基于 A 股日/周/月三周期均线结构的多周期强势股动态股池选股器 + V2.1 买点区域选股器，沪深 A 股约 5200 只全市场覆盖，支持历史日期回看与每日动态更新。

**在线演示**：https://cf97667128d24f65913823bb093afa45.app.workbuddy.link

> 架构：Node 服务（`dist_strong/server.js`）+ 可选的浏览器直开方式。服务端提供 `/api/refresh` 增量刷新接口，收盘后自动把数据拉到最新交易日。

---

## 🎯 核心功能

### 1️⃣ 强势股池（每日动态更新）

**强势股池 = 周月持续强势（规则D）**

- 周线近 10 周 **≥ 7 周**收盘站上周 MA5（核心条件）
- 且（月线近 12 月 **≥ 6 月**站上月 MA5 **或** 三周期强度 **≥ 50**）
- ⚠️ "日周月全站上 MA5" **不作为强势依据**——只是当日勉强站上三线（如方大集团周线仅 5/10、强度 5.6），非强势股
- 每日自动更新，跌破条件即剔除出池；周K/月K按"截至所选日期"动态聚合

### 2️⃣ 回踩 10 / 20 日线附近（强势回踩评分）

- 池内收盘偏离 MA10 / MA20 0~2.5% 且盘中触及
- **强势回踩评分（0~100）**：前期涨幅(近20日≥15%满分) + 均线多头排列与斜率向上 + 回踩缩量(10日<0.8×量/20日<0.7×量) + K线止跌(长下影/阳线/阳包阴) + 收回速度(站回MA5) + 周线多头配合
- 放量长阴破位、均线走平向下、周线走坏等失败形态被降权或剔除
- 按评分降序 TOP10，同分按强度二级排序

### 3️⃣ V2.1 买点区域（每日强势股池 × 回踩MA60）

移植《买点区域选股器 V2.1》算法，门禁 = 当前项目每日强势股池（规则D），与主页面日期联动：

| 等级 | 条件 | 含义 |
|---|---|---|
| 🔥 **S级** | 回踩MA60 + 周线共振 + 缩量 + Trigger | 核心买点 |
| 🎯 **A级** | 回踩MA60 + Trigger（缩量/均线向上/企稳K线三选二） | 试仓 |
| ⏳ **B级** | 回踩MA60 但 Trigger 未确认 | 观察 |
| 💤 **C级** | 低9 / RSI<30 | 非核心（仅记录） |

- **回踩MA60** = \|收盘−MA60\| / ATR14 ≤ 1.0
- **止损** = 20日低点（结构止损）
- 排除实体大阴线跌超 5%
- 列表按 R/R 盈亏比降序（优先关注 R/R≥2）
- 回测参考（原项目 V2.1）：S+A级 10日胜率72%、平均+7.65%；20日胜率75%、平均+14.85%
- 注：V2.1 有意移除 Market Score/R/R/趋势分/RS20 高门槛（回测证明高门槛反而筛出更差信号），S级数量在回调日可能较多，属设计预期

### 4️⃣ 涨跌停梯队与市场情绪

- 涨停/跌停家数、连板高度、温度分、昨日涨停溢价
- 温度分采用**双轨口径**：温度分输入用上线以来冻结的宽松口径；卡片/图表展示的涨跌停家数与连板高度用**真实涨跌停价**逐 bar 判定（含 ST 新规：2026-07-06 起沪深主板 ST 由 5% 调为 10%，创业/科创 ST 维持 20%）
- 标的范围 = 沪深 A 股（**不含北交所、B 股**），故与行情软件"全市场"口径存在约 350 只的固定差异

### 5️⃣ 其他

- 行业 / 概念双维度板块统计（柱状图 TOP15 + 表格 TOP30，可点击下钻）
- 周/月连续站上排序（周线连续 → 月线连续 → 强度 三要素）
- 上涨逻辑自动概括（20日涨幅/当日异动/站上年线/均线多头/三线共振）
- 历史任意交易日回看（按交易日历）

---

## 🚀 快速开始（协作开发）

### 环境要求

- **Python 3.9+**（数据抓取与计算）
- **Node.js 18+**（`server.js` 零第三方依赖，仅用标准库；`node --version` 可验证）

无需 `npm install` / `pip install`，脚本只用标准库与 `urllib`。

### 1. 克隆并安装

```bash
git clone <仓库地址>
cd td9-screener
```

### 2. 准备数据（首次，约 5~10 分钟）

**数据不入库**（体积 1GB+），需本地重建：

```bash
# 方式 A：一键全流程（9 步，推荐）
bash update_all.sh

# 方式 B：分步执行（便于调试）
python3 fetch_stocks.py          # 股票列表
python3 fetch_kline.py           # 全市场日K线（约3-4分钟）
python3 fetch_blocks.py          # 板块信息（行业+概念）
python3 compute_strong.py        # 强势/回踩/强度计算
python3 compute_buydian_v21.py   # V2.1 买点分级
python3 gen_gain_board.py        # 涨幅榜 + year_kline
python3 rebuild_gz.py            # 压缩 .gz 数据包
```

### 3. 本地起服务

```bash
cd dist_strong
node server.js            # 默认 http://localhost:3000（PORT 环境变量可改）
```

也可以直接用浏览器打开 `dist_strong/strong_screener.html`（需先跑过构建脚本生成数据包）。

### 4. 每日更新

```bash
bash update_all.sh        # 收盘后运行（15:30 之后）
```

---

## 📁 项目结构

```
td9-screener/
├── strong_screener.html      # ★ 主页面源文件（改前端从这里改）
├── compute_strong.py         # ★ 强势/回踩评分算法（离线全量）
├── compute_buydian_v21.py    # ★ V2.1 买点算法（离线全量）
├── fetch_*.py                # 数据抓取（股票列表 / K线 / 板块）
├── gen_*.py                  # 数据包生成（涨幅榜 / V2.1 页面）
├── update_all.sh             # ★ 一键 9 步更新脚本
├── rebuild_gz.py             # 重建 .gz 压缩包
├── backtest_*.py / .html     # 各策略历史回测
├── data/                     # 原始数据（不入库）
└── dist_strong/              # ★ 部署目录（node 服务）
    ├── server.js             # 服务端：/api/refresh 增量刷新 + 静态服务
    ├── refresh_core.js       # ★ 服务端增量刷新核心（与 Python 算法互为拷贝）
    ├── strong_screener.html  # 由根目录同步而来（勿直接改）
    ├── echarts.min.js        # 第三方图表库
    └── *.js / *.js.gz        # 数据包（不入库，脚本生成）
```

**关键关系**：根目录是**源**，`dist_strong/` 是**部署产物**。`update_all.sh` 会把根目录的 HTML 同步过去并重建 `.gz`。
**改前端请改根目录 `strong_screener.html`**，再跑脚本同步，不要直接改 `dist_strong/` 里的副本。

---

## 📄 文件说明

| 文件 | 说明 |
|---|---|
| `strong_screener.html` | 主选股器网页（入口，含 V2.1 买点模块 + 涨停梯队 + 涨幅榜） |
| `buydian_v21.html` | 独立 V2.1 买点页 |
| `compute_strong.py` | 全市场强势/回踩/强度计算（多进程） |
| `compute_buydian_v21.py` | V2.1 买点算法（逐日 S/A/B/C 分级） |
| `update_strong.py` | 一键更新：抓K线 → 重算 → 打包 → 同步部署目录 |
| `update_all.sh` | **完整 9 步更新脚本**（增量拉K → 覆盖率检查 → 重算 → meta → strong_data → gain_board/year_kline → 买点 → kline_ref → 同步 dist + gzip + 自检） |
| `gen_buydian_v21_page.py` | 打包 V2.1 网页数据（`buydian_v21_data.js`） |
| `gen_gain_board.py` | 生成涨幅榜与 `year_kline.js` |
| `fill_today_bar.py` | 当日 K 线补全（接口漏同步兜底） |
| `rebuild_gz.py` | 重建所有 `.gz` 数据包（`--targets` 可指定目录） |
| `fetch_kline.py` | 日K线抓取（腾讯接口，并发） |
| `fetch_stocks.py` | 全市场股票列表抓取 |
| `fetch_blocks.py` | 个股所属板块抓取（东财，行业+概念） |
| `dist_strong/server.js` | 部署服务端（`/api/refresh`、`/api/health`） |
| `dist_strong/refresh_core.js` | 服务端增量刷新核心（**与 Python 算法必须同步修改**） |
| `echarts.min.js` | 图表库（第三方） |

## 💾 数据文件（不入库，由脚本生成）

| 文件 | 说明 |
|---|---|
| `data/kline/*.json` | 全市场日K线（腾讯前复权，约 5200 只） |
| `data/out/strong_2026.json` | 逐日强势/回踩计算结果 |
| `data/out/buydian_v21_daily.json` | 逐日 V2.1 买点分级 |
| `strong_data.js` / `kline_ref.js` / `year_kline.js` | 网页数据包（`.gz` 优先加载） |
| `gain_board.js` / `buydian_v21_data.js` | 涨幅榜 / 买点数据包 |

> 为什么不入库：合计 1GB+，且随时可由脚本重建。仓库只保留源码，clone 后体积约 6MB。

---

## 🤝 参与开发

请先阅读 **[CONTRIBUTING.md](CONTRIBUTING.md)** —— 其中记录了**必须遵守的算法同步规则**与几处历史踩坑点（评分逻辑有三份拷贝、三套数据源与页面的对应关系、发布方式等），改动前务必过一遍。

```bash
git checkout -b feature/your-feature
# 开发 + 自测
git commit -m "feat: 描述"
git push origin feature/your-feature
# 然后在 GitHub 上发起 Pull Request
```

---

## ⚠️ 免责声明

本项目基于公开数据和量化分析，仅供参考，**不构成投资建议**。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。
