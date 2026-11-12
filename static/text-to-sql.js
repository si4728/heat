(() => {
  'use strict';
  const root = document.getElementById('text-sql');
  if (!root) return;
  // Fold navigation on small screens without changing the saved preference.
  const shell = document.querySelector('.app-shell'), navToggle = document.querySelector('.sidebar-toggle');
  const smallScreen = window.matchMedia('(max-width:760px)');
  let autoCollapsed = false;
  function fitNavigation() {
    if (!shell || !navToggle) return;
    if (smallScreen.matches && !shell.classList.contains('sidebar-collapsed')) autoCollapsed = true;
    else if (smallScreen.matches || !autoCollapsed) return;
    const collapsed = smallScreen.matches;
    shell.classList.toggle('sidebar-collapsed', collapsed);
    navToggle.setAttribute('aria-expanded', String(!collapsed));
    navToggle.title = collapsed ? '왼쪽 메뉴 펼치기' : '왼쪽 메뉴 접기';
    navToggle.querySelector('[aria-hidden]').textContent = collapsed ? '›' : '‹';
    navToggle.querySelector('.sr-only').textContent = navToggle.title;
    if (!collapsed) autoCollapsed = false;
  }
  fitNavigation(); smallScreen.addEventListener('change', fitNavigation);
  if (navToggle) navToggle.addEventListener('click', () => { autoCollapsed = false; });
  const el = id => document.getElementById(`sql-${id}`);
  let token = null, busy = false, inspectionRequest = 0;
  const labels = {
    tube_no:'튜브번호', bundle_code:'번들', heat_exchanger_id:'열교환기 ID', unit_code:'공정', equipment_tag:'설비 Tag',
    equipment_code:'열교환기 코드', equipment_name:'설비명', inspection_count:'IRIS 검사 횟수',
    latest_inspection_date:'최근 검사일',
    inspected_tubes:'검사 Tube 수', valid_loss_tubes:'유효 감육률 Tube 수',
    minimum_mm:'최소두께 (mm)', maximum_loss:'최대 감육률 (%)', average_loss:'평균 감육률 (%)', mean_loss:'평균 감육률 (%)',
    tube_id:'Tube ID', source_tube_id:'Tube 번호', minimum_wall_thickness_mm:'최소두께 (mm)',
    wall_loss_percent:'감육률 (%)', location_mm:'측정 위치 (mm)', iris_tube_result_id:'측정 결과 ID',
    source_page:'원문 페이지', iris_inspection_id:'검사 ID'
  };
  function error(message) {
    el('error').textContent = message || '';
    el('error').hidden = !message;
    if (message) el('error').focus();
  }
  function reset() {
    token = null; el('code').value = ''; el('parameters').textContent = '—';
    el('copy').disabled = true; el('execute').disabled = true;
    el('result-table').hidden = true;
    el('result-table').querySelector('thead').replaceChildren();
    el('result-table').querySelector('tbody').replaceChildren();
    el('empty').hidden = false; el('empty').textContent = 'SQL을 생성하고 실행하면 결과를 확인할 수 있습니다.';
    el('result-count').textContent = '미실행';
    el('scope-details').hidden = true; el('scope-details').open = false; el('scope-list').textContent = '';
    el('result-scope').textContent = '조회 결과는 선택한 검사 회차의 Tube 상세 데이터를 기준으로 표시됩니다.';
    el('execute-status').textContent = '생성한 SQL을 확인한 뒤 실행하세요.';
    el('result-note').textContent = '읽기 전용 · 최대 100행 · SQL 실행 제한 5초 · 생성 SQL 유효시간 15분';
    error('');
  }
  const selectedIds = () => [...el('equipment').querySelectorAll('input:checked')].map(i => Number(i.value));
  const selectedUnits = () => [...el('units').querySelectorAll('input:checked')].map(i => i.value);
  let scopeReady = false;
  const frequencyQuestion = () => /열교환기|교환기|설비/.test(el('question').value) && /검사/.test(el('question').value) && /(?:제일|가장)\s*많|많이|횟수|빈도|건수/.test(el('question').value);
  function setBusy(value, generating = false) {
    busy = value;
    root.querySelectorAll('#sql-equipment input, #sql-units input, #sql-mode, #sql-filter, #sql-select-visible, #sql-clear-selection').forEach(control => { control.disabled = value; });
    el('inspection').disabled = value || frequencyQuestion() || el('mode').value !== 'equipment' || selectedIds().length !== 1 || !scopeReady;
    el('question').disabled = value;
    root.querySelectorAll('[data-question]').forEach(b => { b.disabled = value; });
    el('generate').disabled = value || (!scopeReady && !frequencyQuestion());
    el('execute').disabled = value || !token;
    root.setAttribute('aria-busy', String(value));
    if (value) el(generating ? 'generate-status' : 'execute-status').textContent = generating ? (frequencyQuestion() ? 'IRIS 검사 횟수 조회 SQL을 준비하고 있습니다.' : '로컬 모델이 SQL을 생성하고 있습니다. 최대 120초 소요됩니다.') : 'MariaDB에서 조회하고 있습니다.';
  }
  async function request(url, data) {
    const response = await fetch(url, {
      method:data ? 'POST' : 'GET', credentials:'same-origin',
      headers:data ? {'Content-Type':'application/json', 'X-CSRF-Token':root.dataset.csrf} : {},
      body:data ? JSON.stringify(data) : undefined
    });
    if (response.redirected) throw new Error('로그인 시간이 만료되었습니다. 새로고침 후 다시 로그인하세요.');
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) throw new Error(response.status === 403 ? 'Text-to-SQL 및 검사 관리 조회 권한을 확인하세요.' : '요청을 처리하지 못했습니다. 페이지를 새로고침한 뒤 다시 시도하세요.');
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || '조회 요청에 실패했습니다.');
    return payload;
  }
  async function scopeChanged() {
    reset(); const sequence = ++inspectionRequest;
    scopeReady = false;
    const unitMode = el('mode').value === 'unit', ids = selectedIds();
    el('units').hidden = !unitMode;
    el('equipment-picker').hidden = unitMode;
    el('selection-count').textContent = `${ids.length}대 선택`;
    el('inspection').replaceChildren(new Option('설비별 최근 유효 검사', ''));
    if (unitMode || ids.length !== 1) {
      scopeReady = unitMode ? selectedUnits().length > 0 : ids.length > 0;
      setBusy(false);
      el('generate-status').textContent = scopeReady ? '선택 범위의 최근 검사를 합쳐 분석합니다.' : '교환기 또는 공정을 선택하세요.';
      return;
    }
    el('inspection').replaceChildren(new Option('검사 회차를 불러오는 중입니다.', ''));
    setBusy(false);
    try {
      const payload = await request(`${root.dataset.inspectionsUrl}?exchanger_id=${ids[0]}`);
      if (sequence !== inspectionRequest) return;
      el('inspection').replaceChildren(new Option(payload.inspections.length ? '최근 유효 검사 (자동 선택)' : '유효한 검사 회차가 없습니다', ''));
      payload.inspections.forEach(row => {
        const date = (row.effective_date || '날짜 없음').slice(0, 10);
        el('inspection').add(new Option(`${date} · ${row.report_number || '보고서 번호 없음'} · 검사 #${row.iris_inspection_id}`, String(row.iris_inspection_id)));
      });
      scopeReady = payload.inspections.length > 0;
      setBusy(false);
      el('generate-status').textContent = scopeReady ? '질문을 입력하고 SQL을 생성하세요.' : '다른 교환기를 선택하세요.';
    } catch (exc) { if (sequence === inspectionRequest) { error(exc.message); setBusy(false); } }
  }
  el('equipment').addEventListener('change', scopeChanged);
  el('mode').addEventListener('change', scopeChanged);
  el('units').addEventListener('change', scopeChanged);
  el('filter').addEventListener('input', () => {
    const query = el('filter').value.trim().toLocaleLowerCase();
    el('equipment').querySelectorAll('label').forEach(row => { row.hidden = !row.textContent.toLocaleLowerCase().includes(query); });
  });
  el('select-visible').addEventListener('click', () => {
    el('equipment').querySelectorAll('label:not([hidden]) input').forEach(i => { i.checked = true; }); scopeChanged();
  });
  el('clear-selection').addEventListener('click', () => {
    el('equipment').querySelectorAll('input').forEach(i => { i.checked = false; }); scopeChanged();
  });
  el('inspection').addEventListener('change', reset);
  function questionChanged() {
    reset(); setBusy(false);
    if (frequencyQuestion()) el('generate-status').textContent = 'IRIS 검사 횟수 순위 · 기본 최근 5년 · 범위 미선택 시 VCM1·VCM2 전체';
  }
  el('question').addEventListener('input', questionChanged);
  root.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
    el('question').value = button.dataset.question; questionChanged(); el('question').focus();
  }));
  el('question-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    reset(); setBusy(true, true);
    try {
      const payload = await request(root.dataset.generateUrl, {
        ...(frequencyQuestion() && !(el('mode').value === 'unit' ? selectedUnits().length : selectedIds().length) ? {unit_codes:['VCM1','VCM2']} :
          el('mode').value === 'unit' ? {unit_codes:selectedUnits()} : {exchanger_ids:selectedIds(), inspection_id:el('inspection').value ? Number(el('inspection').value) : null}),
        question:el('question').value
      });
      token = payload.token; el('code').value = payload.proposal.sql;
      el('parameters').textContent = JSON.stringify(payload.proposal.parameters);
      el('copy').disabled = false;
      el('generate-status').textContent = 'SQL 검증 완료. 내용을 확인한 뒤 실행하세요.';
      if (payload.query_kind === 'inspection_frequency') {
        el('result-scope').textContent = `${payload.period.all_history ? '전체 이력' : payload.period.start + ' ~ ' + payload.period.end} · ${payload.equipment_list.length}대 범위 · IRIS 검사 회차 수 내림차순 · 상위 ${payload.period.limit}${payload.period.target === 'tube' ? '개 튜브' : '대'} · 검사일 없으면 보고일 기준`;
        el('scope-list').textContent = payload.equipment_list.map(s => `${s.unit_code} · ${s.equipment_tag || s.equipment_code}`).join('\n');
        el('scope-details').hidden = false;
        return;
      }
      const scopes = payload.scopes || [{equipment:payload.equipment, inspection:payload.inspection}];
      const excluded = payload.excluded || [];
      el('result-scope').textContent = `${[...new Set(scopes.map(s => s.equipment.unit_code))].join(' · ')} · ${scopes.length}대 분석 · 제외 ${excluded.length}대 · 선택된 검사 Tube를 합쳐 집계합니다.`;
      el('scope-list').textContent = scopes.map(s => `분석 · ${s.equipment.unit_code} ${s.equipment.equipment_tag || s.equipment.equipment_code} · 검사 #${s.inspection.iris_inspection_id}`).concat(excluded.map(s => `제외 · ${s.equipment.unit_code} ${s.equipment.equipment_tag || s.equipment.equipment_code} · ${s.reason}`)).join('\n');
      el('scope-details').hidden = false;
    } catch (exc) { error(exc.message); el('generate-status').textContent = 'SQL을 생성하지 못했습니다.'; }
    finally { setBusy(false); }
  });
  el('execute').addEventListener('click', async () => {
    if (busy || !token) return;
    error(''); setBusy(true);
    el('result-table').hidden = true; el('empty').hidden = false; el('empty').textContent = '결과를 조회하고 있습니다.'; el('result-count').textContent = '조회 중';
    try {
      const {result} = await request(root.dataset.executeUrl, {token});
      const table = el('result-table'), head = table.querySelector('thead'), body = table.querySelector('tbody');
      head.replaceChildren(); body.replaceChildren();
      const columns = ['equipment_code', ...(result.columns || Object.keys(result.rows[0] || {})).filter(column => column !== 'equipment_code')], header = document.createElement('tr');
      const combinedSummary = (result.scopes || []).length > 1 && result.rows.every(row => row.heat_exchanger_id == null);
      const numeric = new Set(columns.filter(column => result.rows.some(row => typeof row[column] === 'number')));
      columns.forEach(column => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = column === 'equipment_code' && combinedSummary ? '열교환기 코드 (집계 대상)' : labels[column] || column; if (numeric.has(column)) th.className = 'sql-number'; header.append(th); });
      head.append(header);
      result.rows.forEach(row => {
        const tr = document.createElement('tr');
        columns.forEach(column => {
          const td = document.createElement('td'), value = row[column];
          if (value === null || value === undefined) { td.textContent = '—'; td.classList.add('sql-null'); }
          else if (typeof value === 'number') {
            const countOrId = /(?:_tubes|_count|_id)$/.test(column) || column === 'source_page';
            const decimals = !countOrId && /(?:loss|thickness|minimum_mm|location_mm)/.test(column) ? 2 : 0;
            td.textContent = new Intl.NumberFormat('ko-KR', {minimumFractionDigits:decimals, maximumFractionDigits:decimals || 6}).format(value);
          } else td.textContent = column === 'latest_inspection_date' ? String(value).slice(0,10) : String(value);
          if (numeric.has(column)) td.classList.add('sql-number');
          if (column === 'equipment_code') window.TextSqlLinks.equipmentCell(td, row, result, root.dataset);
          else window.TextSqlLinks.decorate(td, column, row, result, root.dataset);
          tr.append(td);
        }); body.append(tr);
      });
      table.hidden = !columns.length; el('empty').hidden = result.rows.length > 0;
      el('empty').textContent = '조건에 맞는 Tube 결과가 없습니다.';
      el('result-count').textContent = `${result.result_count.toLocaleString('ko-KR')}행`;
      el('execute-status').textContent = '조회가 완료되었습니다.';
      el('result-note').textContent = `${result.limit_reached ? '100행 제한에 도달했습니다. 조건을 좁혀 조회하세요. · ' : ''}결측값은 —로 표시합니다. 평균 감육률은 유효 Tube의 산술평균입니다. · 조회 ${new Date(result.generated_at).toLocaleString('ko-KR')}`;
      if (result.query_kind === 'inspection_frequency') {
        el('empty').textContent = '선택 범위와 기간에 해당하는 IRIS 검사 이력이 없습니다.';
        el('result-note').textContent = result.period.target === 'tube'
          ? `설비·번들·튜브번호별 1행 · 유효 결과를 검사 ID별 1회 집계 · 대체된 검사 제외 · 동률은 공정·설비 태그·설비 ID·번들·튜브번호순 · 최대 ${result.period.limit}개`
          : `IRIS 검사 ID별 1회 집계 · 대체된 검사 제외 · 동률은 최근 검사일, 설비 ID 순 · 최대 ${result.period.limit}대`;
      }
    } catch (exc) { error(exc.message); el('execute-status').textContent = 'SQL을 실행하지 못했습니다.'; el('empty').textContent = '조회에 실패했습니다. 오류 내용을 확인한 뒤 다시 시도하세요.'; el('result-count').textContent = '실행 실패'; }
    finally { setBusy(false); }
  });
  el('copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(el('code').value); el('execute-status').textContent = 'SQL을 복사했습니다.'; }
    catch (_) { el('code').focus(); el('code').select(); el('execute-status').textContent = '선택한 SQL을 Ctrl+C로 복사하세요.'; }
  });
})();
