// =============================================================
// server.js — 多周期强势股选股器 线上服务
// -------------------------------------------------------------
// 1) 伺服部署目录的全部静态文件(页面优先加载 .gz, 由浏览器解压)
// 2) /api/refresh  增量刷新数据到最新交易日(有历史复用、缺失补拉),
//    完成后原子写回 .js/.gz, 全站访问者立即可见 —— 无需每天重新发布
// 3) /api/health   健康/数据状态探测(供每日任务判断是否需要刷新)
// 零第三方依赖, 直接: node server.js  (PORT 由平台注入)
// =============================================================
'use strict';
const http = require('http');
const path = require('path');
const fs = require('fs');
const { refreshAll } = require('./refresh_core.js');

const ROOT = process.env.ROOT_DIR ? path.resolve(process.env.ROOT_DIR) : __dirname;
const PORT = process.env.PORT || 3000;
const COOLDOWN_MS = 60 * 1000;        // 两次真实刷新最小间隔(防滥用/防腾讯限流)
const STATE_FILE = path.join(ROOT, 'refresh_state.json');  // 上轮刷新后的滞后股快照(区分停牌/漏同步)

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.gz': 'application/gzip',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.css': 'text/css; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.map': 'application/json'
};

// ---- 刷新状态 ----
let lastRunAt = 0;        // 上一次真实执行完成时间
let running = false;
let lastResult = null;    // 冷却期内直接返回最近一次结果

// ---- 智能校验: 决定"真拉取"还是"校验通过走缓存" ----
// 背景: 腾讯K线接口每天会漏同步少量票, 且盘中/收盘后的重复点击没有必要每次都全量拉取;
//       更关键的是镜像在当日同步完成前会把"盘中快照"当当日 bar 返回, 必须在收盘后核对一次。
// 规则(用户确认):
//   · 盘中(工作日 09:25–15:05) → 每次都真刷新(价格在变动, 用户要求每次进入都拿最新);
//   · 非交易时段: 数据落后于"应收交易日" → 真刷新补齐;
//   · 非交易时段: 最新交易日尚未在"当日收盘后(15:05起)"真刷核对过 → 真刷新一次,
//     把可能被固化的盘中快照修正为真实收盘价(2026-09-11 涨跌停家数错误的根因);
//   · 以上都满足(已收盘后核对 + 无新增滞后股, 或滞后股与上轮完全相同=停牌股) → 走缓存, 秒回。
function readState(){
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch(e){ return null; }
}

function shNow(){
  // 北京时间当前 → {date:'YYYY-MM-DD', hhmm: 930 表示 09:30, wd: 0=日 1=一 ... 6=六}
  const d = new Date();
  const p = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false})
    .formatToParts(d);
  const get = function(t){ const x = p.find(function(q){ return q.type === t; }); return x ? x.value : ''; };
  let hour = get('hour'); if(hour === '24') hour = '00';
  const wdStr = new Intl.DateTimeFormat('en-US', {timeZone: 'Asia/Shanghai', weekday: 'short'}).format(d);
  const wdMap = {Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6};
  return {date: get('year') + '-' + get('month') + '-' + get('day'),
          hhmm: parseInt(hour + get('minute'), 10), wd: wdMap[wdStr]};
}

function prevWeekday(dateStr, wd){
  // 回退到上一个工作日(跳过周六日; 不含节假日判断, 节假日多花一次拉取, 无副作用)
  const dt = new Date(dateStr + 'T00:00:00Z');
  let n = wd;
  do { dt.setUTCDate(dt.getUTCDate() - 1); n = (n - 1 < 0) ? 6 : n - 1; } while(n === 0 || n === 6);
  return {date: dt.toISOString().slice(0, 10), wd: n};
}

function expectedLatest(t){
  // 此刻"应已收盘"的最新交易日
  if(t.wd === 0 || t.wd === 6) return prevWeekday(t.date, t.wd).date;
  if(t.hhmm >= 930) return t.date;          // 盘中/收盘后: 期望今天(节假日靠拉取空跑兜底)
  return prevWeekday(t.date, t.wd).date;    // 开盘前: 期望上一工作日
}

function sameSet(a, b){
  if(!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
  const s = a.slice().sort().join(',');
  return b.slice().sort().join(',') === s;
}

function precheck(){
  // 只解析 kline_ref(最关键、最大): latest=全市场最新bar日, lag=落后于latest的股票
  const { readData } = require('./refresh_core.js');
  const ref = readData(ROOT, 'kline_ref');
  let latest = '';
  const syms = Object.keys(ref);
  syms.forEach(function(sym){
    const d = ref[sym] && ref[sym].d;
    if(d && d.length && d[d.length - 1][0] > latest) latest = d[d.length - 1][0];
  });
  const { lagSyms } = require('./refresh_core.js');
  return {latest: latest, lag: latest ? lagSyms(ref, latest) : syms};
}

function postCloseVerified(latest){
  // 最新交易日 latest 的数据是否已在"当日收盘后"被真刷覆盖过 —— 这是排除盘中快照的判据。
  // 背景: 腾讯K线镜像在当日同步完成前会把"盘中快照"当作当日 bar 返回, 一旦落盘会被永久
  // 固化(旧版按日期去重 + year_kline 只追加), 涨跌停家数/温度分/涨幅榜全按盘中价计算
  // (2026-09-04、09-09、09-11 事故)。收盘后(15:05起)至少真刷一次才能把快照修正为真实收盘价。
  const st = readState();
  if(!st || !st.realRunDate) return false;                              // 无记录 = 尚未核对
  if(st.realRunDate > latest) return true;                              // 真刷发生在最新交易日之后
  if(st.realRunDate === latest && st.realRunHhmm >= 1505) return true;  // 当日收盘后刷过
  return false;
}

function smartSkip(){
  // 返回 null=需要真刷新; 否则返回可缓存的响应对象
  const pc = precheck();
  if(!pc.latest) return null;
  const t = shNow();
  const inSession = (t.wd >= 1 && t.wd <= 5 && t.hhmm >= 925 && t.hhmm <= 1505);
  if(inSession) return null;                       // 盘中: 总是刷新(价格在变, 每次进入都要最新)
  if(pc.latest < expectedLatest(t)) return null;   // 落后应收交易日: 必须补
  // 已到最新交易日, 但仍可能停留在"盘中快照"(收盘前抓取被固化) -> 必须先真刷一次核对收盘价,
  // 核对过之后才允许走缓存秒回。这是"每次进页面都能拿到正确收盘数据"的关键一步。
  if(!postCloseVerified(pc.latest)) return null;
  if(pc.lag.length === 0){
    return {ok: true, latest: pc.latest, cached: true, changed: false, added: 0,
            lag: 0, checked: true,
            message: '✅ 完整性校验通过（全部股票已到 ' + pc.latest + '），非交易时段直接使用缓存，无需重新拉取'};
  }
  // 有滞后股: 与上一轮完整刷新后的快照比对 —— 完全相同即停牌股(上轮已尝试补拉), 视为完整
  const st = readState();
  if(st && st.latest === pc.latest && sameSet(st.lag, pc.lag)){
    return {ok: true, latest: pc.latest, cached: true, changed: false, added: 0,
            lag: pc.lag.length, checked: true,
            message: '✅ 完整性校验通过（最新 ' + pc.latest + '，' + pc.lag.length + ' 只停牌股无数据属正常），已使用缓存'};
  }
  return null;                                     // 存在新增滞后股: 继续刷新补齐
}

function sendJson(res, code, obj){
  const body = JSON.stringify(obj);
  res.writeHead(code, {'Content-Type': 'application/json; charset=utf-8',
                       'Cache-Control': 'no-store'});
  res.end(body);
}

async function handleRefresh(req, res){
  if(running){
    return sendJson(res, 200, {ok: false, running: true, message: '刷新正在进行中, 请稍候…'});
  }
  const url = new URL(req.url, 'http://x');
  const limit = parseInt(url.searchParams.get('limit') || '0', 10) || 0;
  const dry = url.searchParams.get('dry') === '1';
  const force = url.searchParams.get('force') === '1';
  // 智能校验在最前(缓存命中不受冷却限制, 秒回); force=1 可强制跳过校验直接拉取
  if(!force && !dry){
    try {
      const cached = smartSkip();
      if(cached) return sendJson(res, 200, cached);
    } catch(e){ /* 校验异常则照常走真刷新 */ }
  }
  const now = Date.now();
  if(now - lastRunAt < COOLDOWN_MS && lastResult){
    lastResult.cooldown = Math.round((COOLDOWN_MS - (now - lastRunAt)) / 1000);
    return sendJson(res, 200, lastResult);
  }
  running = true;
  try {
    const r = await refreshAll(ROOT, {limit: limit > 0 ? limit : 0, dry});
    lastResult = r;
    if(!dry){
      lastRunAt = Date.now();
      // 记录本轮刷新后的滞后股快照: 下次校验时"同一批滞后股"=停牌股(可缓存), "新增滞后股"=漏同步(需补拉)
      if(r && r.ok){
        const rt = shNow();
        try { fs.writeFileSync(STATE_FILE, JSON.stringify({
          ts: Date.now(), latest: r.latest, lag: r.lag || [],
          realRunDate: rt.date, realRunHhmm: rt.hhmm
        })); }
        catch(e){ /* 状态写失败只影响缓存判断, 不影响刷新结果 */ }
      }
    }
    sendJson(res, 200, r);
  } catch(e){
    lastResult = {ok: false, error: String(e && e.message || e)};
    sendJson(res, 500, lastResult);
  } finally {
    running = false;
  }
}

function handleHealth(req, res){
  try {
    const { parseJs, readData } = require('./refresh_core.js');
    const sd = readData(ROOT, 'strong_data');
    const dates = sd.dates || [];
    const last = dates[dates.length - 1];
    const sum = (sd.sum && sd.sum[last]) || [0, 0, 0];
    // dataMtime: strong_data.js.gz 的文件指纹(mtime+size)。页面可拿它与自己加载的
    // 包比对, 判断"浏览器里的数据是否落后于服务端", 避免只靠日期判断漏掉
    // "同一天但内容被修复过"的情况(如盘中快照被自愈覆盖)。
    let dataMtime = 0;
    try {
      const p = path.join(ROOT, 'strong_data.js.gz');
      const st = fs.statSync(p);
      dataMtime = Math.floor(st.mtimeMs) + ':' + st.size;
    } catch(e) { /* 缺失时给 0, 前端忽略 */ }
    sendJson(res, 200, {
      ok: true, latest: last, days: dates.length,
      poolRuleD: sum[0], poolDwm: sum[1], gen: sd.gen || '',
      dataMtime: dataMtime
    });
  } catch(e){
    sendJson(res, 500, {ok: false, error: String(e && e.message || e)});
  }
}

function serveStatic(req, res){
  let urlPath;
  try { urlPath = decodeURIComponent(new URL(req.url, 'http://x').pathname); }
  catch(e){ return sendJson(res, 400, {ok:false, error:'bad url'}); }
  if(urlPath === '/') urlPath = '/strong_screener.html';
  if(urlPath === '/api/refresh') return handleRefresh(req, res);
  if(urlPath === '/api/health') return handleHealth(req, res);
  if(urlPath.startsWith('/api/')) return sendJson(res, 404, {ok:false, error:'unknown api'});

  const filePath = path.normalize(path.join(ROOT, urlPath));
  if(filePath !== ROOT && !filePath.startsWith(ROOT + path.sep)){
    return sendJson(res, 403, {ok:false, error:'forbidden'});
  }
  fs.stat(filePath, function(err, st){
    if(err || !st.isFile()){
      res.writeHead(404, {'Content-Type': 'text/plain; charset=utf-8'});
      return res.end('404 Not Found: ' + urlPath);
    }
    const ext = path.extname(filePath).toLowerCase();
    const type = MIME[ext] || 'application/octet-stream';
    // 数据文件(.js/.gz)与页面必须走协商缓存: 每次请求都校验新鲜度, 未变更返回304。
    // 旧版给 .js/.gz 设了 `public, max-age=300`, 浏览器会在 5 分钟内直接复用本地旧包,
    // /api/refresh 写完盘后页面重载仍读到旧数据 —— 表现就是"点了刷新却没变化"。
    // 改为 no-cache + ETag(写盘用原子 rename, mtime/size 变化 => ETag 变化 => 必拉新包),
    // 同时保留 304 协商, 18MB 的包未变更时不会重复传输。
    const isData = (ext === '.js' || ext === '.gz' || ext === '.html' || ext === '.json');
    const etag = '"' + st.size.toString(36) + '-' + Math.floor(st.mtimeMs).toString(36) + '"';
    if(isData){
      if(req.headers['if-none-match'] === etag){
        res.writeHead(304, {'Cache-Control': 'no-cache', 'ETag': etag});
        return res.end();
      }
      res.writeHead(200, {
        'Content-Type': type,
        'Content-Length': st.size,
        'Cache-Control': 'no-cache',
        'ETag': etag
      });
    } else {
      res.writeHead(200, {
        'Content-Type': type,
        'Content-Length': st.size,
        'Cache-Control': 'public, max-age=300'
      });
    }
    fs.createReadStream(filePath).pipe(res);
  });
}

const server = http.createServer(serveStatic);
if(require.main === module){
  server.listen(PORT, '0.0.0.0', function(){
    console.log('[server] 多周期强势股选股器服务已启动, 端口', PORT, 'root', ROOT);
  });
  server.on('error', function(e){
    console.error('[server] 启动失败:', e.message);
    process.exit(1);
  });
}

module.exports = { shNow, expectedLatest, smartSkip, precheck, postCloseVerified };
