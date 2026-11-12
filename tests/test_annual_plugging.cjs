const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const source=fs.readFileSync(path.join(__dirname,'../static/precision-analysis.js'),'utf8');
const body=source.slice(source.indexOf('  function annualPluggingSeries'),source.indexOf('  function renderAnnualPlugging'));
const context={};vm.runInNewContext(body+'\nglobalThis.build=annualPluggingSeries;',context);
const projectionBody=source.slice(source.indexOf('  function projectTubeDates'),source.indexOf('  function limitExceedanceDate'));
vm.runInNewContext(projectionBody+'\nglobalThis.project=projectTubeDates;globalThis.color=pluggingBarColor;',context);
assert.equal(context.color(7,10),'#0d9488');assert.equal(context.color(8,10),'#d97706');
assert.equal(context.color(10,10),'#d97706');assert.equal(context.color(11,10),'#dc2626');
assert.equal(context.color(0,0),'#0d9488');assert.equal(context.color(1,0),'#dc2626');
const forecast={projection_origin_date:'2026-10-28',years_from_measurement:10,basis:'CALCULATED'};
const actual={projection_origin_date:'2020-01-01',plugging_date:'2024-05-01',basis:'ALREADY_PLUGGED'};
assert(context.project([forecast],2)[0].projectedDate<context.project([forecast],1)[0].projectedDate);
assert.equal(context.project([actual],.1)[0].projectedDate,Date.parse('2024-05-01T00:00:00Z'));
assert.equal(context.project([{...forecast,years_from_measurement:1e20}],.1).length,0);
assert.equal(context.project([{...forecast,years_from_measurement:null}],1).length,0);
assert.equal(context.project([{...forecast,years_from_measurement:-1}],1).length,0);
console.log('PASS: green/yellow/red boundaries, slider forecast dates, actual plugged date, date range and missing values');
const dates=['2024-12-31','2026-01-01','2026-12-31','2027-01-01','2055-01-01'];
const input=dates.map(d=>({projectedDate:Date.parse(d+'T00:00:00Z')}));input.push({projectedDate:NaN});
const rows=context.build(input,2026,2027);
const limitBody=source.slice(source.indexOf('  function limitExceedanceDate'),source.indexOf('  function updateRateAnalysis'));
vm.runInNewContext(limitBody+'\nglobalThis.exceed=limitExceedanceDate;',context);
assert.equal(context.exceed(input,null),null);
assert.equal(context.exceed(input,0),Date.parse('2024-12-31T00:00:00Z'));
assert.equal(context.exceed(input,3),Date.parse('2027-01-01T00:00:00Z'));
assert.equal(rows[0].cumulative,3);assert.equal(rows[0].added,2);
assert.equal(rows[1].cumulative,4);assert.equal(rows[1].added,1);
assert.equal(context.build([],2026,2026)[0].cumulative,0);
console.log('PASS: annual boundaries, previous years, invalid dates, out-of-window forecasts, empty series');
// Exercise actual history rendering with original values, including unavailable
// measurements and old installations; values must never become generated history.
function element(){return {children:[],style:{},appendChild(x){this.children.push(x);},replaceChildren(){this.children=[];}};}
const node=element();
const hctx={lifeData:{tube_histories:{'7':[
  {date:'2020-01-01',thickness_mm:2.5,historical:true,inspection_id:1,result_id:11},
  {date:'2025-01-01',thickness_mm:2.1,historical:false,inspection_id:2,result_id:12},
  {date:'2025-02-01',thickness_mm:null,historical:false,inspection_id:3,result_id:13}
]}},document:{getElementById:()=>node,createElement:()=>element()}};
const historyBody=source.slice(source.indexOf('  function renderThicknessHistory'),source.indexOf('  function revealLinkedItem'));
vm.runInNewContext(historyBody+'\nrenderThicknessHistory(7,3);',hctx);
assert.equal(node.children.length,4);
assert(node.children[0].children[0].textContent.includes('2020-01-01'));
assert(node.children[0].children[0].textContent.includes('2.50 mm'));
assert(node.children[0].children[0].textContent.includes('조회 전용'));
assert(node.children[1].children[0].textContent.includes('2.10 mm'));
assert(node.children[2].children[0].textContent.includes('유효 두께 미등록'));
assert.equal(node.children[2].children.length,2);
console.log('PASS: real dated thickness history, historical marker, missing measurement, inspection links');
