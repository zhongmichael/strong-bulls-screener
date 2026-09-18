# 📈 多周期强势股选股器（Strong Bulls Screener）

一个页面三块功能（顶部 Tab 切换），覆盖沪深 A 股约 5200 只：

- **📋 选股器** —— 多周期强势股动态股池 + 回踩评分 + V2.1 买点区域
- **🚀 涨幅榜** —— 全市场/强势池 × 涨速/月/季/半年/年 五周期排行 + 趋势分类 + 入场信号
- **⚡ 涨停梯队** —— 连板梯队分层 + 市场情绪温度计（默认视图）

支持历史日期回看与每日动态更新。

**在线演示**：https://cf97667128d24f65913823bb093afa45.app.workbuddy.link

> 架构：Node 服务（`dist_strong/server.js`）+ 可选的浏览器直开方式。服务端提供 `/api/refresh` 增量刷新接口，收盘后自动把数据拉到最新交易日。

---

## 🧩 三大核心模块

页面顶部三个 Tab 切换，**默认进入 ⚡ 涨停梯队**。三个视图共享同一个「选择日期」控件（切换日期时联动刷新），但各自有独立的数据包与算法：

| Tab | 模块 | 页面主容器 | 依赖数据包 | 后端算法 / 生成脚本 |
|---|---|---|---|---|
| ⚡ **涨停梯队**（默认） | 连板梯队 + 市场情绪温度计 + 强势板块 TOP10（板块口径三选一：**同花顺概念板块**(默认，同花顺官方板块指数口径) / 通达信主题板块 / 东财概念题材；整卡点主平台 / 右下角标签点副平台） | `#ztCard` | `kline_ref.js`<br>`year_kline.js`<br>`ths_sector_ref.js`<br>`tdx_sector_ref.js`<br>`sector_ref.js` | `gen_gain_board.py`（year_kline）<br>`fetch_ths_blocks.py`（同花顺板块指数口径）<br>`fetch_tdx_blocks.py`（通达信主题板块）<br>`gen_sector_ref.py`（东财概念映射 + 双平台板块代码）<br>+ 页面内 `ztCompute` / `ztSentiment` / `sectorTop10` |
| 🚀 **涨幅榜** | 多周期涨幅排行 + 趋势分类 + 入场信号 | `#gainCard` | `gain_board.js`<br>`year_kline.js`<br>`kline_ref.js` | `gen_gain_board.py`<br>+ 页面内趋势 / 信号计算 |
| 📋 **选股器** | 强势股池 + 回踩评分 + V2.1 买点 | `#filters` `#cards` `#blkCard`<br>`.list-card` `#bd21Card` `.pull-cards` | `strong_data.js`<br>`kline_ref.js`<br>`buydian_v21_data.js` | `compute_strong.py`<br>`compute_buydian_v21.py`<br>`gen_buydian_v21_page.py` |

> `strong_data.js` 里的 `meta`（名称 / 一级行业 / 收盘 / 当日涨跌幅）是三个模块共用的公共底座。
> 三个 Tab 的显示切换逻辑在 `strong_screener.html` 末尾的 `applyView()`（视图互斥的容器清单写在 `screenerBlocks` 里，新增卡片必须同步登记，否则会在错误的视图下露出来）。

### ⚡ 涨停梯队（默认视图）

- 🌡️ **市场情绪温度计**：温度分 = 涨停家数 28% + 昨涨停溢价 24% + 涨跌比 20% + 跌停 14% + 连板高度 14%
  - 附带**全交易日情绪曲线**：拖动底部滑块/滚轮可回看约一年，**点击曲线上的某天可直接切换日期**
  - **温度分口径自上线起冻结不变**（保证曲线与冰点触发连续可比），卡片展示的涨跌停家数则用**真实涨跌停价**逐 bar 判定（含 ST 新规：2026-07-06 起沪深主板 ST 由 5% 调为 10%，创业/科创 ST 维持 20%）
- 🔥🚀💥 **连板梯队三列**：龙头梯队（3板+） / 晋级梯队（2板） / 首板梯队，标注是否一字板（开盘即封）
- 📊 **涨停板块热度饼图**：点击扇区/图例下钻查看该板块涨停个股明细
- 🧊 **冰点策略卡片**：极寒情绪下的机会提示
- ⚠️ 标的范围 = 沪深 A 股（**不含北交所、B 股**），故涨跌家数与行情软件的「全市场」口径存在约 350 只的固定差异（多出来的是北交所，且其中绝大多数是下跌股）

### 🚀 涨幅榜

- **两种范围 × 五个周期**，二维组合出榜（各 TOP50）
  - 范围：**全市场** / **仅强势股池**（`gainScope`）
  - 周期：⚡涨速（近 5 交易日） / 月度（月初至今） / 季度（前 60 交易日） / 半年度（前 120 交易日） / 年度（年初至今）
- 📊 **板块分布饼图**：当前周期 TOP50 的行业分布，点击扇区/图例下钻个股明细
- 📈 **趋势分类**：五个榜单合并股池，按近一两月 K 线形态分为 🔥强势股 / ⚖️震荡 / 📉下跌趋势 三栏
- 🏹 **猎手·综合入场信号**：月度榜 + 涨速榜合并池 × OHLCV，输出四类信号（🔵缩量回踩 / 🔴反转确认 / 🟠放量突破 / 🟣洗盘回探），带板块共振加分与追高减分
- 🎯 **入场候选 TOP10**：趋势 30 + 回调 25 + 动量 25 + 整理 20 四维评分，含**突破回踩有效性约束**（真突破 / 回踩深度 ≤15% / 快速企稳 / 缩量回踩）
- 🎛️ **震荡股入场信号（至善·波段过滤器 V3.0）**：对趋势分类中的"震荡"股应用超卖反转 / 变盘预警 / 底背离，带右侧确认加成与陈旧信号衰减

### 📋 选股器

#### 1️⃣ 强势股池（每日动态更新）

**强势股池 = 周月持续强势（规则D）**

- 周线近 10 周 **≥ 7 周**收盘站上周 MA5（核心条件）
- 且（月线近 12 月 **≥ 6 月**站上月 MA5 **或** 三周期强度 **≥ 50**）
- ⚠️ "日周月全站上 MA5" **不作为强势依据**——只是当日勉强站上三线（如方大集团周线仅 5/10、强度 5.6），非强势股
- 每日自动更新，跌破条件即剔除出池；周K/月K按"截至所选日期"动态聚合

#### 2️⃣ 回踩 10 / 20 日线附近（强势回踩评分）

- 池内收盘偏离 MA10 / MA20 0~2.5% 且盘中触及
- **强势回踩评分（0~100）**：前期涨幅(近20日≥15%满分) + 均线多头排列与斜率向上 + 回踩缩量(10日<0.8×量/20日<0.7×量) + K线止跌(长下影/阳线/阳包阴) + 收回速度(站回MA5) + 周线多头配合
- 放量长阴破位、均线走平向下、周线走坏等失败形态被降权或剔除
- 按评分降序 TOP10，同分按强度二级排序

#### 3️⃣ V2.1 买点区域（每日强势股池 × 回踩MA60）

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

#### 4️⃣ 板块分布统计与强势池列表

- 行业 / 概念双维度板块统计（柱状图 TOP15 + 表格 TOP30）：点击柱子或表格行可筛选列表仅显示该板块个股，点击数量弹出该板块个股明细
- 强势股池明细表：按「趋势延续+动量 / 强度 / 当日涨跌幅 / 代码」排序，支持代码名称搜索、屏蔽 ST；列出强度%、回踩10/20评分与上涨逻辑

## 🔄 模块 ↔ 数据链路（改代码前必看）

`update_all.sh` 的 9 个步骤分别产出哪些数据包、被哪个模块消费——**改任一环节前先确认影响面**：

| 步骤 | 产出 | 消费模块 |
|---|---|---|
| [1][2] 增量拉 K 线 / 覆盖率检查 + 补当日 bar | `data/kline/*.json` | 全部模块的底座数据 |
| [3] `compute_strong.py` 重算强势股 | `data/out/strong_*.json` | 📋 选股器 |
| [4] 重建 meta（含新股） | `data/out/meta.json` | 📋 选股器 / 🚀 涨幅榜 / ⚡ 涨停梯队（公共） |
| [5] 生成 strong_data.js | `strong_data.js` | 📋 选股器（含三个模块共用的 `meta`） |
| [6] `gen_gain_board.py` | `gain_board.js` + `year_kline.js` | 🚀 涨幅榜 + ⚡ 涨停梯队 |
| [7] `compute_buydian_v21.py` + `gen_buydian_v21_page.py` | `buydian_v21_data.js` | 📋 选股器（V2.1 买点） |
| [8] 生成 kline_ref | `kline_ref.js` | **三个模块都用**（止损 / 回踩 / 连板 / 趋势分类） |
| [9] 同步 dist_strong + gzip + 发布自检 | `dist_strong/*.js.gz` | 线上服务 |

> `sector_ref.js`（概念题材映射，供涨停梯队的「强势板块 TOP10」用）**不在这 9 步里**——板块归属变化很慢，
> 离线跑一次即可，依赖三个文件：
> ```bash
> python3 fetch_block_codes.py   # ① data/out/block_codes.json    ← 概念名 → 东财板块代码(BKxxxx)
> python3 fetch_ths_codes.py     # ② data/out/ths_block_codes.json ← 概念名 → 同花顺概念代码(6位数字)
> python3 gen_sector_ref.py      # ③ sector_ref.js ← stock_blocks.json + 上面两份代码表
> ```
> **两套代码体系互不相通**（东财 `BK0877` ≠ 同花顺 `308832`），而且概念命名差异很大
> （`PCB`→`PCB概念`、`5G概念`→`5G`、`新能源车`→`新能源汽车`），同花顺侧只有约 **55%**（219/401）能对上；
> 对不上的概念在页面上**不渲染同花顺入口**（不猜、不硬套到名字相近但成分不同的板块上）。
> 两份代码表都**不是硬依赖**：缺哪个，对应的入口就不渲染，不会报错。
> `fetch_ths_codes.py` 里有一张人工核对的 `ALIAS` 别名表，要扩覆盖率改那里。
> 日常更新若要刷新，重跑上面三个脚本后 `python3 rebuild_gz.py --targets . dist_strong` 重新压缩。
>
> **`tdx_sector_ref.js`（通达信主题板块，供「强势板块 TOP10」切换口径用）**同样不在这 9 步里：
> ```bash
> python3 fetch_tdx_blocks.py            # tdx_sector_ref.js + data/out/tdx_blocks.json（增量，命中过的名字走缓存）
> python3 fetch_tdx_blocks.py --rebuild  # 忽略缓存全量重探
> ```
> 数据源是**通达信官方 Web 网关 TQLEX**（`page.tdx.com.cn:7615`，与通达信客户端 F10「主题板块」页同一上游，
> **无需授权/密钥**）。该接口只能**按板块名精确查询、没有公开的列表接口**，所以脚本用「候选名探测」重建板块全集：
> 拿我们自己的 401 个概念名 + 同花顺概念名 + 人工补充的常见题材名共 626 个逐个探测，命中 305 个 →
> 去重 + 剔除「最近多板/近期新高/次新股/摘帽」等交易事件榜 → 保留 **288 个主题板块 / 覆盖 5161 只**。
> 想扩覆盖率就往脚本里的 `EXTRA` 列表加名字，或用 `--rebuild` 重探。
>
> **`ths_sector_ref.js`（同花顺概念板块，默认口径）**同样不在这 9 步里：
> ```bash
> python3 fetch_ths_blocks.py            # ths_sector_ref.js + data/out/ths_blocks.json（增量，7 天内走缓存）
> python3 fetch_ths_blocks.py --rebuild  # 忽略缓存全量重抓
> python3 fetch_ths_blocks.py --verify   # 自检：拿免费可抓全的小板块成分股与同花顺字段对拍
> ```
> 数据源是**同花顺公开行情桥 `d.10jqka.com.cn`**（与同花顺 App 同一数据源，**无需登录/授权/Cookie**），
> 走 `/v6/realhead/48_<板块指数代码>/defer/last.js`，一次拿全 **361 个概念板块**的官方统计：
> 成分股数、上涨/下跌家数、**涨停家数**、首板、连板、成交额、涨跌幅、振幅。板块指数代码从
> 概念页的 `<input id="clid">` 取（`885xxx` / `886xxx`）。
>
> ⚠️ **为什么不用「抓成分股自己算」**：同花顺概念成分股页非登录态只开放前 5 页（50 只），
> 第 6 页 302 跳 `/account/login/`；而 ajax 翻页接口被 chameleon 风控（401）+ nginx（403）拦死。
> 机器人概念有 1230 只、人工智能 1090 只，抓不全就只能拿到「涨幅前 50」这种**有偏样本**，
> 算涨停率会严重失真 —— 所以改用同花顺自己的板块指数统计，反而更权威、覆盖全。
>
> 字段语义已**逐只对拍验证**（`--verify`）：取 6 个成分股 ≤50 只的板块抓全成分股自算，
> 成分股数 6/6 全等、涨停家数 6/6 全等；再用 `tdx_sector_ref.js` 里**独立成分**的同名板块交叉验证
> 大板块（华为概念 13=13、机器人概念 13=13、商业航天 12=12、汽车电子 9=9、无人机 9=9）。
> 涨跌家数差 0~7 只，差在同花顺口径含北交所/停牌股而我们不含。

> ⚠️ 三个模块各读不同数据源，**改动数据合并逻辑后必须逐个视图验证**，只验一个视图会漏（2026-09-03 教训）。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 🧭 通用功能

- 历史任意交易日回看（按交易日历，三个视图联动切换）
- 🔄 **刷新最新数据** 按钮 + 打开/刷新页面自动核对：盘中每次真拉到最新，收盘后第一次访问强制真刷核对（修正盘中快照），核对过之后秒回缓存
- 上涨逻辑自动概括（20日涨幅 / 当日异动 / 站上年线 / 均线多头 / 三线共振）

---

## 🚀 快速开始（协作开发）

### 环境要求

| 依赖 | 版本 | 说明 |
|---|---|---|
| **Python** | 3.9+ | 数据抓取与计算 |
| **numpy** | ≥ 1.19 | `compute_strong.py` / `compute_buydian_v21.py` 依赖（其余脚本只用标准库） |
| **Node.js** | 18+ | `server.js` / `refresh_core.js` **零第三方依赖**，只用标准库，无需 `npm install` |

### 1. 克隆并安装

```bash
git clone https://github.com/zhongmichael/strong-bulls-screener.git
cd strong-bulls-screener

# 只需安装 numpy（见 requirements.txt）
pip3 install -r requirements.txt
```

> 除 numpy 外无任何第三方依赖：抓取脚本用 `urllib`，服务端用 Node 标准库。

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
python3 fetch_block_codes.py      # 概念名 → 东财板块代码（卡片主入口跳转，离线跑一次）
python3 fetch_ths_codes.py        # 概念名 → 同花顺概念代码（卡片副入口，离线跑一次）
python3 gen_sector_ref.py        # 东财概念题材映射（涨停梯队「强势板块 TOP10」口径之一）
python3 fetch_tdx_blocks.py      # 通达信主题板块映射（同一模块的口径之二; 走通达信官方 TQLEX 网关, 免授权）
python3 fetch_ths_blocks.py      # 同花顺概念板块（同一模块的默认口径; 走同花顺公开行情桥 d.10jqka.com.cn, 免授权）
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
strong-bulls-screener/
├── strong_screener.html      # ★ 主页面源文件（三个模块都在这个文件里：选股器 / 涨幅榜 / 涨停梯队）
├── requirements.txt          # Python 依赖（仅 numpy）
├── compute_strong.py         # ★ 选股器：强势/回踩评分算法（离线全量）
├── compute_buydian_v21.py    # ★ 选股器：V2.1 买点算法（离线全量）
├── gen_gain_board.py         # ★ 涨幅榜 + 涨停梯队：生成 gain_board.js / year_kline.js
├── fetch_*.py                # 数据抓取（股票列表 / K线 / 板块）
├── gen_*.py                  # 数据包生成（V2.1 页面等）
├── update_all.sh             # ★ 一键 9 步更新脚本
├── rebuild_gz.py             # 重建 .gz 压缩包
├── backtest_*.py / .html     # 各策略历史回测
├── data/                     # 原始数据（不入库）
└── dist_strong/              # ★ 部署目录（node 服务）
    ├── server.js             # 服务端：/api/refresh 增量刷新 + 静态服务
    ├── refresh_core.js       # ★ 服务端增量刷新核心（与 Python 算法互为拷贝）
    ├── strong_screener.html  # 由根目录同步而来（勿直接改）
    ├── buydian_v21.html      # 独立 V2.1 买点页
    ├── echarts.min.js        # 第三方图表库
    └── *.js / *.js.gz        # 数据包（不入库，脚本生成）
```

**关键关系**：根目录是**源**，`dist_strong/` 是**部署产物**。`update_all.sh` 会把根目录的 HTML 同步过去并重建 `.gz`。
**改前端请改根目录 `strong_screener.html`**，再跑脚本同步，不要直接改 `dist_strong/` 里的副本。

**三个模块共用一个 HTML 文件**：`strong_screener.html` 由多个 IIFE 模块拼成（boot 主逻辑 / V2.1 买点 / 涨停梯队 / 涨幅榜），闭包互不相通，跨模块调用必须走 `window` 钩子（`selectDateHook`、`bdSetDate`、`__refreshZt`、`__refreshGain`）。

---

## 📄 文件说明

| 文件 | 说明 | 服务模块 |
|---|---|---|
| `strong_screener.html` | **主页面（三个模块的入口）**：含选股器主逻辑、V2.1 买点、涨停梯队、涨幅榜四个 IIFE 模块 | 全部 |
| `buydian_v21.html` | 独立 V2.1 买点页 | 📋 选股器 |
| `requirements.txt` | Python 依赖清单（仅 `numpy`） | 全部 |
| `compute_strong.py` | 全市场强势/回踩/强度计算（多进程） | 📋 选股器 |
| `compute_buydian_v21.py` | V2.1 买点算法（逐日 S/A/B/C 分级） | 📋 选股器 |
| `gen_buydian_v21_page.py` | 打包 V2.1 网页数据（`buydian_v21_data.js`） | 📋 选股器 |
| `gen_gain_board.py` | 生成涨幅榜与 `year_kline.js` | 🚀 涨幅榜 / ⚡ 涨停梯队 |
| `update_strong.py` | 一键更新：抓K线 → 重算 → 打包 → 同步部署目录 | 全部 |
| `update_all.sh` | **完整 9 步更新脚本**（增量拉K → 覆盖率检查 → 重算 → meta → strong_data → gain_board/year_kline → 买点 → kline_ref → 同步 dist + gzip + 自检） | 全部 |
| `fill_today_bar.py` | 当日 K 线补全（接口漏同步兜底） | 全部 |
| `rebuild_gz.py` | 重建所有 `.gz` 数据包（`--targets` 可指定目录） | 全部 |
| `fetch_kline.py` | 日K线抓取（腾讯接口，并发） | 全部 |
| `fetch_stocks.py` | 全市场股票列表抓取 | 全部 |
| `fetch_blocks.py` | 个股所属板块抓取（东财，行业+概念） | 📋 选股器 / 🚀 涨幅榜 / ⚡ 涨停梯队（板块维度） |
| `dist_strong/server.js` | 部署服务端（`/api/refresh`、`/api/health`） | 全部 |
| `dist_strong/refresh_core.js` | 服务端增量刷新核心（**与 Python 算法必须同步修改**） | 全部 |
| `echarts.min.js` | 图表库（第三方） | 全部 |

## 💾 数据文件（不入库，由脚本生成）

| 文件 | 说明 |
|---|---|
| `data/kline/*.json` | 全市场日K线（腾讯前复权，约 5200 只） |
| `data/out/strong_2026.json` | 逐日强势/回踩计算结果 |
| `data/out/buydian_v21_daily.json` | 逐日 V2.1 买点分级 |
| `strong_data.js` / `kline_ref.js` / `year_kline.js` | 网页数据包（`.gz` 优先加载） |
| `sector_ref.js` / `tdx_sector_ref.js` / `ths_sector_ref.js` | 板块数据包（东财概念归属 / 通达信主题归属 / 同花顺官方板块指数统计），懒加载，`.gz` 优先 |
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
