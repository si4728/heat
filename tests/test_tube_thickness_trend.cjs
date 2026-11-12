const assert=require('node:assert/strict');
const {series}=require('../static/tube-thickness-trend.js');
const history=[{date:'2025-01-01',thickness_mm:2.01},{date:'2023-01-01',thickness_mm:2.06},
  {date:'2020-01-01',thickness_mm:2.3,historical:true},{date:'2025-02-01',thickness_mm:null},
  {date:'bad',thickness_mm:2},{date:'2025-02-31',thickness_mm:2},{date:'2025-03-01',thickness_mm:0}];
const actual=series(history);
assert.equal(actual.length,4);
assert.equal(actual[0].historical,true);
assert.equal(actual.at(-1).value,0);
assert.equal(actual[2].date,'2025-01-01');
assert.equal(history[0].date,'2025-01-01');
assert.equal(series([]).length,0);
assert.equal(series([{date:'2025-01-01',thickness_mm:Infinity}]).length,0);
console.log('PASS: actual dates, chronological order, invalid dates, zero thickness, missing values and original-history immutability');
