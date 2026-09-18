// =============================================================
// refresh_core.js — 服务端"增量刷新"核心 (node, 零依赖)
// -------------------------------------------------------------
// 用途: 线上站点点「刷新最新数据」/每日任务调用 /api/refresh 时,
//       从"当前已发布数据"(基线)出发, 增量拉取腾讯行情补到最新交易日:
//         · 已有历史日期的 K 线全部复用, 只补缺失交易日(按日期合并, 不覆盖历史)
//         · 周/月收盘序列按 ISO 周 / 自然月判断"跨期追加 or 同期待覆盖"
//         · 计算逻辑与前端 strong_screener.html 的 computeOne 1:1 对齐
//       完成后把 strong_data / year_kline / kline_ref / gain_board / buydian_v21_data 的
//       .js 与 .gz 原子写回(部署目录), 所有访客立即可见, 无需重新发布。
// -------------------------------------------------------------
// 注意: 凡改本文件计算逻辑, 必须同步 strong_screener.html 中的同名函数
//       (smaAt / isoWeekKey / scorePullback / computeOne)。
// =============================================================
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

// ---------- 纯函数 (与 strong_screener.html 1:1 移植) ----------

// 收盘/成交量 简单移动平均: vi=2取收盘, vi=5取成交量
function smaAt(dArr, endIdx, n, vi){
  if(endIdx + 1 < n) return null;
  let s = 0;
  for(let i = endIdx - n + 1; i <= endIdx; i++) s += +dArr[i][vi];
  return s / n;
}

// ISO 周键 (年*100+周), 与 Python date.isocalendar() / JS html 版一致
function isoWeekKey(dstr){
  const p = dstr.split('-');
  const d = new Date(+p[0], (+p[1]) - 1, +p[2]);
  d.setHours(0,0,0,0);
  const thu = new Date(d.getTime());
  thu.setDate(thu.getDate() - (thu.getDay()+6)%7 + 3);   // 本周周四
  const y = thu.getFullYear();
  const f = new Date(y, 0, 4);
  f.setHours(0,0,0,0);
  const fThu = new Date(f.getTime());
  fThu.setDate(fThu.getDate() - (fThu.getDay()+6)%7 + 3);
  return y * 100 + 1 + Math.round((thu.getTime() - fThu.getTime()) / 604800000);
}

// 强势回踩评分 (与 html scorePullback 1:1)
function scorePullback(dArr, i, ma5, ma10, ma20, wseq, wi, target){
  const tgt = target === 'ma10' ? ma10 : ma20;
  const shrink = target === 'ma10' ? 0.8 : 0.7;
  if(tgt == null) return 0;
  const o = +dArr[i][1], c = +dArr[i][2], h = +dArr[i][3], l = +dArr[i][4], v = +dArr[i][5];
  let score = 0;
  // 1. 前期涨幅 (0-20)
  if(i >= 20){
    const ret20 = (c / (+dArr[i-20][2]) - 1) * 100;
    if(ret20 >= 15) score += 20; else if(ret20 >= 10) score += 15; else if(ret20 >= 5) score += 8;
  }
  // 2. 均线多头 (0-20)
  const pma5 = smaAt(dArr, i, 5, 2), pma10 = smaAt(dArr, i, 10, 2), pma20 = smaAt(dArr, i, 20, 2);
  if(pma5 != null && pma10 != null && pma20 != null && pma5 > pma10 && pma10 > pma20) score += 10;
  if(i >= 1){
    const q10 = smaAt(dArr, i-1, 10, 2), q20 = smaAt(dArr, i-1, 20, 2);
    if(pma10 != null && q10 != null && pma10 > q10) score += 5;
    if(pma20 != null && q20 != null && pma20 > q20) score += 5;
  }
  // 3. 回踩深度 (0-15)
  const touch = target === 'ma10' ? (l <= tgt * 1.01) : (l <= tgt * 1.02);
  if(touch) score += 10;
  if(c > tgt) score += 5;
  // 4. 缩量确认 (0-15)
  const vma5 = smaAt(dArr, i, 5, 5);
  if(vma5 != null && vma5 > 0){
    const vr = v / vma5;
    if(vr < shrink) score += 15;
    else if(vr < 1.0) score += 10;
    else if(vr < 1.2) score += 5;
    else if(vr >= 1.5) score -= 10;
  }
  // 5. K线止跌 (0-15): 长下影 / 阳线或十字星 / 阳包阴
  const body = c - o, rng = h - l, lower = Math.min(o, c) - l;
  if(rng > 0 && lower > Math.abs(body) * 2) score += 6;
  if(body > 0 || (rng > 0 && Math.abs(body) / rng < 0.1)) score += 4;
  if(i >= 1 && body > 0 && (+dArr[i-1][2] < +dArr[i-1][1])
     && c >= +dArr[i-1][1] && o <= +dArr[i-1][2]) score += 5;
  // 6. 收回速度 (0-15)
  if(pma5 != null && c > pma5) score += 8;
  if(c > tgt) score += 7;
  // 7. 大周期配合 (0-10)
  if(wi >= 4){
    let s5 = 0; for(let k = wi-4; k <= wi; k++) s5 += wseq[k];
    if(c > s5/5) score += 6;
  }
  if(wi >= 9){
    let s10 = 0; for(let k2 = wi-9; k2 <= wi; k2++) s10 += wseq[k2];
    if(c > s10/10) score += 4;
  }
  // 8. 回踩节奏 (突破回踩有效性: 大阴线砸下=假突破 / 碎步阴跌动能衰竭=健康)
  const body0 = c - o;
  if(i >= 1){
    const pBody = (+dArr[i-1][2]) - (+dArr[i-1][1]);
    if(body0 < 0 && c > 0 && body0 / c <= -0.032) score -= 20;             // 当日大阴线(实体≤-3.2%)
    else if(body0 < 0 && pBody < 0 && body0 > pBody * 0.5) score += 4;     // 阴线实体较昨日收窄过半: 下跌动能衰竭
  }
  // 9. 深度极限 (不能深入前期震荡箱体下半部)
  if(l < tgt * 0.97) score -= 15;                                          // 盘中深破均线3%以上: 突破失败
  // 10. 时间过滤 (有效回踩3-5根K线内企稳, 久盘必跌)
  let pullDays = 0;
  for(let pd = i; pd >= 0 && pd > i - 12; pd--){
    const m5v = (pd === i) ? pma5 : smaAt(dArr, pd, 5, 2);
    if(m5v != null && (+dArr[pd][2]) < m5v) pullDays++; else break;
  }
  if(pullDays >= 6) score -= 20;                                           // 久盘: 连续6日以上站不回MA5
  else if(pullDays <= 2) score += 5;                                       // 快速企稳
  // 11. 突破放量→回踩缩量 对比 (放量突破是前提, 缩量回踩是过程)
  if(i >= 5){
    let vBrk = 0;
    for(let vb = (i - 20 > 0 ? i - 20 : 0); vb < i; vb++){ const vv = +dArr[vb][5]; if(vv > vBrk) vBrk = vv; }
    if(vBrk > 0){
      if(v < vBrk * 0.55) score += 5;                                      // 较突破日峰值显著缩量
      else if(v >= vBrk * 0.85) score -= 5;                                // 回踩量接近突破日: 抛压未消化
    }
  }
  return Math.round(Math.max(Math.min(score, 100), 0) * 10) / 10;
}

// 计算单只股票在"最新日"的强势数据 (与 html computeOne 1:1)
// dArr: 日K数组(最后1根=最新)  wArr: 周收盘数组  mArr: 月收盘数组
function computeOne(sym, dArr, wArr, mArr){
  const n = dArr.length;
  const last = dArr[n-1];
  const date = last[0], c = +last[2];
  if(n < 6) return null;
  // 日线MA5
  let s5=0; for(let i=n-5;i<n;i++) s5+= +dArr[i][2]; const dma5 = s5/5;
  const dayOk = c > dma5;
  // 周线: 最新周=部分周, 收盘用c; 周MA5序列
  const wi = wArr.length - 1;
  let weekOk = false, wkUp10 = 0, wkStreak = 0;
  let s5w = 0, wma5 = c;
  if(wi >= 4){
    const wc = c;
    s5w = 0; for(let j=wi-4;j<=wi;j++) s5w += (j===wi?wc:wArr[j]); wma5 = s5w/5;
    weekOk = wc > wma5;
    const seq = wArr.slice(0, wi).concat([wc]);
    for(let k=0;k<10 && wi-k>=4;k++){
      const idx = wi-k;
      let s5k = 0; for(let j=idx-4;j<=idx;j++) s5k += seq[j];
      if(seq[idx] > s5k/5) wkUp10++;
    }
    for(let k2=0; k2<14 && wi-k2>=4; k2++){
      const idx2 = wi-k2;
      let s5k2 = 0; for(let j=idx2-4;j<=idx2;j++) s5k2 += seq[j];
      if(seq[idx2] > s5k2/5) wkStreak++; else break;
    }
  }
  // 月线
  const mi = mArr.length - 1;
  let moOk = false, moUp12 = 0, moStreak = 0;
  let s5m = 0, mma5 = c;
  if(mi >= 4){
    const mc = c;
    s5m = 0; for(let j=mi-4;j<=mi;j++) s5m += (j===mi?mc:mArr[j]); mma5 = s5m/5;
    moOk = mc > mma5;
    const mseq = mArr.slice(0, mi).concat([mc]);
    for(let k=0;k<12 && mi-k>=4;k++){
      const idx = mi-k;
      let s5k = 0; for(let j=idx-4;j<=idx;j++) s5k += mseq[j];
      if(mseq[idx] > s5k/5) moUp12++;
    }
    for(let k2=0; k2<16 && mi-k2>=4; k2++){
      const idx2 = mi-k2;
      let s5k2 = 0; for(let j=idx2-4;j<=idx2;j++) s5k2 += mseq[j];
      if(mseq[idx2] > s5k2/5) moStreak++; else break;
    }
  }
  // 三周期强度 = 乖离率之和
  const biasD = (c/dma5 - 1)*100;
  const biasW = (c/wma5 - 1)*100;
  const biasM = (c/mma5 - 1)*100;
  const strength = Math.round((biasD + biasW + biasM) * 100) / 100;
  const r2 = function(x){ return Math.round(x * 100) / 100; };
  const r1 = function(x){ return Math.round(x * 10) / 10; };
  // r[14] 当日涨跌幅 (上一交易日收盘为基准)
  const day_pct = n >= 2 ? (c / (+dArr[n-2][2]) - 1) * 100 : 0;
  // r[13] 近20日涨幅
  const ret20 = n >= 21 ? (c / (+dArr[n-21][2]) - 1) * 100 : 0;
  // r[4]/r[5] 相对MA10/MA20乖离
  const ma10 = smaAt(dArr, n-1, 10, 2), ma20 = smaAt(dArr, n-1, 20, 2);
  const bias10 = ma10 != null ? (c/ma10 - 1) * 100 : null;
  const bias20 = ma20 != null ? (c/ma20 - 1) * 100 : null;
  // r[6]/r[7] 基础回踩判定
  const lo = +last[4];
  const pull10 = (bias10 != null && bias10 >= 0 && bias10 <= 2.5 && lo <= ma10 * 1.01) ? 1 : 0;
  const pull20 = (bias20 != null && bias20 >= 0 && bias20 <= 2.5 && lo <= ma20 * 1.02) ? 1 : 0;
  // r[9]/r[10] 强势回踩评分
  const wseq = wArr.slice(0, wi).concat([c]);
  const pull10_score = pull10 ? scorePullback(dArr, n-1, dma5, ma10, ma20, wseq, wi, 'ma10') : 0;
  const pull20_score = pull20 ? scorePullback(dArr, n-1, dma5, ma10, ma20, wseq, wi, 'ma20') : 0;
  // r[11] 均线多头 / r[12] 站上年线
  const bull = (ma10 != null && ma20 != null && dma5 > ma10 && ma10 > ma20) ? 1 : 0;
  const ma250 = smaAt(dArr, n-1, 250, 2);
  const above_year = (ma250 != null && c > ma250) ? 1 : 0;
  // r[8] 形态强势分
  const mom5 = n >= 6 ? (c / (+dArr[n-6][2]) - 1) * 100 : 0;
  let form = strength;
  if(bull) form += 8;
  if(above_year) form += 6;
  form += Math.max(Math.min(mom5 * 0.5, 5), 0);
  if(day_pct >= 0 && day_pct < 5) form += 3;
  else if(day_pct >= 9) form -= 3;
  const form_score = r1(form);
  return {
    r: [dayOk?1:0, weekOk?1:0, moOk?1:0, strength,
        bias10 == null ? null : r2(bias10),
        bias20 == null ? null : r2(bias20),
        pull10, pull20, form_score, pull10_score, pull20_score,
        bull, above_year, r1(ret20), r2(day_pct),
        wkUp10, moUp12, wkStreak, moStreak],
    date: date, close: c
  };
}

// ---------- 文件 IO ----------

function parseJs(text){
  // 去掉 "window.XXX = " 前缀与末尾分号, 返回 JSON 文本
  let t = text;
  const eq = t.indexOf('=');
  if(eq >= 0) t = t.slice(eq + 1);
  t = t.trim();
  while(t.endsWith(';')) t = t.slice(0, -1).trim();
  return JSON.parse(t);
}
function readData(dir, name){
  // 优先读明文 .js(与 .gz 内容一致, 已由发布自检保证), 缺失时尝试 .gz
  const jsPath = path.join(dir, name + '.js');
  try {
    if(fs.existsSync(jsPath)) return parseJs(fs.readFileSync(jsPath, 'utf8'));
  } catch(e) { /* fallthrough */ }
  const gzPath = path.join(dir, name + '.js.gz');
  const buf = fs.readFileSync(gzPath);
  return parseJs(zlib.gunzipSync(buf).toString('utf8'));
}
function writeJsGz(dir, name, obj, extraHeader){
  const text = (extraHeader || 'window.' + name.toUpperCase().replace(/-/g,'_') + ' = ')
    + JSON.stringify(obj) + ';';
  const jsPath = path.join(dir, name + '.js');
  const gzPath = path.join(dir, name + '.js.gz');
  const tmpJs = jsPath + '.tmp', tmpGz = gzPath + '.tmp';
  fs.writeFileSync(tmpJs, text, 'utf8');
  fs.writeFileSync(tmpGz, zlib.gzipSync(text, {level: 6}));
  fs.renameSync(tmpJs, jsPath);   // 原子替换, 避免读到半截文件
  fs.renameSync(tmpGz, gzPath);
  return text.length;
}

// ---------- 数据拉取 (腾讯行情) ----------

function httpGet(url, timeoutMs){
  return fetch(url, { signal: AbortSignal.timeout(timeoutMs || 20000), headers: {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://gu.qq.com/'
  }});
}
async function fetchKline(sym, startStr, endStr){
  // 与前端 fetchLatest / update_all.sh 同一接口与窗口(<=50根), 返回 [date,o,c,h,l,v,...] 数组
  // 关键: **不要传 start/end 区间**。
  // 收盘后(15:05~晚间)带显式区间的请求会稳定少给一天(实测 2026-09-18 16:40:
  // `...,day,2026-08-04,2026-09-18,50,qfq` 末日恒为 2026-09-17, 20/20;
  // 而 `...,day,,,50,qfq` 末日是 2026-09-18 且收盘价与实时行情 80/80 全等)。
  // 后果: 覆盖率 cover 掉到 1.7% -> 既追加不了当日 bar, 也无法用真实收盘价覆盖
  // 已经写进 ref/year_kline 的"盘中快照"(open 对、close/low/vol 停在盘中某刻),
  // 快照被永久固化。无区间请求固定返回最近 51 根, 足够覆盖 REPAIR_N(8) 的校验窗口。
  const url = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get?param='
    + sym + ',day,,,50,qfq';
  const r = await httpGet(url, 20000);
  const j = await r.json();
  const item = (j && j.data && j.data[sym]) || {};
  return item.qfqday || item.day || [];
}
async function fetchQuotes(symbols){
  // qt.gtimg.cn 实时行情批量(50/批, 返回 GBK 文本), 用于探测交易日与补当日 bar
  const out = {};
  for(let i = 0; i < symbols.length; i += 50){
    const batch = symbols.slice(i, i + 50);
    const url = 'https://qt.gtimg.cn/q=' + batch.join(',');
    try {
      const r = await httpGet(url, 20000);
      const raw = new TextDecoder('gbk').decode(Buffer.from(await r.arrayBuffer()));
      for(const line of raw.split(';')){
        if(line.indexOf('~') < 0) continue;
        const parts = line.split('~');
        if(parts.length < 35) continue;
        const sym = parts[0].split('=')[0].replace('v_', '').trim();
        if(symbols.indexOf(sym) >= 0) out[sym] = parts;
      }
    } catch(e) { /* 跳过该批 */ }
    await new Promise(res => setTimeout(res, 120));
  }
  return out;
}
async function isTradingDay(){
  // 用权重指数实时行情探测: 行情时间戳为今日 且 vol>0 命中>=2 -> 是交易日
  try {
    const q = await fetchQuotes(['sh000001', 'sh600519', 'sz000001', 'sz399001']);
    const today = new Date();
    const ts = '' + today.getFullYear()
      + String(today.getMonth() + 1).padStart(2, '0')
      + String(today.getDate()).padStart(2, '0');
    let hit = 0;
    for(const k of Object.keys(q)){
      const p = q[k];
      const vol = parseFloat(p[6]) || 0;
      if(String(p[30]).startsWith(ts) && vol > 0) hit++;
    }
    return hit >= 2;
  } catch(e) { return false; }
}
function dstr(d){
  const y = d.getFullYear(), m = d.getMonth() + 1, dd = d.getDate();
  return y + '-' + String(m).padStart(2, '0') + '-' + String(dd).padStart(2, '0');
}
async function fetchLatestParallel(symbols, startStr, endStr, concurrency, onProgress){
  const results = {};
  let idx = 0, okCount = 0;
  const total = symbols.length;
  async function worker(){
    while(true){
      const i = idx++;
      if(i >= total) return;
      const sym = symbols[i];
      try {
        const arr = await fetchKline(sym, startStr, endStr);
        if(arr && arr.length) results[sym] = arr;
      } catch(e) { /* 单只失败跳过 */ }
      okCount++;
      if(onProgress && okCount % 500 === 0) onProgress(okCount, total);
    }
  }
  const n = Math.min(concurrency || 32, total);
  await Promise.all(Array.from({length: n}, worker));
  return results;
}

// ---------- 主流程: 增量刷新 ----------

// 处理周期窗口拉取结果与基线合并(与 html doRefresh 合并逻辑 1:1)
function mergeAndRecompute(ref, yk, strong, rows){
  // REPAIR_N: 每轮刷新对接口返回的最近 N 根 K 线做"逐根内容校验+修正", 用于覆盖
  // 盘中快照与历史污染日。取 8 (约 1.5 周), 足够修正相邻交易日污染(如 09-09/09-11),
  // 又不会把久远历史卷进复权口径差异的风险里。
  const REPAIR_N = 8;
  let added = 0, ykUpdated = 0, metaUpdated = 0, fixed = 0, ykFixed = 0;
  const dayMap = {};
  let maxDate = '';

  // ---- 第一遍: 把 K 线接口返回的新 bar 并入 ref(按日期去重, 不覆盖历史) ----
  Object.keys(rows).forEach(function(sym){
    const newBars = rows[sym];
    if(!ref[sym]) return;
    const refBars = ref[sym].d;
    const refDates = {};
    refBars.forEach(function(b){ refDates[b[0]] = 1; });
    const fresh = newBars.filter(function(b){ return !refDates[b[0]]; });
    if(fresh.length){
      ref[sym].d = refBars.concat(fresh).slice(-130);
      added += fresh.length;
    }
    // 逐根内容校验: 对接口返回的最近 REPAIR_N 根, 与 ref 同日期 bar 比对, 内容不同则覆盖。
    // 修正两类错误:
    //   1) 盘中快照 —— 腾讯K线镜像当日 bar 停在盘中某刻(open 正确 / close·low·vol 偏旧),
    //      旧版按日期去重"只追加不覆盖", 快照被永久固化(2026-09-04、09-09、09-11 事故);
    //   2) 历史污染日 —— 旧版自愈只覆盖"最后一根", 日期翻篇后该日再也不被修正。
    // 两条安全阀防误伤:
    //   · open 必须一致 —— 排除除权/复权口径变化(那会同时改动 open, 不是快照);
    //   · 成交量不得倒退 —— 成交量单调递增, 防"用快照覆盖 already 正确的收盘数据"。
    // 停牌股接口无当日 bar, 天然不参与。
    if(newBars.length){
      const arr = ref[sym].d;
      const pos = {};
      arr.forEach(function(b, i){ pos[b[0]] = i; });
      const tail = newBars.slice(-REPAIR_N);
      for(let k = 0; k < tail.length; k++){
        const nb = tail[k], i = pos[nb[0]];
        if(i === undefined) continue;
        const lb = arr[i];
        if(Math.abs(+nb[1] - +lb[1]) >= 0.011) continue;
        if(+nb[5] < +lb[5] - 0.5) continue;
        if(Math.abs(+nb[2] - +lb[2]) > 0.0005
           || Math.abs(+nb[4] - +lb[4]) > 0.0005
           || Math.abs(+nb[5] - +lb[5]) > 0.5){
          arr[i] = nb;
          fixed++;
        }
      }
    }
  });

  // ---- 第二遍: 用"真实最新一根 K 线"更新周/月收盘、YEAR_KLINE 与 ld ----
  // 关键: 必须用 ref[sym].d 的最后一根, 不能用 rows 返回的最后一根。
  // 腾讯 K 线接口每天漏同步几十只票(2026-09-03 漏 22 只), 这些票靠 fillTodayBar
  // 用实时行情补上当日 bar 后, ref 里已经是 09-03, 但 rows 里最后一根仍是 09-02。
  // 旧代码拿 rows 的 09-02 去更新, 后果有三:
  //   1. YEAR_KLINE 停在 09-02 → 涨幅榜的"当日涨跌幅"仍是 --(bars[iEnd][0]!==targetDate)
  //   2. 周/月收盘写的还是 09-02 的价 → 周线/月线判断用错价格
  //   3. ref[sym].ld 被写回 09-02 → 下次刷新又会误判为"日期已变"
  // 同时遍历 ref 全量而非只遍历 rows: 接口偶发失败的股票也能在下一次刷新时自愈。
  Object.keys(ref).forEach(function(sym){
    const o = ref[sym];
    if(!o.d.length) return;
    const lastBar = o.d[o.d.length - 1];
    const ld = lastBar[0], lc = +lastBar[2];
    const oldLd = o.ld;
    const wArr = o.w, mArr = o.m;

    // ---- YEAR_KLINE 同步(必须放在 oldLd===ld 短路之前) ----
    // 与 ref 最近 REPAIR_N 根逐日对齐: 日期已存在则校验 close, 不同即覆盖。
    // 这样即使日线末日未变(ld===oldLd), 也能把 year_kline 的当日收盘价从"盘中快照"
    // 修正为真实收盘价 —— 旧版只在"日期更晚"时才 push, 同日永不覆盖, 导致快照在
    // year_kline 里永久固化(涨跌停家数/温度分/涨跌幅榜全部读它, 2026-09-11 事故)。
    if(yk && yk[sym] && yk[sym].length){
      const ykArr = yk[sym];
      const ykPos = {};
      ykArr.forEach(function(b, i){ ykPos[b[0]] = i; });
      const tail = o.d.slice(-REPAIR_N);
      for(let k = 0; k < tail.length; k++){
        const bar = tail[k], i = ykPos[bar[0]];
        if(i === undefined) continue;
        const v = Math.round(+bar[2] * 100) / 100;
        if(Math.abs(+ykArr[i][1] - v) > 0.0005){ ykArr[i] = [bar[0], v]; ykFixed++; }
      }
      const ykLast = ykArr[ykArr.length - 1];
      if(ykLast && ykLast[0] < ld){
        ykArr.push([ld, Math.round(lc * 100) / 100]);
        ykUpdated++;
      }
    }

    // 基线没有 ld 记录时只登记, 不动周/月/年线 —— 否则 sameWeek 会判成 false 而
    // 往周线序列里重复 push 一根, 污染周线 MA5。
    if(!oldLd){ o.ld = ld; return; }
    if(oldLd === ld){
      // 末日未变, 但当日收盘价可能刚被快照自愈修正 —— 需同步回周/月线的最后一根
      // (最后一根对应当前所处周/月), 否则周月共振判断仍在用盘中快照价。
      if(wArr && wArr.length && wArr[wArr.length - 1] !== lc) wArr[wArr.length - 1] = lc;
      if(mArr && mArr.length && mArr[mArr.length - 1] !== lc) mArr[mArr.length - 1] = lc;
      return;                              // 无跨期变化, 其余保持幂等跳过
    }
    o.ld = ld;
    const sameWeek = oldLd && isoWeekKey(oldLd) === isoWeekKey(ld);
    const sameMonth = oldLd && oldLd.substring(0, 7) === ld.substring(0, 7);
    if(wArr && wArr.length){
      if(sameWeek) wArr[wArr.length - 1] = lc;
      else wArr.push(lc);
    }
    if(mArr && mArr.length){
      if(sameMonth) mArr[mArr.length - 1] = lc;
      else mArr.push(lc);
    }
  });

  // 重算全部股票, 得到最新交易日强势数据
  const objMap = {};
  Object.keys(ref).forEach(function(sym){
    const o = computeOne(sym, ref[sym].d, ref[sym].w, ref[sym].m);
    if(o){
      objMap[sym] = o;
      dayMap[sym] = o.r;
      if(o.date > maxDate) maxDate = o.date;
    }
  });

  // 第二遍: 只把"最新交易日确有 K 线"的股票写进 meta(收盘价 + 当日涨跌幅)。
  // 停牌或数据滞后的股票(o.date < maxDate)若沿用上一根 K 线的涨跌幅, 页面会
  // 把它当成最新交易日的涨跌幅展示 —— 例如 2026-09-03 生益科技的 meta 涨跌幅
  // 是 +0.39%, 实际那是 09-02 相对 09-01 的涨幅, 当日真实涨跌为 -1.23%,
  // 属静默误导。这里置 null, 让页面统一显示 "--"。
  Object.keys(objMap).forEach(function(sym){
    const o = objMap[sym];
    const mm = strong.meta[sym];
    if(!mm) return;
    mm[1] = Math.round(o.close * 100) / 100;
    mm[2] = (o.date === maxDate) ? o.r[14] : null;
    metaUpdated++;
  });

  // 更新 dates / strong / sum
  let changed = false;
  if(maxDate && maxDate !== strong.dates[strong.dates.length - 1]){
    strong.dates = strong.dates.filter(function(d){ return d <= maxDate; });
    if(!strong.dates.length || strong.dates[strong.dates.length - 1] !== maxDate)
      strong.dates.push(maxDate);
    changed = true;
  }
  strong.strong[maxDate] = dayMap;
  // sum 更新为最新日 (与生成脚本口径一致)
  if(maxDate){
    let nP = 0, nD = 0, n1 = 0;
    for(const s of Object.keys(dayMap)){
      const r = dayMap[s];
      if(r[15] >= 7 && (r[16] >= 6 || r[3] >= 50)) nP++;
      if(r[0] && r[1] && r[2]) nD++;
      if(r[0]) n1++;
    }
    strong.sum = strong.sum || {};
    strong.sum[maxDate] = [nP, nD, n1];
  }
  return {added, ykUpdated, metaUpdated, fixed, ykFixed, latestDate: maxDate, changed};
}

// 补当日 bar(镜像K线接口同步延迟): 对仍缺 target 日的股票用 qt 实时行情补齐
async function fillTodayBar(ref, target){
  const missing = [];
  Object.keys(ref).forEach(function(sym){
    const d = ref[sym].d;
    if(!d.length || d[d.length - 1][0] < target) missing.push(sym);
  });
  if(!missing.length) return 0;
  const qt = await fetchQuotes(missing);
  const tsPrefix = target.replace(/-/g, '');
  let appended = 0;
  for(const sym of missing){
    const parts = qt[sym];
    if(!parts) continue;
    try {
      const cur = parseFloat(parts[3]);
      const prevc = parseFloat(parts[4]);
      const opn = parseFloat(parts[5]);
      const vol = parseFloat(parts[6]);
      const high = parseFloat(parts[33]);
      const low = parseFloat(parts[34]);
      const ts = parts[30] || '';
      if(vol <= 0) continue;                       // 停牌/无成交
      if(!String(ts).startsWith(tsPrefix)) continue; // 时间戳非当日
      const lastClose = parseFloat(ref[sym].d[ref[sym].d.length - 1][2]);
      if(lastClose == null || Math.abs(prevc - lastClose) > 0.005) continue; // 昨收衔接异常
      ref[sym].d.push([target,
        String(Math.round(opn * 1000) / 1000),
        String(Math.round(cur * 1000) / 1000),
        String(Math.round(high * 1000) / 1000),
        String(Math.round(low * 1000) / 1000),
        String(Math.round(vol))]);
      appended++;
    } catch(e) { /* skip */ }
  }
  return appended;
}

// ---------- V2.1 买点区域 (compute_buydian_v21.py 1:1 移植, 随增量刷新实时重算) ----------
// 输入: ref[sym]={d:[[date,o,c,h,l,v],...], w:[周收盘...], m:[月收盘...]}
//       strong.strong[dt][sym]=r数组(门禁: r[15]>=7 && (r[16]>=6 || r[3]>=50)), strong.meta[sym][0]=名称
// 输出: 与离线 buydian_v21_data.js 同构 {dates, daily, sum, gen}
// 注意: 服务端 ref 只保留130根日K(离线Python用全量历史), 因此:
//   · 只重算窗口内指标齐全的日期(i>=124, 约2026-06起), 更早日期保留离线包内容;
//   · ma250 用现有窗口均值近似(离线用250根), 只影响 ts/buy_score ±10 的排序, 不影响 S/A/B 分级。
// 凡改这里, 必须同步根目录 compute_buydian_v21.py。
function bdMaPart(vals, n){
  const out = new Array(vals.length); let s = 0;
  for(let i = 0; i < vals.length; i++){
    s += vals[i];
    if(i >= n) s -= vals[i - n];
    out[i] = s / Math.min(i + 1, n);
  }
  return out;
}
function bdAtr14(h, l, c){
  const n = c.length, tr = new Array(n);
  for(let i = 0; i < n; i++)
    tr[i] = (i === 0) ? (h[i] - l[i])
      : Math.max(h[i] - l[i], Math.abs(h[i] - c[i-1]), Math.abs(l[i] - c[i-1]));
  const atr = new Array(n); let s = 0;
  for(let i = 0; i < n; i++){ s += tr[i]; if(i >= 14) s -= tr[i-14]; atr[i] = s / Math.min(i + 1, 14); }
  return atr;
}
function bdRsi14(c){
  const n = c.length, out = new Array(n).fill(null);
  if(n < 15) return out;
  let ag = 0, al = 0;
  for(let i = 1; i < 15; i++){ const ch = c[i] - c[i-1]; ag += Math.max(ch, 0); al += Math.max(-ch, 0); }
  ag /= 14; al /= 14;
  out[14] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  for(let i = 15; i < n; i++){
    const ch = c[i] - c[i-1];
    ag = (ag * 13 + Math.max(ch, 0)) / 14;
    al = (al * 13 + Math.max(-ch, 0)) / 14;
    out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
  }
  return out;
}
function bdNineCnt(c){
  const n = c.length, cnt = new Array(n).fill(0);
  for(let i = 4; i < n; i++){
    if(c[i] < c[i-4]) cnt[i] = cnt[i-1] > 0 ? cnt[i-1] + 1 : 1;
    else if(c[i] > c[i-4]) cnt[i] = cnt[i-1] < 0 ? cnt[i-1] - 1 : -1;
    else cnt[i] = 0;
  }
  return cnt;
}
function bdGoldenNeedle(o, c, h, l){
  const body = Math.abs(c - o), lower = Math.min(o, c) - l, rng = (h - l) || 0.01;
  if(c <= o) return false;
  return lower >= 2 * body && lower >= 0.5 * rng && lower / rng >= 0.45;
}
function bdStab(o, c, h, l){
  const body = Math.abs(c - o), lower = Math.min(o, c) - l,
        upper = h - Math.max(o, c), rng = (h - l) || 0.01;
  if(body <= 0.004 * c) return true;
  if(lower >= 2 * body && lower >= 0.4 * rng && upper <= 0.35 * rng) return true;
  if(c > o && lower >= 0.5 * rng) return true;
  return false;
}
const BD_LEVELS = [['M5',5],['M10',10],['M20',20],['M30',30],['M52',52],['M60',60]];
function bdWeekLabel(wc, idx, wma5A, wma10A, wma20A){
  const cv = wc[idx];
  function wmaAt(arr, i, nn){
    if(i + 1 < nn || i < 0) return null;
    let s = 0; for(let k = i - nn + 1; k <= i; k++) s += arr[k];
    return s / nn;
  }
  const devs = {
    M5:  wma5A[idx]  != null ? (cv / wma5A[idx]  - 1) * 100 : null,
    M10: wma10A[idx] != null ? (cv / wma10A[idx] - 1) * 100 : null,
    M20: wma20A[idx] != null ? (cv / wma20A[idx] - 1) * 100 : null,
    M30: (function(){ const m = wmaAt(wc, idx, 30); return m != null ? (cv / m - 1) * 100 : null; })(),
    M52: (function(){ const m = wmaAt(wc, idx, 52); return m != null ? (cv / m - 1) * 100 : null; })(),
    M60: (function(){ const m = wmaAt(wc, idx, 60); return m != null ? (cv / m - 1) * 100 : null; })()
  };
  const hits = [];
  BD_LEVELS.forEach(function(p){ const d = devs[p[0]]; if(d != null && Math.abs(d) <= 2) hits.push([p[0], d]); });
  if(hits.length){
    hits.sort(function(a, b){ return Math.abs(a[1]) - Math.abs(b[1]); });
    const nm = hits[0][0];
    return {lab: '回踩' + nm, cls: (nm === 'M52' || nm === 'M60') ? 'red' : 'blue'};
  }
  for(let ri = BD_LEVELS.length - 1; ri >= 0; ri--){
    const nm2 = BD_LEVELS[ri][0], d3 = devs[nm2];
    if(d3 != null && d3 < 0) return {lab: '跌破' + nm2, cls: 'down'};
  }
  const d10 = devs['M10'];
  if(d10 != null) return {lab: (d10 >= 0 ? '+' : '') + Math.round(d10) + '%', cls: 'flat'};
  return {lab: '—', cls: 'flat'};
}
const BD_RANK = {S: 0, A: 1, B: 2, C: 3};
function bd21ComputeAll(ref, strong, oldDaily){
  const t0 = Date.now();
  const meta = strong.meta || {};
  const strongMap = strong.strong || {};
  const daily = (oldDaily && typeof oldDaily === 'object') ? Object.assign({}, oldDaily) : {};
  Object.keys(ref).forEach(function(sym){
    const D = ref[sym].d;
    const n = D.length;
    if(n < 130) return;
    const o = new Array(n), c = new Array(n), h = new Array(n), l = new Array(n), v = new Array(n);
    for(let i = 0; i < n; i++){
      o[i] = +D[i][1]; c[i] = +D[i][2]; h[i] = +D[i][3]; l[i] = +D[i][4];
      v[i] = D[i].length > 5 ? +D[i][5] : 0;
    }
    const name = (meta[sym] || [])[0] || sym;
    const m5 = bdMaPart(c,5), m10 = bdMaPart(c,10), m20 = bdMaPart(c,20), m30 = bdMaPart(c,30),
          m60 = bdMaPart(c,60), m120 = bdMaPart(c,120);
    let s250 = 0; for(let k = 0; k < n; k++) s250 += c[k];
    const ma250approx = s250 / n;
    const atr = bdAtr14(h,l,c), rsi = bdRsi14(c);
    const vma5 = bdMaPart(v,5), vma20 = bdMaPart(v,20);
    const nine = bdNineCnt(c);
    // 周/月: 从 d 聚合近期(周键/月键+末日+收盘), 与 ref.w/ref.m 长历史尾部对齐
    const wkKey = [], wkEnd = [], wkClose = [], wkIdxOf = new Array(n);
    let curWk = null, wj = -1;
    for(let i = 0; i < n; i++){
      const wk = isoWeekKey(D[i][0]);
      if(wk !== curWk){ wkKey.push(wk); wkEnd.push(D[i][0]); wkClose.push(c[i]); curWk = wk; wj++; }
      else { wkEnd[wkEnd.length-1] = D[i][0]; wkClose[wkClose.length-1] = c[i]; }
      wkIdxOf[i] = wj;
    }
    const moKey = [], moEnd = [], moClose = [], moIdxOf = new Array(n);
    let curMo = null, mj = -1;
    for(let i = 0; i < n; i++){
      const mk = D[i][0].slice(0, 7);
      if(mk !== curMo){ moKey.push(mk); moEnd.push(D[i][0]); moClose.push(c[i]); curMo = mk; mj++; }
      else { moEnd[moEnd.length-1] = D[i][0]; moClose[moClose.length-1] = c[i]; }
      moIdxOf[i] = mj;
    }
    const wFull = ref[sym].w || [], mFull = ref[sym].m || [];
    let wArr, wOff, mArr, mOff;
    const K = wkClose.length, J = moClose.length;
    if(wFull.length >= K){
      let ok = true;
      for(let k2 = 0; k2 < K; k2++)
        if(Math.abs(wFull[wFull.length - K + k2] - wkClose[k2]) > 0.011){ ok = false; break; }
      if(ok){ wArr = wFull; wOff = wFull.length - K; } else { wArr = wkClose; wOff = 0; }
    } else { wArr = wkClose; wOff = 0; }
    if(mFull.length >= J){
      let ok2 = true;
      for(let k3 = 0; k3 < J; k3++)
        if(Math.abs(mFull[mFull.length - J + k3] - moClose[k3]) > 0.011){ ok2 = false; break; }
      if(ok2){ mArr = mFull; mOff = mFull.length - J; } else { mArr = moClose; mOff = 0; }
    } else { mArr = moClose; mOff = 0; }
    const wma5A = bdMaPart(wArr,5), wma10A = bdMaPart(wArr,10), wma20A = bdMaPart(wArr,20);
    const mma5A = bdMaPart(mArr,5), mma10A = bdMaPart(mArr,10);
    for(let i = 124; i < n; i++){
      const dt = D[i][0];
      if(dt < '2026-01-01') continue;
      const pool = strongMap[dt];
      if(!pool || !pool[sym]) continue;
      const pr = pool[sym];
      if(!(pr[15] >= 7 && (pr[16] >= 6 || pr[3] >= 50))) continue;
      const cv = c[i];
      const a5 = m5[i], a10 = m10[i], a20 = m20[i], a60 = m60[i], a120 = m120[i];
      const atrV = atr[i];
      if(!(atrV > 0)) continue;
      // 趋势分
      let ts = 0;
      if(a5 > a10) ts += 10;
      if(a10 > a20) ts += 10;
      if(a20 > a60) ts += 15;
      if(a60 > a120) ts += 15;
      if(i >= 5 && m60[i] > m60[i-5]) ts += 10;
      if(i >= 5 && m120[i] > m120[i-5]) ts += 10;
      // 与 Python bisect_right(wdates, dt)-1 同语义: 周中日期取上一个"完整"周期,
      // 只有当 dt 恰为本周期最后一天(末日)时才指向本周期
      const wi2 = wkIdxOf[i];
      const widx = wOff + ((wkEnd[wi2] <= dt) ? wi2 : wi2 - 1);
      const mi2 = moIdxOf[i];
      const midx = mOff + ((moEnd[mi2] <= dt) ? mi2 : mi2 - 1);
      const weekMa10Up = (widx >= 4) && (wma10A[widx] > wma10A[widx-4]);
      if(weekMa10Up) ts += 10;
      const monthBull = (midx >= 0) && (mma5A[midx] > mma10A[midx]);
      if(monthBull) ts += 10;
      if(cv > ma250approx) ts += 10;
      const bull_align = (a5 > a10 && a10 > a20 && a20 > a60 && a60 > a120)
        && (i >= 5 && m20[i] > m20[i-5]) && (m60[i] > m60[i-5]);
      const osc_up = (a20 > a60 && a60 > a120) && (i >= 5 && m60[i] > m60[i-5]) && (m120[i] >= m120[i-5]);
      const align = bull_align ? 'bull' : (osc_up ? 'osc' : 'none');
      const wm5 = wma5A[widx], wm10 = wma10A[widx], wm20 = wma20A[widx], wcc = wArr[widx];
      const week_strong = (widx >= 0) && (wm5 > wm10 && wm10 > wm20) && (wcc > wm20);
      const day_strong = (a20 > a60 && a60 > a120) && (i >= 5 && m60[i] > m60[i-5]) && (m120[i] >= m120[i-5]);
      if(!(day_strong && week_strong && monthBull)) continue;
      const dist60 = Math.abs(cv - a60) / atrV;
      const ma60_pullback = dist60 <= 1.0 && cv >= a60 * 0.98;
      const primary = ma60_pullback ? 'MA60' : null;
      const shrink = vma5[i] < vma20[i] * 0.8;
      let ma_up = false;
      if(primary) ma_up = (i >= 5) && (m60[i] >= m60[i-5]);
      const stable = bdStab(o[i], cv, h[i], l[i]);
      const breakout = (i >= 1) && (cv > h[i-1]) && (v[i] >= vma5[i] * 1.0);
      const trig_cnt = (shrink ? 1 : 0) + (ma_up ? 1 : 0) + (stable ? 1 : 0);
      const trigger_ok = trig_cnt >= 2;
      const low9 = nine[i] >= 9, low8 = nine[i] === 8;
      const wst = (widx >= 0) ? bdWeekLabel(wArr, widx, wma5A, wma10A, wma20A) : null;
      const week_hit = (wst && (wst.cls === 'red' || wst.cls === 'blue')) ? wst.lab : null;
      const resonate = (primary !== null) && (week_hit !== null);
      let segLow = Infinity;
      for(let k4 = Math.max(0, i - 19); k4 <= i; k4++) if(l[k4] < segLow) segLow = l[k4];
      const stop = segLow;
      let hi60 = -Infinity;
      for(let k5 = Math.max(0, i - 59); k5 <= i; k5++) if(h[k5] > hi60) hi60 = h[k5];
      const risk = cv - stop;
      const rr = risk > 0 ? (hi60 - cv) / risk : null;
      let bs = 0;
      if(ts >= 90) bs += 10; else if(ts >= 80) bs += 5;
      if(shrink) bs += 10;
      if(ma_up) bs += 10;
      if(stable) bs += 15;
      if(breakout) bs += 10;
      const sig_red9 = nine[i] >= 9;
      const sig_needle = bdGoldenNeedle(o[i], cv, h[i], l[i]);
      let engulf = false;
      if(i >= 1 && c[i] > o[i] && c[i-1] < o[i-1])
        engulf = (c[i] >= Math.max(o[i-1], c[i-1])) && (o[i] <= Math.min(o[i-1], c[i-1]));
      let reclaim = false;
      if(i >= 1 && c[i] > o[i] && c[i-1] < o[i-1] && c[i] > a10 && c[i-1] <= a10
         && vma5[i] > 0 && v[i] >= vma5[i]) reclaim = true;
      const turn = engulf || reclaim;
      if(turn) bs += 10;
      const red9_stabilized = sig_red9 && (stable || cv > o[i]) && shrink;
      const red9_partial = sig_red9 && (turn || stable || cv > o[i] || shrink);
      const needle_confirmed = sig_needle && (shrink || trig_cnt >= 2);
      let level = null;
      if(ma60_pullback && trigger_ok) level = (resonate && shrink) ? 'S' : 'A';
      else if(ma60_pullback) level = (turn && shrink) ? 'A' : 'B';
      else if(red9_stabilized) level = 'S';
      else if(red9_partial) level = 'A';
      else if(sig_red9) level = 'B';
      else if(needle_confirmed) level = 'S';
      else if(sig_needle) level = 'A';
      else if(rsi[i] != null && rsi[i] < 30) level = 'C';
      const chg = i >= 1 ? (cv / c[i-1] - 1) * 100 : 0;
      if(chg <= -5 && cv < o[i]) level = null;
      daily[dt] = daily[dt] || [];
      daily[dt].push({
        c: sym, n: name, close: Math.round(cv * 100) / 100,
        trend_score: Math.round(ts), align: align, primary_ma: primary,
        pullback_dist: primary ? Math.round(dist60 * 100) / 100 : null,
        shrink: shrink, ma_up: ma_up, stable: stable,
        breakout: breakout, trigger_ok: trigger_ok, trig_cnt: trig_cnt,
        low9: low9, low8: low8, red9: sig_red9,
        golden_needle: sig_needle, week_hit: week_hit,
        engulf: engulf, reclaim: reclaim, turn: turn,
        resonate: resonate, buy_score: bs, level: level,
        stop: Math.round(stop * 100) / 100, resistance: Math.round(hi60 * 100) / 100,
        rr: rr != null ? Math.round(rr * 100) / 100 : null,
        rsi14: rsi[i] != null ? Math.round(rsi[i] * 10) / 10 : null,
        dev60: Math.round((cv / a60 - 1) * 1000) / 10
      });
    }
  });
  // 排序: S > A > B > C, 同级按 buy_score 降序; 统计 sum
  const sum = {};
  Object.keys(daily).forEach(function(dt){
    daily[dt].sort(function(a, b){
      const ra = BD_RANK[a.level] != null ? BD_RANK[a.level] : 9;
      const rb = BD_RANK[b.level] != null ? BD_RANK[b.level] : 9;
      return ra - rb || b.buy_score - a.buy_score;
    });
    const cnt = {S: 0, A: 0, B: 0, C: 0};
    daily[dt].forEach(function(r){ if(cnt[r.level] != null) cnt[r.level]++; });
    sum[dt] = cnt;
  });
  const dates = Object.keys(daily).sort();
  return {dates: dates, daily: daily, sum: sum, tookMs: Date.now() - t0};
}

/**
 * 统计滞后股: 最后一根日K日期 < latest 的股票(含停牌/接口漏同步)。
 * 供 server.js 智能校验区分"停牌(可缓存)"与"漏同步(需继续补拉)"。
 */
function lagSyms(ref, latest){
  const lag = [];
  Object.keys(ref).forEach(function(sym){
    const d = ref[sym] && ref[sym].d;
    if(!d || !d.length || d[d.length - 1][0] < latest) lag.push(sym);
  });
  return lag;
}

/**
 * 增量刷新到最新
 * @param dir 部署目录(含 strong_data.js / year_kline.js / kline_ref.js / gain_board.js / buydian_v21_data.js)
 * @param opts {limit?:number 只处理前N只(测试用), dry?:boolean 只算不写盘}
 * @returns {Promise<{ok, latest, added, filled, pool, changed, took, bd21?, lag?}>}
 */
async function refreshAll(dir, opts){
  opts = opts || {};
  const t0 = Date.now();
  const strong = readData(dir, 'strong_data');
  const yk = readData(dir, 'year_kline');
  const ref = readData(dir, 'kline_ref');
  const gb = readData(dir, 'gain_board');

  let symbols = Object.keys(ref);
  if(opts.limit && opts.limit > 0) symbols = symbols.slice(0, opts.limit);
  if(!symbols.length) return {ok: false, error: 'kline_ref 为空'};

  const now = new Date();
  const endStr = dstr(now);
  const start = new Date(now.getTime() - 45 * 86400000);
  const startStr = dstr(start);

  // 非交易日(收盘后/周末)无新数据: 仍尝试拉一次以合并接口已同步的当日bar(如周五晚补周五)
  const trading = await isTradingDay();
  const rows = await fetchLatestParallel(symbols, startStr, endStr, 32);
  if(!Object.keys(rows).length)
    return {ok: false, error: '腾讯行情拉取为空(网络/限流), 未做任何修改', took: Date.now() - t0};

  // 计算到达目标日覆盖率: 目标日=今天(若今天有bar)否则行内最大日期
  let reached = 0;
  Object.keys(rows).forEach(function(sym){
    const arr = rows[sym];
    if(arr.length && arr[arr.length - 1][0] >= endStr) reached++;
  });
  const cover = reached / Math.max(1, Object.keys(rows).length);
  let filled = 0;
  // 补当日 bar 的前提: 今天是交易日。
  // 注意: 这里**不能**再加"整体覆盖率不足"(旧版 cover<0.85)或"基线日期 < 今天"
  // (旧版 baseLast < endStr)两个开关, 两个都会让补 bar 永久失效:
  //   · 覆盖率开关: 腾讯 K 线接口每天都会漏同步几十只票(2026-09-03 漏了 22 只:
  //     生益科技/行云科技/工业富联/新易盛/天孚通信等), 此时全市场覆盖率高达
  //     98.6%, 阈值不触发, 整批补 bar 被跳过, 这些票永远停在上一交易日;
  //   · 基线日期开关: 只要 dates 已推进到今天(哪怕只有一部分票到齐), 之后无论
  //     刷新多少次 baseLast < endStr 都不成立, 漏掉的票再也补不回来。
  // fillTodayBar 内部自己算 missing 列表, 且有三重校验(vol<=0 停牌 /
  // 时间戳非当日 / 昨收衔接异常), 停牌股会被自然跳过, 无需外层兜底。
  if(trading){
    filled = await fillTodayBar(ref, endStr);
  }
  const res = mergeAndRecompute(ref, yk, strong, rows);
  const nP = (strong.sum && strong.sum[res.latestDate]) ? strong.sum[res.latestDate][0] : 0;

  // ykUpdated / ykFixed / fixed 也要算进"有无变化": 存在"日线已到位、但 YEAR_KLINE
  // 还停在上一日或仍是盘中快照"的修复型刷新(added=filled=changed=0), 若不看这些修正
  // 计数就会提前返回不写盘, 涨幅榜/涨跌停家数永远补不回来; 同理 ref 的 fixed 快照
  // 修正也必须写盘。
  if(!res.added && !filled && !res.changed && !res.ykUpdated && !res.fixed && !res.ykFixed){
    return {ok: true, latest: res.latestDate, added: 0, filled, pool: nP,
            changed: false, fixed: res.fixed, ykFixed: res.ykFixed, ykUpdated: res.ykUpdated,
            lag: lagSyms(ref, res.latestDate),
            message: '无新增交易日, 数据已是最新', took: Date.now() - t0};
  }
  // V2.1 买点区域: 随增量刷新实时重算(与离线 compute_buydian_v21.py 同构),
  // 与旧包按日期合并 —— 服务端窗口只覆盖近期日期, 更早的历史日期保留离线结果。
  // 放在早退判断之后: 无变化时不动包(避免无谓的 ETag 变化触发全量重下)。
  let bd21 = null;
  try {
    const oldBd = readData(dir, 'buydian_v21_data');
    const built = bd21ComputeAll(ref, strong, (oldBd && oldBd.daily) || {});
    if(!opts.dry)
      writeJsGz(dir, 'buydian_v21_data',
        {dates: built.dates, daily: built.daily, sum: built.sum, gen: 'auto-' + dstr(new Date())},
        'window.BD21_DATA = ');
    const lastDt = built.dates[built.dates.length - 1] || '';
    bd21 = {dates: built.dates.length, latest: lastDt,
            levels: lastDt ? built.sum[lastDt] : null, tookMs: built.tookMs};
  } catch(e) {
    bd21 = {error: String(e && e.message || e)};   // 买点重算失败不阻塞主刷新
  }
  if(!opts.dry){
    // 写回(顺带更新 gain_board.date 显示用字段)
    gb.date = res.latestDate;
    // strong_data 的 gen 也必须跟着更新: 离线脚本(update_all.sh/update_strong.py)会写
    // 'auto-<当天>', 服务端原先只写数据不动 gen, 导致页面「数据包生成于」永远停在最后一次
    // 离线全量的日期(线上长期显示 auto-2026-09-05), 而 dates 其实每天都在推进
    // → 用户误以为数据没有实时更新(2026-09-11 反馈)。与 BD21 包(上方)写法保持一致。
    strong.gen = 'auto-' + dstr(new Date());
    writeJsGz(dir, 'strong_data', strong);
    writeJsGz(dir, 'year_kline', yk);
    writeJsGz(dir, 'kline_ref', ref);
    writeJsGz(dir, 'gain_board', gb);
  }
  return {ok: true, latest: res.latestDate, added: res.added + filled, filled,
          pool: nP, changed: true, dry: !!opts.dry,
          fixed: res.fixed, ykFixed: res.ykFixed, ykUpdated: res.ykUpdated,
          lag: lagSyms(ref, res.latestDate),
          cover: Math.round(cover * 1000) / 10, took: Date.now() - t0, bd21: bd21};
}

module.exports = { refreshAll, computeOne, smaAt, isoWeekKey, scorePullback, parseJs, readData, writeJsGz, bd21ComputeAll, lagSyms };
