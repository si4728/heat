const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../static/precision-analysis.js'), 'utf8');
const body = source.slice(source.indexOf('  function revealLinkedItem'), source.indexOf('  function selectTube'));
const rect = (top = 0, left = 0, width = 20, height = 20) => ({top, left, width, height, bottom: top + height, right: left + width});
function viewport(header = false) {
  return {scrollTop:0, scrollLeft:0, clientHeight:200, clientWidth:200, calls:[],
    getBoundingClientRect:()=>rect(0,0,200,200), scrollTo(options){this.calls.push(options);},
    querySelector:()=>header ? {getBoundingClientRect:()=>rect(0,0,200,40)} : null};
}
const map = viewport(), table = viewport(true);
function item(id, kind) {
  const classes = new Set();
  return {dataset:kind === 'map' ? {tubeId:String(id)} : {analysisTube:String(id)}, attrs:{}, classes,
    classList:{add:c=>classes.add(c),remove:c=>classes.delete(c),toggle:(c,on)=>on?classes.add(c):classes.delete(c)},
    setAttribute(k,v){this.attrs[k]=v;}, closest:()=>table, getBoundingClientRect:()=>rect(900,300), offsetWidth:20};
}
const buttons = [item(1,'map'),item(1,'map'),item(2,'map')];
const rows = [item(1,'table'),item(2,'table'),item(3,'table')];
const status = {};
const context = {mapNode:map,tubes:[{tube_id:1,tube_no:'A'},{tube_id:2,tube_no:'B'}],defectByTube:new Map([[3,{tube_no:'C'}]]),
  document:{querySelectorAll:selector=>selector === '.precision-tube' ? buttons : rows,getElementById:()=>status}};
vm.runInNewContext(body + '\nglobalThis.sync=syncTubeSelection;',context);
context.sync(1,'map');
assert(rows[0].classes.has('linked-tube-pulse'));
assert.equal(table.calls.length,1);
assert(buttons[0].classes.has('selected') && buttons[1].classes.has('selected'));
assert.equal(buttons[0].attrs['aria-pressed'],'true');
context.sync(2,'table');
assert.equal(map.calls.length,1);
assert(buttons[2].classes.has('linked-tube-pulse'));
assert(!rows[0].classes.has('selected') && !rows[0].classes.has('linked-tube-pulse'));
assert.equal(rows[1].attrs['aria-current'],'true');
context.sync(3,'table');
assert(rows[2].classes.has('selected'));
assert(status.textContent.includes('C'));
context.sync(1,'initial');
assert.equal(map.calls.length,1);
assert.equal(table.calls.length,1);
console.log('PASS: bidirectional selection, container scrolling, pulses, duplicate Map points, missing Map location, no initial scrolling');
