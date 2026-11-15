const assert=require('node:assert/strict');
const charts=require('../static/text-to-sql-charts.js');
for(const value of [null,undefined,'',true,false,'  ',Infinity,NaN,'0x10','1,000',{},[]]) assert.equal(charts.number(value),null);
assert.equal(charts.number(0),0);assert.equal(charts.number('-1.5'),-1.5);assert.equal(charts.number('1e3'),1000);
const result={columns:['tube_id','source_page','equipment_tag','tube_no','inspection_count','wall_loss_percent'],rows:[
  {tube_id:1,source_page:3,equipment_tag:'E-1',tube_no:'1-1',inspection_count:9,wall_loss_percent:20},
  {tube_id:2,source_page:4,equipment_tag:'E-2',tube_no:'1-1',inspection_count:3,wall_loss_percent:null},
  {tube_id:3,source_page:5,equipment_tag:'E-2',tube_no:'1-1',inspection_count:0,wall_loss_percent:0}]};
const before=JSON.stringify(result), fields=charts.describe(result);
assert.deepEqual(fields.metrics,['inspection_count','wall_loss_percent']);
assert.equal(fields.category,'tube_no');
const points=charts.points(result,'inspection_count','tube_no');
assert.equal(new Set(points.map(p=>p.label)).size,3);
assert.equal(points[2].value,0);
assert.equal(charts.points(result,'wall_loss_percent','tube_no')[1].value,null);
assert.equal(charts.pie(points,'inspection_count').total,12);
assert.ok(charts.pie(points,'wall_loss_percent').reason);
assert.ok(charts.pie([{value:-1},{value:2}],'inspection_count').reason);
assert.ok(charts.pie([{value:0},{value:0}],'inspection_count').reason);
assert.ok(charts.pie([{value:1e308},{value:1e308}],'inspection_count').reason);
const slices=charts.pie(Array.from({length:10},(_,index)=>({value:index+1,label:String(index),index})),'inspection_count');
assert.equal(slices.slices.length,5);assert.equal(slices.total,55);
assert.equal(slices.slices.reduce((n,p)=>n+p.value,0),55);
const history={columns:['inspection_date','minimum_wall_thickness_mm'],rows:[
  {inspection_date:'2025-01-01',minimum_wall_thickness_mm:1},
  {inspection_date:'2023-01-01',minimum_wall_thickness_mm:2},
  {inspection_date:'2024-01-01',minimum_wall_thickness_mm:null}]};
const series=charts.line(charts.points(history,'minimum_wall_thickness_mm','inspection_date'),'inspection_date');
assert.deepEqual(series.series.map(p=>p.value),[2,null,1]);
assert.ok(charts.line([...series.series,{...series.series[0]}],'inspection_date').reason);
assert.ok(charts.line([{categoryValue:'2025-02-30',value:1},{categoryValue:'2026-01-01',value:2}],'date').reason);
assert.equal(charts.line([{categoryValue:2024,value:1},{categoryValue:2025,value:2}],'year').series.length,2);
assert.ok(charts.line(points,'tube_no').reason);
assert.deepEqual(charts.describe({rows:[]}).metrics,[]);
assert.deepEqual(charts.describe({columns:['tube_id'],rows:[{tube_id:7}]}).metrics,[]);
assert.equal(JSON.stringify(result),before);
console.log('PASS: chart metrics, ID exclusion, null/zero, unique labels, count-only pie, totals, overflow, chronology, gaps and immutable rows');
