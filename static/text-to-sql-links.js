(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TextSqlLinks = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function identifier(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (!/^[1-9]\d*$/.test(String(value))) return null;
    const id = Number(value);
    return Number.isSafeInteger(id) ? String(id) : null;
  }
  function resolve(column, row, result, urls) {
    let id, template, title;
    if (column === 'tube_id' || column === 'source_tube_id') {
      // A report's printed tube number is not the application's primary key.
      id = identifier(row.tube_id); template = urls.tubeUrl; title = 'Tube 상세 조회';
    } else if (['heat_exchanger_id', 'equipment_code', 'equipment_tag', 'equipment_name'].includes(column)) {
      // Only a single-equipment result may supply a result-level fallback.
      id = identifier(row.heat_exchanger_id == null ? result.heat_exchanger_id : row.heat_exchanger_id);
      template = urls.exchangerUrl; title = '교환기 상세 조회';
    } else if (column === 'iris_inspection_id') {
      id = identifier(row.iris_inspection_id); template = urls.inspectionUrl; title = '검사 상세 조회';
    }
    if (!id || !template || !template.startsWith('/') || template.startsWith('//') || !template.includes('/0')) return null;
    return {href: template.replace(/\/0(?=\/|$)/, '/' + id), title};
  }
  function decorate(cell, column, row, result, urls) {
    if (row[column] === null || row[column] === undefined || row[column] === '') return;
    const link = resolve(column, row, result, urls);
    if (!link) return;
    const anchor = cell.ownerDocument.createElement('a');
    anchor.href = link.href;
    anchor.textContent = cell.textContent;
    anchor.className = 'sql-detail-link';
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    anchor.title = link.title + ' (새 탭)';
    anchor.setAttribute('aria-label', anchor.textContent + ' · ' + anchor.title);
    cell.replaceChildren(anchor);
  }
  function equipmentContexts(row, result) {
    if (identifier(row.heat_exchanger_id)) return [{...row}];
    if (identifier(result.heat_exchanger_id) && result.equipment) {
      return [{...result.equipment, heat_exchanger_id:result.heat_exchanger_id}];
    }
    const seen = new Set();
    return (result.scopes || []).flatMap(scope => {
      const id = identifier(scope.heat_exchanger_id ?? scope.equipment?.heat_exchanger_id);
      if (!id || seen.has(id)) return [];
      seen.add(id);
      return [{...scope.equipment, heat_exchanger_id:id}];
    });
  }
  function equipmentCell(cell, row, result, urls) {
    const contexts = equipmentContexts(row, result);
    cell.replaceChildren();
    if (!contexts.length) { cell.textContent = row.equipment_code || '—'; return; }
    contexts.forEach((equipment, index) => {
      if (index) cell.append(cell.ownerDocument.createTextNode(' · '));
      const span = cell.ownerDocument.createElement('span');
      span.textContent = equipment.equipment_code || equipment.equipment_tag || `ID ${equipment.heat_exchanger_id}`;
      decorate(span, 'equipment_code', {...equipment, equipment_code:span.textContent}, result, urls);
      cell.append(span);
    });
    if (contexts.length > 1) cell.title = '집계 대상 열교환기 코드';
  }
  return {resolve, decorate, equipmentContexts, equipmentCell};
});
