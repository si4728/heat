(() => {
  const rateSlider = document.getElementById('corrosion-rate-slider');
  let selectedTubeId = null;
  ['corrosion', 'remaining-life'].forEach(prefix => {
    const helpTrigger = document.getElementById(`${prefix}-help-trigger`);
    const helpDialog = document.getElementById(`${prefix}-help-dialog`);
    if (!helpTrigger || !helpDialog) return;
    helpTrigger.addEventListener('click', () => helpDialog.showModal());
    helpDialog.addEventListener('click', event => {
      const bounds = helpDialog.getBoundingClientRect();
      if (event.target === helpDialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) helpDialog.close();
    });
    helpDialog.addEventListener('close', () => helpTrigger.focus());
  });
  const mapNode = document.getElementById('precision-tube-map');
  const mapJson = document.getElementById('precision-map-data');
  const lifeJson = document.getElementById('precision-life-data');
  if (!mapNode || !mapJson || !lifeJson) return;

  const panelLayout = document.getElementById('precision-panel-layout');
  const widthResizer = document.getElementById('precision-panel-resizer');
  const heightResizer = document.getElementById('precision-map-height-resizer');
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  function bindResizer(handle, read, write, pointerValue, keys, step, enabled = () => true) {
    if (!handle) return;
    let drag = null;
    handle.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !enabled()) return;
      event.preventDefault();
      handle.focus();
      drag = {id: event.pointerId, x: event.clientX, y: event.clientY, value: read()};
      handle.setPointerCapture(event.pointerId);
      handle.classList.add('is-resizing');
    });
    handle.addEventListener('pointermove', event => {
      if (drag && drag.id === event.pointerId && enabled()) write(pointerValue(event, drag));
    });
    const finish = event => {
      if (!drag || drag.id !== event.pointerId) return;
      drag = null;
      handle.classList.remove('is-resizing');
      if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    };
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => handle.addEventListener(name, finish));
    handle.addEventListener('keydown', event => {
      if (!enabled() || !keys.includes(event.key)) return;
      event.preventDefault();
      write(read() + (event.key === keys[0] ? -step : step));
    });
  }
  if (panelLayout && widthResizer) {
    let mapShare = 50;
    bindResizer(widthResizer, () => mapShare, value => {
      mapShare = clamp(value, 25, 75);
      panelLayout.style.setProperty('--map-track', `${mapShare}fr`);
      panelLayout.style.setProperty('--results-track', `${100 - mapShare}fr`);
      widthResizer.setAttribute('aria-valuenow', String(Math.round(mapShare)));
    }, (event, drag) => drag.value + (event.clientX - drag.x) / Math.max(panelLayout.clientWidth - widthResizer.offsetWidth, 1) * 100,
    ['ArrowLeft', 'ArrowRight'], 2, () => window.matchMedia('(min-width: 1101px)').matches);
  }
  if (heightResizer) {
    const writeHeight = value => {
      const height = clamp(Math.round(value), 240, 1600);
      mapNode.style.height = `${height}px`;
      heightResizer.setAttribute('aria-valuenow', String(height));
    };
    heightResizer.setAttribute('aria-valuenow', String(Math.round(mapNode.getBoundingClientRect().height)));
    bindResizer(heightResizer, () => mapNode.getBoundingClientRect().height, writeHeight,
      (event, drag) => drag.value + event.clientY - drag.y, ['ArrowUp', 'ArrowDown'], 20);
  }

  const mapData = JSON.parse(mapJson.textContent);
  const lifeData = JSON.parse(lifeJson.textContent);
  if (rateSlider) {
    rateSlider.value = '1.0';
    rateSlider.addEventListener('input', () => {
      document.getElementById('corrosion-rate-output').textContent = `${Number(rateSlider.value).toFixed(1)}배`;
      updateRateAnalysis();
    });
    document.getElementById('corrosion-rate-form').addEventListener('submit', event => event.preventDefault());
  }
  const tubes = mapData.tubes || [];
  const defects = lifeData.defect_rows || [];
  const worstWallLoss = defects.reduce((worst, defect) => Math.max(worst, Number(defect.wall_loss_percent)), -Infinity);
  const defectByTube = new Map(defects.map(row => [Number(row.tube_id), row]));
  const validCoordinate = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const validPoints = tubes.filter(tube => validCoordinate(tube.x) && validCoordinate(tube.y));
  const defaultColors = {NORMAL:'#14b8a6', WARNING:'#f59e0b', CRITICAL:'#ef4444', NOT_INSPECTED:'#64748b', PLUGGED:'#334155'};
  const mapColor = key => mapData.colors?.[key] || defaultColors[key];
  const warning = Number(mapData.thresholds?.warning ?? 20);
  const critical = Number(mapData.thresholds?.critical ?? 40);
  function mixColor(from, to, ratio) {
    const parse = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
    const a = parse(from), b = parse(to), t = Math.max(0, Math.min(1, ratio));
    return `#${a.map((value, i) => Math.round(value + (b[i] - value) * t).toString(16).padStart(2, '0')).join('')}`;
  }
  function colorFromLossPercent(loss) {
    if (!Number.isFinite(loss)) return mapColor('NOT_INSPECTED');
    if (loss <= warning) return mixColor(mapColor('NORMAL'), mapColor('WARNING'), loss / Math.max(warning, 0.01));
    return mixColor(mapColor('WARNING'), mapColor('CRITICAL'), (loss - warning) / Math.max(critical - warning, 0.01));
  }
  const lossLegend = [
    {key:'NORMAL', label:`정상 · ${warning}% 미만`, color:mapColor('NORMAL')},
    {key:'WARNING', label:`주의 · ${warning}% 이상~${critical}% 미만`, color:mapColor('WARNING')},
    {key:'CRITICAL', label:`위험 · ${critical}% 이상`, color:mapColor('CRITICAL')},
    {key:'NOT_INSPECTED', label:'미검사 / 감육률 미등록', color:mapColor('NOT_INSPECTED')},
    {key:'PLUGGED', label:'Plugged · 사용중지', color:mapColor('PLUGGED')},
  ];
  const legendByKey = new Map(lossLegend.map(item => [item.key, {...item, count: 0}]));
  const lossKey = tube => {
    if (tube.category === 'PLUGGED' || (tube.operational_status || tube.current_status) === 'PLUGGED') return 'PLUGGED';
    if (tube.category === 'NOT_INSPECTED' || !validCoordinate(tube.wall_loss_percent)) return 'NOT_INSPECTED';
    const loss = Number(tube.wall_loss_percent);
    return loss >= critical ? 'CRITICAL' : loss >= warning ? 'WARNING' : 'NORMAL';
  };
  const tubeColor = tube => {
    const key = lossKey(tube);
    return ['NOT_INSPECTED', 'PLUGGED'].includes(key) ? mapColor(key) : colorFromLossPercent(Number(tube.wall_loss_percent));
  };
  validPoints.forEach(tube => legendByKey.get(lossKey(tube)).count++);
  const legendNode = document.getElementById('precision-map-legend');
  if (legendNode) {
    legendByKey.forEach(item => {
      const entry = document.createElement('div');
      entry.className = 'wall-loss-legend-entry';
      const icon = document.createElement('i');
      icon.style.backgroundColor = item.color;
      icon.setAttribute('aria-hidden', 'true');
      const label = document.createElement('span');
      label.textContent = item.label;
      const count = document.createElement('strong');
      count.textContent = item.unavailable ? '—' : item.count.toLocaleString('ko-KR');
      entry.appendChild(icon);
      entry.appendChild(label);
      entry.appendChild(count);
      legendNode.appendChild(entry);
    });
    const gradient = document.createElement('div');
    gradient.className = 'wall-loss-legend-gradient';
    const strip = document.createElement('div');
    strip.style.background = `linear-gradient(90deg, ${mapColor('NORMAL')}, ${mapColor('WARNING')}, ${mapColor('CRITICAL')})`;
    const caption = document.createElement('span');
    caption.textContent = `감육률 0% → ${warning}% → ${critical}% 이상 (연속 색상)`;
    gradient.appendChild(strip);
    gradient.appendChild(caption);
    legendNode.appendChild(gradient);
    const total = document.createElement('div');
    total.className = 'wall-loss-legend-total';
    total.textContent = `Total Tubes · 표시 Tube 합계 ${validPoints.length.toLocaleString('ko-KR')}개`;
    legendNode.appendChild(total);
  }
  const xs = validPoints.map(tube => Number(tube.x));
  const ys = validPoints.map(tube => Number(tube.y));
  const minX = xs.length ? Math.min(...xs) : 0, maxX = xs.length ? Math.max(...xs) : 1;
  const minY = ys.length ? Math.min(...ys) : 0, maxY = ys.length ? Math.max(...ys) : 1;
  const scale = (value, min, max) => max === min ? 50 : 10 + ((Number(value) - min) / (max - min)) * 80;
  const mapCanvas = document.createElement('div');
  mapCanvas.className = 'precision-map-canvas';
  mapNode.appendChild(mapCanvas);
  const overlayToggle = document.getElementById('precision-overlay-toggle');
  if (overlayToggle) {
    const overlayStorageKey = 'iris2.precision-map.overlays';
    try {
      const saved = localStorage.getItem(overlayStorageKey);
      if (saved === 'true' || saved === 'false') overlayToggle.setAttribute('aria-checked', saved);
    } catch { /* Keep the default when browser storage is unavailable. */ }
    const updateVisibility = () => {
      const hidden = overlayToggle.getAttribute('aria-checked') !== 'true';
      mapNode.classList.toggle('hide-map-grid', hidden);
      mapNode.classList.toggle('hide-map-labels', hidden);
    };
    overlayToggle.addEventListener('click', () => {
      overlayToggle.setAttribute('aria-checked', String(overlayToggle.getAttribute('aria-checked') !== 'true'));
      try {
        localStorage.setItem(overlayStorageKey, overlayToggle.getAttribute('aria-checked'));
      } catch { /* The switch remains usable even when persistence is blocked. */ }
      updateVisibility();
    });
    updateVisibility();
  }
  const axisGroups = field => {
    const groups = new Map();
    validPoints.forEach(tube => {
      if (!validCoordinate(tube[field])) return;
      const key = Number(tube[field]);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(tube);
    });
    return groups;
  };
  const rows = axisGroups('row');
  const columns = axisGroups('column');
  // Keep every label readable on dense sheets; the map viewport scrolls.
  mapCanvas.style.minWidth = `${Math.max(400, columns.size * 24 + 100)}px`;
  mapCanvas.style.minHeight = `${Math.max(400, rows.size * 24 + 70)}px`;
  const addLabel = (text, className, left, top, title) => {
    const label = document.createElement('span');
    label.className = `precision-map-label ${className}`;
    label.textContent = text;
    label.style.left = left;
    label.style.top = top;
    label.title = title || text;
    mapCanvas.appendChild(label);
  };
  const addGridLine = (direction, position) => {
    const line = document.createElement('span');
    line.className = `precision-map-grid precision-map-grid-${direction}`;
    line.style[direction === 'row' ? 'top' : 'left'] = `${position}%`;
    line.setAttribute('aria-hidden', 'true');
    mapCanvas.appendChild(line);
  };
  addLabel('Y · 행', 'axis-heading', '4%', '22px');
  addLabel('X · 열', 'axis-heading', '50%', 'calc(100% - 8px)');
  addLabel('수량', 'axis-heading', '97%', '22px');
  rows.forEach((points, row) => {
    const y = points.reduce((sum, tube) => sum + Number(tube.y), 0) / points.length;
    const top = `${scale(y, minY, maxY)}%`;
    addGridLine('row', scale(y, minY, maxY));
    addLabel(String(row), 'row-label', '3%', top, `행 ${row}`);
    addLabel(String(points.length), 'row-count', '97%', top, `행 ${row}: 표시 Tube ${points.length}개`);
  });
  columns.forEach((points, column) => {
    const x = points.reduce((sum, tube) => sum + Number(tube.x), 0) / points.length;
    addGridLine('column', scale(x, minX, maxX));
    addLabel(String(column), 'column-label', `${scale(x, minX, maxX)}%`, '28px', `열 ${column}`);
    addLabel(String(column), 'column-label', `${scale(x, minX, maxX)}%`, '94%', `X축 · 열 ${column}`);
  });

  validPoints.forEach(tube => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `precision-tube category-${String(tube.category || 'NOT_INSPECTED').toLowerCase()}`;
    const legendItem = legendByKey.get(lossKey(tube));
    button.style.backgroundColor = tubeColor(tube);
    button.style.border = '1px solid #7890a1';
    button.style.left = `${scale(tube.x, minX, maxX)}%`;
    button.style.top = `${scale(tube.y, minY, maxY)}%`;
    button.dataset.tubeId = tube.tube_id || '';
    button.title = `Tube ${tube.tube_no} · 행 ${tube.row ?? '미등록'} / 열 ${tube.column ?? '미등록'} · ${legendItem.label} · ${tube.wall_loss_percent == null ? '감육률 미등록' : `감육률 ${Number(tube.wall_loss_percent).toFixed(1)}%`}`;
    button.setAttribute('aria-label', button.title);
    button.setAttribute('aria-pressed', 'false');
    if (tube.tube_id) button.addEventListener('click', () => selectTube(Number(tube.tube_id), 'map'));
    mapCanvas.appendChild(button);
  });

  const metric = (label, value, tone = '') => `<div class="analysis-metric"><span>${label}</span><b class="${tone}">${value}</b></div>`;
  const fmt = (value, digits = 3) => value == null ? '-' : Number(value).toFixed(digits);
  function limitExceedanceDate(projections, allowableCount) {
    const count = Number(allowableCount);
    if (!Number.isInteger(count) || count < 0) return null;
    const dates = projections.map(row => row.projectedDate).filter(Number.isFinite).sort((a, b) => a - b);
    return dates[count] ?? null;
  }
  function updateRateAnalysis() {
    const multiplier = Number(rateSlider?.value || 1);
    const defect = defectByTube.get(selectedTubeId);
    const baseRate = defect?.long_term_corrosion_rate_mm_per_year;
    const rate = baseRate == null ? null : Number(baseRate) * multiplier;
    document.getElementById('long-term-rate').textContent = `${fmt(baseRate)} mm/yr`;
    const applied = document.getElementById('applied-corrosion-rate');
    applied.textContent = `${fmt(rate)} mm/yr`;
    applied.className = rate == null ? '' : rate >= .08 ? 'danger' : rate >= .04 ? 'warn' : 'good';
    const dayMs = 86400000;
    const projections = (lifeData.tube_projections || []).map(row => {
      const origin = Date.parse(`${row.projection_origin_date}T00:00:00Z`);
      const years = Number(row.years_from_measurement || 0) / multiplier;
      // Python timedelta dates use the whole elapsed days from the inspection date.
      const projectedDate = row.basis === 'ALREADY_PLUGGED' ? Date.parse(`${row.plugging_date}T00:00:00Z`) : origin + Math.floor(years * 365.2425) * dayMs;
      return { ...row, projectedDate, projectedYear: new Date(projectedDate).getUTCFullYear() };
    }).filter(row => Number.isFinite(row.projectedDate));
    const reachedDate = limitExceedanceDate(projections, lifeData.allowable_plugging_count);
    const reachedYear = reachedDate == null ? null : new Date(reachedDate).getUTCFullYear();
    const reachedDateText = reachedDate == null ? '한도 미도달' : new Date(reachedDate).toISOString().slice(0, 10);
    const remaining = reachedYear == null ? null : Math.max(reachedYear - Number(lifeData.current_year), 0);
    const asOf = Date.parse(`${lifeData.as_of_date}T00:00:00Z`);
    const currentCount = projections.filter(row => row.projectedDate <= asOf).length;
    const selected = projections.find(row => Number(row.tube_id) === selectedTubeId);
    const plugYear = defect?.plugging_complete ? '처리 완료' : defect?.plugging_threshold_reached ? '판정 기준 도달' : selected ? `${selected.projectedYear}년` : '산정 불가';
    document.getElementById('remaining-life-analysis').innerHTML = [
      metric('허용 Plugging 한도', `${lifeData.limit_percent ?? '-'}% (${lifeData.allowable_plugging_count ?? '-'}개)`),
      metric('기준일 누적 Plugging 대상(예측 포함)', `${currentCount}개`),
      metric('선택 Tube 예상', plugYear, defect?.plugging_complete || defect?.plugging_threshold_reached ? 'danger' : 'warn'),
      metric('열교환기 예상 잔여수명', remaining == null ? '한도 미도달' : `${remaining}년`, remaining != null && remaining <= 5 ? 'danger' : 'good'),
      metric('한도 초과 예상일', reachedDateText, reachedDate != null && reachedDate <= asOf ? 'danger' : ''),
      metric('계산 기준일', lifeData.as_of_date || '-')
    ].join('');
    document.querySelectorAll('[data-analysis-tube]').forEach(row => {
      const item = defectByTube.get(Number(row.dataset.analysisTube));
      // Measurement results stay unchanged when the prediction multiplier changes.
      row.classList.toggle('is-worst-loss', item?.wall_loss_percent === worstWallLoss);
    });
    const rates = projections.filter(row => row.calculation_method === 'LATEST_INSPECTION_INSTALLATION_AVERAGE' && row.corrosion_rate_mm_per_year > 0).map(row => row.corrosion_rate_mm_per_year * multiplier).sort((a, b) => a - b);
    const middle = Math.floor(rates.length / 2);
    const representative = rates.length ? rates.length % 2 ? rates[middle] : (rates[middle - 1] + rates[middle]) / 2 : null;
    const infoRate = document.querySelector('.analysis-info-bar .warning-value');
    if (infoRate) infoRate.textContent = fmt(representative);
  }
  function revealLinkedItem(container, item, headerHeight = 0) {
    if (!container || !item) return;
    const bounds = container.getBoundingClientRect(), target = item.getBoundingClientRect();
    const options = {behavior: 'auto'};
    if (target.top < bounds.top + headerHeight || target.bottom > bounds.bottom) {
      options.top = Math.max(0, container.scrollTop + target.top - bounds.top - headerHeight - (container.clientHeight - headerHeight - target.height) / 2);
    }
    if (target.left < bounds.left || target.right > bounds.right) {
      options.left = Math.max(0, container.scrollLeft + target.left - bounds.left - (container.clientWidth - target.width) / 2);
    }
    if ('top' in options || 'left' in options) container.scrollTo(options);
  }
  function syncTubeSelection(tubeId, source) {
    const mapButtons = [...document.querySelectorAll('.precision-tube')];
    const tableRows = [...document.querySelectorAll('[data-analysis-tube]')];
    const selectedButtons = mapButtons.filter(node => Number(node.dataset.tubeId) === Number(tubeId));
    const selectedRow = tableRows.find(node => Number(node.dataset.analysisTube) === Number(tubeId));
    mapButtons.forEach(node => {
      const selected = selectedButtons.includes(node);
      node.classList.toggle('selected', selected);
      node.setAttribute('aria-pressed', String(selected));
      node.classList.remove('linked-tube-pulse');
    });
    tableRows.forEach(node => {
      const selected = node === selectedRow;
      node.classList.toggle('selected', selected);
      node.setAttribute('aria-current', String(selected));
      node.classList.remove('linked-tube-pulse');
    });
    if (source === 'map' && selectedRow) {
      const viewport = selectedRow.closest('.analysis-table-scroll');
      const header = viewport?.querySelector('thead')?.getBoundingClientRect().height || 0;
      revealLinkedItem(viewport, selectedRow, header);
      void selectedRow.offsetWidth;
      selectedRow.classList.add('linked-tube-pulse');
    }
    if (source === 'table' && selectedButtons.length) {
      revealLinkedItem(mapNode, selectedButtons[0]);
      selectedButtons.forEach(node => { void node.offsetWidth; node.classList.add('linked-tube-pulse'); });
    }
    const status = document.getElementById('precision-linked-selection-status');
    if (status) {
      const tube = tubes.find(item => Number(item.tube_id) === Number(tubeId)) || defectByTube.get(Number(tubeId));
      status.textContent = `선택 Tube ${tube?.tube_no || tubeId}` +
        (!selectedRow ? ' · 부식측정결과 목록에 없는 Tube입니다(목록은 최근 감육률 0% 초과 결과).' : '') +
        (!selectedButtons.length ? ' · 현재 Map에 연결된 표시 위치가 없습니다.' : ' · Map과 결과표 선택 연결');
    }
  }
  function selectTube(tubeId, source = 'initial') {
    const defect = defectByTube.get(Number(tubeId));
    const tube = tubes.find(item => Number(item.tube_id) === Number(tubeId)) || (defect ? {
      ...defect, inspection_date: defect.measurement_date,
    } : null);
    if (!tube) return;
    selectedTubeId = Number(tubeId);
    const threeLink = document.getElementById('precision-3d-link');
    if (threeLink) {
      const url = new URL(threeLink.href, window.location.origin);
      url.searchParams.set('tube_id', String(selectedTubeId));
      threeLink.href = url.href;
    }
    syncTubeSelection(tubeId, source);
    document.getElementById('selected-tube-title').textContent = `Tube ${tube.tube_no} — 최근 두께 결과`;
    const nominal = Number(mapData.tube_spec?.nominal_thickness_mm || 0);
    const measured = Number(tube.minimum_wall_thickness_mm || 0);
    const percent = nominal > 0 ? Math.max(0, Math.min(100, measured / nominal * 100)) : 0;
    document.getElementById('thickness-history').innerHTML = `
      <div class="history-track"><i style="width:${percent}%"></i></div>
      <div class="history-caption"><span>${tube.inspection_date || '검사일 미등록'}</span><strong>${measured ? measured.toFixed(2) + ' mm' : '두께 미등록'}</strong></div>
      <a class="analysis-detail-link" href="/tubes/${tubeId}">전체 검사이력 및 2D 요약 보기 →</a>`;
    const rateForm = document.getElementById('corrosion-rate-form');
    // Keep the existing slider and listeners when switching the selected tube.
    if (rateForm) rateForm.remove();
    document.getElementById('corrosion-analysis').innerHTML = [
      metric('단기 부식속도', `${fmt(defect?.short_term_corrosion_rate_mm_per_year)} mm/yr`),
      `<div class="analysis-metric"><span>장기 부식속도</span><b id="long-term-rate"></b></div>`,
      `<div class="analysis-metric analysis-long-term"><div class="analysis-rate-label"><span>적용 부식속도</span><span id="corrosion-rate-slot"></span></div><b id="applied-corrosion-rate"></b></div>`,
      metric('산정 근거', defect?.corrosion_rate_selection_basis || '산정 불가')
    ].join('');
    if (rateForm) document.getElementById('corrosion-rate-slot').appendChild(rateForm);
    updateRateAnalysis();
  }

  document.querySelectorAll('[data-analysis-tube]').forEach(row => {
    const activate = () => selectTube(Number(row.dataset.analysisTube), 'table');
    row.addEventListener('click', activate);
    row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
  });
  if (defects.length) selectTube(Number(defects[0].tube_id));
})();
