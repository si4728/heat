const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const criticality={value:'NORMAL',addEventListener:(name,handler)=>criticality.change=handler};
const limit={value:'',dispatchEvent:()=>{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/plugging-limit-range.js'),'utf8'),{
  Event:class {},document:{querySelector:()=>criticality,getElementById:()=>limit,querySelectorAll:()=>[]}});
assert.equal(limit.value,'20');criticality.value='CRITICAL';criticality.change();assert.equal(limit.value,'20');
criticality.value='NORMAL';criticality.change();assert.equal(limit.value,'20');
limit.dataset={normalLimit:'18',criticalLimit:'12'};
criticality.change();assert.equal(limit.value,'18');
criticality.value='CRITICAL';criticality.change();assert.equal(limit.value,'12');
console.log('PASS: both defaults 20%; future configured importance limits retained');
