const fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'static/precision-analysis.js'),'utf8');
const body=source.slice(source.indexOf('  function projectTubeDates'),source.indexOf('  function limitExceedanceDate'));
const context={};vm.runInNewContext(body+'\nglobalThis.project=projectTubeDates;',context);
const cases=JSON.parse(fs.readFileSync(path.join(root,'tmp/life_parity_cases.json'),'utf8'));
const errors=[];let dates=0;
for(const c of cases){
  const actual=Object.fromEntries(context.project(c.rows,c.multiplier).map(row=>[String(row.tube_id),new Date(row.projectedDate).toISOString().slice(0,10)]));
  for(const key of new Set([...Object.keys(actual),...Object.keys(c.expected)])){
    dates++;if(actual[key]!==c.expected[key])errors.push({id:c.id,multiplier:c.multiplier,tube:key,client:actual[key],server:c.expected[key]});
  }
}
const result={cases:cases.length,dates,errors};
fs.writeFileSync(path.join(root,'reports/system_recheck/20261028/life_browser_parity.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify({...result,errors:errors.slice(0,10)}));process.exitCode=errors.length?1:0;
