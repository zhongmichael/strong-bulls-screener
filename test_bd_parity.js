// 对拍: 页面 JS 冰点策略函数 vs Python 回测逐笔记录
// 用法: node test_bd_parity.js
const fs = require('fs');
const vm = require('vm');
const ROOT = '/Users/michael/Documents/golden-system/td9-screener';

const html = fs.readFileSync(ROOT + '/strong_screener.html', 'utf8');
function extractFn(name){
  const i = html.indexOf('function ' + name + '(');
  if(i < 0) throw new Error('fn not found: ' + name);
  let d = 0, started = false;
  for(let k = html.indexOf('{', i); k < html.length; k++){
    if(html[k] === '{'){ d++; started = true; }
    else if(html[k] === '}'){ d--; if(started && !d) return html.slice(i, k+1); }
  }
  throw new Error('brace mismatch: ' + name);
}
const sandbox = { window: {}, console };
vm.createContext(sandbox);
vm.runInContext(extractFn('ztLimit') + '\n' + extractFn('symCodeG'), sandbox);
// 冰点策略整块(到 bingdianCardHtml 为止, 其余页面函数不需要)
const blockStart = html.indexOf('// ===== 冰点策略');
const blockEnd = html.indexOf('function bingdianCardHtml');
if(blockStart < 0 || blockEnd < 0) throw new Error('block not found');
vm.runInContext(html.slice(blockStart, blockEnd), sandbox);

// 加载数据包(与线上一致)
vm.runInContext(fs.readFileSync(ROOT + '/dist_strong/strong_data.js', 'utf8'), sandbox);
vm.runInContext(fs.readFileSync(ROOT + '/dist_strong/year_kline.js', 'utf8'), sandbox);

const jsPicks = {};
['2026-09-04', '2026-09-03', '2026-07-07', '2026-03-04', '2026-02-13', '2025-12-16'].forEach(function(dt){
  const sc = sandbox.bdScan(dt);
  if(!sc){ console.log(dt, 'scan null'); return; }
  ['S11', 'S11b', 'S5', 'S1', 'S9d', 'S10c'].forEach(function(code){
    jsPicks[code + '|' + dt] = sandbox.bdPick(code, sc).map(function(r){ return r.code; });
  });
});

const pySets = {};
function loadTrades(file){
  const j = JSON.parse(fs.readFileSync(ROOT + '/' + file, 'utf8'));
  Object.keys(j.trades).forEach(function(code){
    j.trades[code].forEach(function(tr){
      const k = code + '|' + tr.date;
      if(!pySets[k]) pySets[k] = [];                 // 三个json重复含S1~S5, 只保留首份
      if(pySets[k].indexOf(tr.code) < 0) pySets[k].push(tr.code);
    });
  });
}
loadTrades('backtest_s11_data.json');
loadTrades('backtest_s9_data.json');
loadTrades('backtest_s10_data.json');

let match = 0, total = 0, diffs = [];
Object.keys(jsPicks).forEach(function(k){
  const py = pySets[k] || null;
  if(!py) return;                                 // 该日非冰点触发日
  total++;
  const js = jsPicks[k];
  // Python trades 剔除了停牌无报价的票, JS 列表应为其超集且相对顺序一致(子序列匹配)
  let pi = 0, ok = true;
  for(let i = 0; i < js.length && pi < py.length; i++){
    if(js[i] === py[pi]) pi++;
  }
  if(pi !== py.length) ok = false;
  const extras = js.filter(function(c){ return py.indexOf(c) < 0; });
  if(ok){ match++; } else { diffs.push({k:k, js:js, py:py}); }
  console.log((ok ? 'OK  ' : 'DIFF') + ' ' + k + '  js=' + js.length + ' py=' + py.length + (extras.length ? '  js独有(疑似停牌): ' + extras.join(',') : ''));
});
console.log('\n匹配 ' + match + '/' + total);
if(diffs.length){
  diffs.forEach(function(d){
    console.log('\n=== ' + d.k + '\njs: ' + d.js.join(',') + '\npy: ' + d.py.join(','));
  });
  process.exit(1);
}
