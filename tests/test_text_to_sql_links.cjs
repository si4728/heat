const assert = require('node:assert/strict');
const links = require('../static/text-to-sql-links.js');
const urls = {tubeUrl:'/iris2/tubes/0', exchangerUrl:'/iris2/exchangers/0', inspectionUrl:'/iris2/inspections/0'};
assert.equal(links.resolve('source_tube_id', {tube_id:123, source_tube_id:'A-7'}, {}, urls).href, '/iris2/tubes/123');
assert.equal(links.resolve('tube_id', {tube_id:123}, {}, urls).href, '/iris2/tubes/123');
assert.equal(links.resolve('source_tube_id', {source_tube_id:7}, {}, urls), null);
for (const column of ['heat_exchanger_id', 'equipment_code', 'equipment_tag', 'equipment_name']) {
  assert.equal(links.resolve(column, {heat_exchanger_id:151}, {}, urls).href, '/iris2/exchangers/151');
}
assert.equal(links.resolve('equipment_code', {}, {heat_exchanger_id:151}, urls).href, '/iris2/exchangers/151');
assert.equal(links.resolve('equipment_code', {heat_exchanger_id:152}, {heat_exchanger_id:151}, urls).href, '/iris2/exchangers/152');
assert.equal(links.resolve('equipment_code', {}, {heat_exchanger_id:null}, urls), null);
assert.equal(links.resolve('iris_inspection_id', {iris_inspection_id:389}, {}, urls).href, '/iris2/inspections/389');
for (const id of [null, undefined, '', 0, -1, 1.5, true, {}, [], '1/../../x', 'javascript:alert(1)', '1e3', Number.MAX_SAFE_INTEGER+1]) {
  assert.equal(links.resolve('tube_id', {tube_id:id}, {}, urls), null);
}
for (const column of ['inspection_count', 'inspected_tubes', 'wall_loss_percent', 'iris_tube_result_id']) {
  assert.equal(links.resolve(column, {tube_id:123}, {}, urls), null);
}
assert.equal(links.resolve('tube_id', {tube_id:123}, {}, {tubeUrl:'//evil.test/tubes/0'}), null);
assert.equal(links.resolve('tube_id', {tube_id:123}, {}, {tubeUrl:'javascript:/0'}), null);
console.log('Text-to-SQL links: primary keys, mixed rows, aggregate exclusions, subpath URLs and invalid IDs passed');
const scopes=[{heat_exchanger_id:151,equipment:{equipment_code:'E106'}},{heat_exchanger_id:152,equipment:{equipment_code:'E107'}}];
assert.deepEqual(links.equipmentContexts({}, {scopes}).map(e=>e.equipment_code),['E106','E107']);
assert.deepEqual(links.equipmentContexts({heat_exchanger_id:152,equipment_code:'E107'}, {scopes}).map(e=>e.equipment_code),['E107']);
assert.equal(links.equipmentContexts({}, {heat_exchanger_id:151,equipment:{equipment_code:'E106'}})[0].equipment_code,'E106');
assert.equal(links.equipmentContexts({}, {scopes:[...scopes,scopes[0]]}).length,2);
