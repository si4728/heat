const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '../static/exchanger-form.js'), 'utf8');
function run(selectedUnused) {
  const connected = {dataset:{unconnected:'false'},selected:!selectedUnused};
  const unused = {dataset:{unconnected:'true'},selected:selectedUnused};
  const callbacks = {};
  const select = {options:[connected,unused],get selectedOptions(){return this.options.filter(x=>x.selected);},addEventListener(type,fn){callbacks.select=fn;}};
  const toggle = {checked:false,addEventListener(type,fn){callbacks.toggle=fn;}};
  vm.runInNewContext(source,{document:{getElementById(id){return {'organization-process':select,'show-unconnected-processes':toggle}[id]||null;}}});
  return {connected,unused,select,toggle,callbacks};
}
const state = run(false);
assert(state.unused.hidden && state.unused.disabled);
assert(!state.connected.hidden && !state.connected.disabled);
state.toggle.checked = true; state.callbacks.toggle();
assert(!state.unused.hidden && !state.unused.disabled);
state.connected.selected = false; state.unused.selected = true;
state.toggle.checked = false; state.callbacks.toggle();
assert(!state.unused.hidden && !state.unused.disabled, 'Do not silently drop the current selection');
state.connected.selected = true; state.unused.selected = false; state.callbacks.select();
assert(state.unused.hidden && state.unused.disabled);
const restored = run(true);
assert(restored.toggle.checked && !restored.unused.disabled, 'Preserve a selection after validation errors');
console.log('PASS: unused organization choices are opt-in, selectable, and preserved on validation');
