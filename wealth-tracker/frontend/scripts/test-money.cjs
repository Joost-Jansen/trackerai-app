const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(file) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '..', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const mod = { exports: {} };
  // An import from the app itself ("./month-periods", "@/lib/api") loads that .ts
  // file in the same way; the rest goes to node.
  const local = (base) => (fs.existsSync(path.join(__dirname, '..', `${base}.ts`)) ? `${base}.ts` : `${base}/index.ts`);
  const req = (id) =>
    id.startsWith('./') ? load(local(path.join(path.dirname(file), id)))
      : id.startsWith('@/') ? load(local(id.slice(2)))
        : require(id);
  new Function('module', 'exports', 'require', code)(mod, mod.exports, req);
  return mod.exports;
}
const { periodWindow, moveWindow, sampleBalances, dayNumber, windowWithBase } = load('lib/timeline.ts');
assert.deepEqual(periodWindow('1M','2020-01-01','2024-03-31'),{from:'2024-03-01',to:'2024-03-31'});
assert.deepEqual(periodWindow('1Y','2020-01-01','2024-02-29'),{from:'2023-03-01',to:'2024-02-29'});
assert.deepEqual(periodWindow('YTD','2026-03-15','2026-09-13'),{from:'2026-03-15',to:'2026-09-13'});
assert.deepEqual(periodWindow('All','2020-01-01','2026-09-13'),{from:'2020-01-01',to:'2026-09-13'});
for (const scale of [0.5,1,2]) for (const direction of [-1,0,1]) {
  const w=moveWindow({from:'2026-03-20',to:'2026-04-10'},'2026-03-01','2026-04-30',scale,direction);
  assert(w.from >= '2026-03-01' && w.to <= '2026-04-30' && w.from <= w.to);
  assert.equal(dayNumber(w.to)-dayNumber(w.from)+1,Math.round(22*scale));
}
const observations=[{d:'2026-01-01',v:10},{d:'2026-01-31',v:20},{d:'2026-02-28',v:30}];
assert.deepEqual(sampleBalances(observations,'year'),[observations[0],observations[2]]);
assert.deepEqual(sampleBalances(observations,'day'),observations);
// A window starts from the balance at the end of the day before it: a salary on
// its first day counts.
const days=[{d:'2026-07-19',net:100},{d:'2026-07-20',net:100},{d:'2026-07-21',net:4500},{d:'2026-10-06',net:5800}];
const viewed=windowWithBase(days,{from:'2026-07-21',to:'2026-10-06'});
assert.deepEqual(viewed.map(p=>p.d),['2026-07-20','2026-07-21','2026-10-06']);
assert.equal(viewed.at(-1).net-viewed[0].net,5700);
assert.deepEqual(windowWithBase(days,{from:'2026-07-01',to:'2026-07-20'}).map(p=>p.d),['2026-07-19','2026-07-20']);
assert.deepEqual(windowWithBase(days,{from:'2026-08-01',to:'2026-08-31'}),[]);
const { accountGroups } = load('lib/account-groups.ts');
const account=(id,provider,kind='bank',currency='EUR')=>({id,provider,kind,currency,name:`Account ${id}`});
const grouped=accountGroups([account(1,'ing'),account(2,'ing'),account(3,'bunq'),account(4,'manual'),account(5,'manual'),account(6,'ing','bank','USD')]);
assert.equal(grouped.length,5);
assert.deepEqual(grouped[0].accounts.map(a=>a.id),[1,2]);
assert.equal(grouped[0].name,'ING');
console.log('Date windows, window bases, zoom boundaries, balance sampling and bank grouping passed.');

const { monthsCovered } = load('lib/timeline.ts');
assert.equal(monthsCovered({from:'2024-01-01',to:'2024-12-31'}),12);
assert.equal(monthsCovered({from:'2024-01-01',to:'2024-03-31'}),3);
assert.equal(monthsCovered({from:'2024-02-01',to:'2024-02-29'}),1);
assert.equal(monthsCovered({from:'2026-04-16',to:'2026-04-30'}),0.5);
assert.equal(monthsCovered({from:'2026-04-16',to:'2026-04-15'}),0);
console.log('Monthly averages use full and prorated calendar months correctly.');

const { averageMonthBase } = load('lib/timeline.ts');
assert.equal(averageMonthBase({from:'2026-08-14',to:'2026-09-13'},'1M'),1);
assert.equal(averageMonthBase({from:'2026-06-14',to:'2026-09-13'},'3M'),3);
assert.equal(averageMonthBase({from:'2025-09-14',to:'2026-09-13'},'1Y'),12);
assert.equal(averageMonthBase({from:'2026-09-01',to:'2026-09-13'},'1Y'),13/30);
