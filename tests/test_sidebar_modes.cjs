const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const script = fs.readFileSync(require('node:path').join(__dirname,'../static/sidebar.js'),'utf8');
function page(mode, narrow=false, saved='false') {
  const classes = new Set(), events={}, mediaEvents={};
  const icon={}, label={}, attributes={};
  const shell={dataset:{sidebarMode:mode},classList:{contains:k=>classes.has(k),toggle(k,on){on?classes.add(k):classes.delete(k);}}};
  const toggle={setAttribute:(k,v)=>attributes[k]=v,querySelector:s=>s.includes('aria-hidden')?icon:label,addEventListener:(e,fn)=>events[e]=fn};
  const media={matches:narrow,addEventListener:(e,fn)=>mediaEvents[e]=fn};
  vm.runInNewContext(script,{document:{querySelector:s=>s==='.app-shell'?shell:s==='.sidebar-toggle'?toggle:null,addEventListener:(e,fn)=>events[e]=fn},window:{matchMedia:()=>media,localStorage:{getItem:()=>saved,setItem:(k,v)=>saved=v}}});
  return {collapsed:()=>classes.has('sidebar-collapsed'),click:()=>events.click(),attributes,
    resize(value){media.matches=value;mediaEvents.change();},escape:()=>events.keydown({key:'Escape'})};
}
for (const narrow of [false,true]) {
  for(const saved of ['false','true']) {
    const analysis=page('collapsed',narrow,saved);
    assert.equal(analysis.collapsed(),true);
    analysis.click();assert.equal(analysis.collapsed(),false);
    assert.equal(analysis.attributes['aria-expanded'],'true');
    analysis.click();assert.equal(analysis.collapsed(),true);
    const detail=page('expanded',narrow,saved);
    assert.equal(detail.collapsed(),false);
    detail.click();assert.equal(detail.collapsed(),true);
    detail.resize(!narrow);assert.equal(detail.collapsed(),true);
    detail.click();assert.equal(detail.collapsed(),false);
  }
}
const detail=page('expanded',true);detail.escape();assert.equal(detail.collapsed(),true);
assert.equal(page('auto',true).collapsed(),true);
assert.equal(page('auto',false,'true').collapsed(),true);
assert.equal(page('auto',false,'false').collapsed(),false);
console.log('PASS: analysis hides; detail shows; button overrides both; resize preserves manual choice; Escape and other-page preferences work');
