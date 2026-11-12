(() => {
  const rateSlider = document.getElementById('corrosion-rate-slider');
  let selectedTubeId = null;
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
  const defects = lifeData.analysis_tube_rows || lifeData.defect_rows || [];
  const worstWallLoss = (lifeData.defect_rows || []).reduce((worst, defect) => Math.max(worst, Number(defect.wall_loss_percent)), -Infinity);
  const defectByTube = new Map(defects.map(row => [Number(row.tube_id), row]));
  const validCoordinate = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
  const validPoints = tubes.filter(tube => validCoordinate(tube.x) && validCoordinate(tube.y));
  const palette = window.IrisWallLossPalette;
  const lossLegend = palette.bands;
  const legendByKey = new Map(lossLegend.map(item => [item.key, {...item, count: 0}]));
  const lossKey = tube => palette.tubeGrade(tube).key;
  const tubeColor = tube => palette.tubeGrade(tube).color;
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
    const total = document.createElement('div');
    total.className = 'wall-loss-legend-total';
    total.textContent = `표시 위치 합계 ${validPoints.length.toLocaleString('ko-KR')}개 (등록 튜브 ${validPoints.filter(tube => lossKey(tube) !== 'UNREGISTERED').length.toLocaleString('ko-KR')}개 · 미등록 위치 ${validPoints.filter(tube => lossKey(tube) === 'UNREGISTERED').length.toLocaleString('ko-KR')}개)`;
    legendNode.appendChild(total);
  }
  const xs = validPoints.map(tube => Number(tube.x));
  const ys = validPoints.map(tube => Number(tube.y));
  const minX = xs.length ? Math.min(...xs) : 0, maxX = xs.length ? Math.max(...xs) : 1;
  const minY = ys.length ? Math.min(...ys) : 0, maxY = ys.length ? Math.max(...ys) : 1;
  const scale = (value, min, max) => max === min ? 50 : 11.6 + ((Number(value) - min) / (max - min)) * 76.8;
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
  if (mapData.layout?.pdf_vector_display_applied) {
    const ratio = Math.max(maxX - minX, 1) / Math.max(maxY - minY, 1);
    const fitPdfCanvas = () => {
      const width = Math.min(mapNode.clientWidth, mapNode.clientHeight * ratio);
      mapCanvas.style.minWidth = '0'; mapCanvas.style.minHeight = '0';
      mapCanvas.style.width = `${Math.max(1, width)}px`;
      mapCanvas.style.height = `${Math.max(1, width / ratio)}px`;
      mapCanvas.style.marginInline = 'auto';
    };
    fitPdfCanvas();
    new ResizeObserver(fitPdfCanvas).observe(mapNode);
  }

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
    button.style.border = lossKey(tube) === 'UNREGISTERED' ? '1px dashed #64748b' : '1px solid #7890a1';
    button.style.left = `${scale(tube.x, minX, maxX)}%`;
    button.style.top = `${scale(tube.y, minY, maxY)}%`;
    button.dataset.tubeId = tube.tube_id || '';
    button.title = `Tube ${tube.tube_no} · 행 ${tube.row ?? '미등록'} / 열 ${tube.column ?? '미등록'} · ${legendItem.label} · ${lossKey(tube) === 'UNREGISTERED' ? '표시용 위치 · 운전 상태와 검사 여부 미확인' : tube.wall_loss_percent == null ? '감육률 미등록' : `감육률 ${Number(tube.wall_loss_percent).toFixed(1)}%`}`;
    button.setAttribute('aria-label', button.title);
    button.setAttribute('aria-pressed', 'false');
    if (tube.tube_id) button.addEventListener('click', () => selectTube(Number(tube.tube_id), 'map'));
    mapCanvas.appendChild(button);
  });

  const metric = (label, value, tone = '') => `<div class="analysis-metric"><span>${label}</span><b class="${tone}">${value}</b></div>`;
  const fmt = (value, digits = 3) => value == null ? '-' : Number(value).toFixed(digits);
  function projectTubeDates(rows, multiplier) {
    if (!Number.isFinite(multiplier) || multiplier <= 0) return [];
    const maxDate = Date.parse('9999-12-31T00:00:00Z');
    return rows.filter(row => row.basis === 'ALREADY_PLUGGED'
      || (row.years_from_measurement != null && Number.isFinite(Number(row.years_from_measurement))
          && Number(row.years_from_measurement) >= 0)).map(row => {
      const origin = Date.parse(`${row.projection_origin_date}T00:00:00Z`);
      const years = Number(row.years_from_measurement) / multiplier;
      const projectedDate = row.basis === 'ALREADY_PLUGGED'
        ? Date.parse(`${row.plugging_date}T00:00:00Z`)
        : origin + Math.floor(years * 365.2425) * 86400000;
      return {...row, projectedDate, projectedYear: new Date(projectedDate).getUTCFullYear()};
    }).filter(row => Number.isFinite(row.projectedDate) && row.projectedDate <= maxDate
      && row.projectedYear >= 1);
  }
  function pluggingBarColor(count, limit) {
    return count > limit ? '#dc2626' : count > limit * 0.7 ? '#d97706' : '#0d9488';
  }
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
    document.getElementById('long-term-rate').textContent = fmt(baseRate,4);
    const applied = document.getElementById('applied-corrosion-rate');
    applied.textContent = fmt(rate,4);
    applied.className = rate == null ? '' : rate >= .08 ? 'danger' : rate >= .04 ? 'warn' : 'good';
    const projections = projectTubeDates(lifeData.tube_projections || [], multiplier);
    const reachedDate = limitExceedanceDate(projections, lifeData.allowable_plugging_count);
    const reachedYear = reachedDate == null ? null : new Date(reachedDate).getUTCFullYear();
    const reachedDateText = reachedDate == null ? '가용 데이터에서 한도 미도달' : new Date(reachedDate).toISOString().slice(0, 10);
    const remaining = reachedYear == null ? null : Math.max(reachedYear - Number(lifeData.current_year), 0);
    const asOf = Date.parse(`${lifeData.as_of_date}T00:00:00Z`);
    const currentCount = projections.filter(row => row.projectedDate <= asOf).length;
    const futureCount = projections.filter(row => row.projectedDate > asOf && row.basis !== 'ALREADY_PLUGGED' && !defectByTube.get(Number(row.tube_id))?.plugging_threshold_reached).length;
    renderAnnualPlugging(projections, Number(lifeData.current_year), lifeData.allowable_plugging_count);
    const selected = projections.find(row => Number(row.tube_id) === selectedTubeId);
    const plugYear = defect?.plugging_complete ? '처리 완료' : defect?.plugging_threshold_reached ? '최근 검사에서 기준 도달 확인 — 실제 도달일 미상' : selected ? `${selected.projectedYear}년` : '산정 불가';
    document.getElementById('remaining-life-analysis').innerHTML = [
      metric('허용 Plugging 한도', `${lifeData.limit_percent ?? '-'}% (${lifeData.allowable_plugging_count ?? '-'}개)`),
      metric('실제 Plugging 완료 수량', `${lifeData.actual_plugged_count ?? 0}개`),
      metric('Plugging 기준 도달 대상 수량', `${lifeData.threshold_reached_count ?? 0}개`),
      metric('향후 Plugging 예상 수량', `${futureCount}개`),
      metric('기준일 누적 예측 대상 (실제 완료 포함)', `${currentCount}개`),
      metric('선택 Tube 예상', plugYear, defect?.plugging_complete || defect?.plugging_threshold_reached ? 'danger' : 'warn'),
      metric('열교환기 예상 잔여수명', remaining == null ? (projections.length ? '가용 데이터에서 한도 미도달' : '산정 불가') : `${remaining}년`, remaining == null ? '' : remaining <= 5 ? 'danger' : 'good'),
      metric('배율 적용 후 날짜 범위 밖', `${(lifeData.tube_projections || []).length - projections.length}개`),
      metric('한도 초과 예상일', reachedDateText, reachedDate != null && reachedDate <= asOf ? 'danger' : ''),
      metric('계산 기준일', lifeData.as_of_date || '-'),
      metric('그래프 표시 종료 연도', `${Number(lifeData.current_year) + 25}년 (한도 판정 기간과 별개)`)
    ].join('');
    let scopeNote = document.getElementById('remaining-life-scope-note');
    if (!scopeNote) {
      scopeNote = document.createElement('p');
      scopeNote.id = 'remaining-life-scope-note';
      scopeNote.className = 'analysis-quality-note';
      document.getElementById('remaining-life-analysis').after(scopeNote);
    }
    const unregistered = lifeData.unregistered_tube_count == null ? '미등록 수량은 미확인이며 평가에서 제외됩니다.' : `미등록 ${Number(lifeData.unregistered_tube_count).toLocaleString('ko-KR')}개는 평가에서 제외됩니다.`;
    scopeNote.textContent = `예측 가능한 등록 튜브 중 향후 추가 도달 대상 ${futureCount}개이며, ${unregistered} 설비 최근 검사일: ${lifeData.equipment_summary?.latest_inspection_date || '미확인'} · 계산 기준일: ${lifeData.as_of_date || '미확인'}. 기준 도달 수량은 각 튜브의 최근 검사값에 따른 판정이며 실제 작업 완료나 계산 기준일의 재측정 결과를 뜻하지 않습니다.`;
    document.querySelectorAll('[data-analysis-tube]').forEach(row => {
      const item = defectByTube.get(Number(row.dataset.analysisTube));
      // Measurement results stay unchanged when the prediction multiplier changes.
      row.classList.toggle('is-worst-loss', item?.wall_loss_percent === worstWallLoss);
      const appliedCell = row.querySelector('[data-applied-rate]');
      if (appliedCell) appliedCell.textContent = fmt(item?.long_term_corrosion_rate_mm_per_year == null ? null : item.long_term_corrosion_rate_mm_per_year * multiplier,4);
      const forecastCell = row.querySelector('[data-analysis-forecast]');
      const projected = projections.find(p => Number(p.tube_id) === Number(row.dataset.analysisTube));
      if (forecastCell) forecastCell.textContent = item?.plugging_complete ? '처리 완료' : item?.plugging_threshold_reached ? '검사 시 기준 도달' : projected ? `${projected.projectedYear}년` : '산정 불가';
    });
    const rates = projections.filter(row => row.calculation_method === 'LATEST_INSPECTION_INSTALLATION_AVERAGE' && row.corrosion_rate_mm_per_year > 0).map(row => row.corrosion_rate_mm_per_year * multiplier).sort((a, b) => a - b);
    const middle = Math.floor(rates.length / 2);
    const representative = rates.length ? rates.length % 2 ? rates[middle] : (rates[middle - 1] + rates[middle]) / 2 : null;
    const infoRate = document.querySelector('.analysis-info-bar .warning-value');
    if (infoRate) infoRate.textContent = fmt(representative);
  }
  function annualPluggingSeries(projections, startYear, endYear) {
    const valid = projections.filter(row => Number.isFinite(row.projectedDate));
    const rows = [];
    for (let year = startYear; year <= endYear; year++) {
      const end = Date.UTC(year + 1, 0, 1);
      const start = Date.UTC(year, 0, 1);
      rows.push({year, cumulative: valid.filter(row => row.projectedDate < end).length,
        added: valid.filter(row => row.projectedDate >= start && row.projectedDate < end).length});
    }
    return rows;
  }
  function renderAnnualPlugging(projections, startYear, allowable) {
    const node = document.getElementById('annual-plugging-chart');
    const table = document.getElementById('annual-plugging-table');
    if (!node || !table) return;
    if (!projections.length) {
      node.textContent = '계산 가능한 Tube 예측 데이터가 없습니다.';
      table.replaceChildren();
      return;
    }
    const rows = annualPluggingSeries(projections, startYear, startYear + 25);
    const limit = Number(allowable);
    const max = Math.max(1, limit, ...rows.map(row => row.cumulative));
    const left = 55, top = 25, height = 180, width = 800, step = width / rows.length;
    const y = count => top + height * (1 - count / max);
    const bars = rows.map((row, index) => `<rect x="${left + index * step + 3}" y="${y(row.cumulative)}" width="${step - 6}" height="${height * row.cumulative / max}" fill="${pluggingBarColor(row.cumulative, limit)}"><title>${row.year}년: 누적 ${row.cumulative}개 / 당해 ${row.added}개</title></rect>${index % 5 === 0 ? `<text x="${left + index * step}" y="225" font-size="12" fill="currentColor">${row.year}</text>` : ''}`).join('');
    node.innerHTML = `<svg viewBox="0 0 900 250" style="width:100%;min-width:520px;max-height:320px" role="img" aria-label="${startYear}년부터 25년간 누적 예측. 허용 ${limit}개"><text x="8" y="20" fill="currentColor" font-size="12">수량(개)</text><text x="8" y="${top + 8}" fill="currentColor" font-size="12">${max}</text><text x="30" y="${top + height}" fill="currentColor" font-size="12">0</text>${bars}<line x1="${left}" x2="${left + width}" y1="${y(limit)}" y2="${y(limit)}" stroke="#b45309" stroke-width="2" stroke-dasharray="6 4"/><text x="${left}" y="${Math.max(13, y(limit) - 5)}" fill="currentColor" font-size="12">허용 한도 ${limit}개 (초과 시 도달)</text></svg>`;
    const beyond = projections.filter(row => row.projectedDate >= Date.UTC(startYear + 26, 0, 1)).length;
    const note = document.createElement('p');
    note.textContent = `녹색: 허용 한도의 70% 이하 / 황색: 70% 초과~한도 이하 / 적색: 한도 초과. 표시 기간: ${startYear}~${startYear + 25}년. 기간 이후 예상 ${beyond}개. 이전 연도 도달분은 누적에 포함됩니다.`;
    node.appendChild(note);
    table.innerHTML = `<table><thead><tr><th>연도</th><th>당해 도달</th><th>누적 대상</th><th>허용 한도</th></tr></thead><tbody>${rows.map(row => `<tr><td>${row.year}</td><td>${row.added}</td><td>${row.cumulative}</td><td>${limit}</td></tr>`).join('')}</tbody></table>`;
  }

  function renderThicknessHistory(tubeId, nominal) {
    const node = document.getElementById('thickness-history');
    node.replaceChildren();
    const history = lifeData.tube_histories?.[String(tubeId)] || [];
    if (!history.length) node.textContent = '등록된 실제 검사이력이 없습니다.';
    history.forEach(item => {
      const row = document.createElement('div');
      row.className = 'history-measurement';
      row.style.marginBottom = '10px';
      const thickness = item.thickness_mm;
      const valid = thickness != null && Number.isFinite(Number(thickness)) && Number(thickness) >= 0;
      const caption = document.createElement('div');
      caption.textContent = `${item.date || '검사일 미등록'} · ${valid ? Number(thickness).toFixed(2) + ' mm' : '유효 두께 미등록'}${item.historical ? ' · 설치 이전 이력(조회 전용)' : ''}`;
      row.appendChild(caption);
      if (valid && nominal > 0) {
        const track = document.createElement('div'); track.className = 'history-track';
        const bar = document.createElement('i');
        bar.style.width = `${Math.max(0, Math.min(100, Number(thickness) / nominal * 100))}%`;
        track.appendChild(bar); row.appendChild(track);
      }
      const link = document.createElement('a');
      link.href = `/inspections/${Number(item.inspection_id)}`;
      link.textContent = `검사 원문 보기 · 결과 #${item.result_id}`;
      row.appendChild(link);
      if (item.pdf_url) {
        const pdf = document.createElement('a');
        pdf.href = item.pdf_url; pdf.target = '_blank'; pdf.rel = 'noopener';
        pdf.textContent = '검사 PDF ↗'; pdf.className = 'analysis-pdf-shortcut';
        row.appendChild(pdf);
      }
      node.appendChild(row);
    });
    const link = document.createElement('a');
    link.href = `/tubes/${Number(tubeId)}`; link.textContent = '전체 검사이력 및 상태 관리 →';
    node.appendChild(link);
    node.style.maxHeight = '340px'; node.style.overflowY = 'auto';
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
        (!selectedRow ? ' · 최근 측정 결과가 없는 Tube입니다.' : '') +
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
    document.getElementById('selected-tube-title').textContent = `Tube ${tube.tube_no} — 실제 다년도 두께 이력`;
    const nominal = Number(mapData.tube_spec?.nominal_thickness_mm || 0);
    renderThicknessHistory(tubeId, nominal);
    const trend = document.getElementById('thickness-trend');
    if (trend && window.TubeThicknessTrend) {
      trend.dataset.tubeId = String(tubeId);
      window.TubeThicknessTrend.render(trend, lifeData.tube_histories?.[String(tubeId)] || [],
        nominal,Number(lifeData.plugging_wall_loss_percent || 40),tube.tube_no);
    }
    const rateForm = document.getElementById('corrosion-rate-form');
    // Keep the existing slider and listeners when switching the selected tube.
    if (rateForm) rateForm.remove();
    const selectedTable = document.createElement('table');
    selectedTable.className = 'selected-tube-table';
    const body = document.createElement('tbody');
    const fields = [
      ['최근 측정일',defect?.measurement_date || tube.inspection_date || '-'],
      ['최근 측정 두께 (mm)',fmt(defect?.minimum_wall_thickness_mm ?? tube.minimum_wall_thickness_mm,3)],
      ['감육률 (%)',fmt(defect?.wall_loss_percent ?? tube.wall_loss_percent,2)],
      ['단기 감육속도(mm/년)',fmt(defect?.short_term_corrosion_rate_mm_per_year,4),'short-term-rate'],
      ['장기 감육속도(mm/년)','-','long-term-rate'],
      ['감육속도(mm/년)','-','applied-corrosion-rate'],
      ['선정 근거',defect?.corrosion_rate_selection_basis ? '장기 평균 × 배율' : '산정 불가'],
    ];
    for (const [label,value,id] of fields) {
      const row = document.createElement('tr'), heading = document.createElement('th'), cell = document.createElement('td'), number = document.createElement('b');
      heading.scope='row'; heading.textContent=label; number.textContent=value;
      if(id) number.id=id;
      if(id==='short-term-rate' && defect?.short_term_status==='NON_POSITIVE') number.className='non-positive-short-rate';
      cell.appendChild(number);
      if(id==='applied-corrosion-rate') {const slot=document.createElement('span');slot.id='corrosion-rate-slot';cell.appendChild(slot);}
      row.appendChild(heading);row.appendChild(cell);body.appendChild(row);
    }
    selectedTable.appendChild(body);
    const analysis=document.getElementById('corrosion-analysis');
    analysis.replaceChildren(selectedTable);analysis.dataset.tubeId=String(tubeId);
    const shortNote=document.createElement('p');shortNote.className='analysis-quality-note';
    shortNote.textContent=defect?.short_term_previous_date ?
      `단기 계산: (${fmt(defect.short_term_previous_thickness_mm,3)} − ${fmt(defect.short_term_current_thickness_mm,3)}) mm ÷ ${fmt(defect.short_term_elapsed_years,3)}년 · ${defect.short_term_previous_date} ~ ${defect.short_term_current_date}${defect.short_term_status==='NON_POSITIVE'?' · 0 이하 값은 측정 편차 확인 대상입니다.':''}` : '단기 감육속도는 최근 두 유효 측정 두께가 있어야 계산합니다.';
    analysis.appendChild(shortNote);
    if (rateForm) document.getElementById('corrosion-rate-slot').appendChild(rateForm);
    updateRateAnalysis();
  }

  document.querySelectorAll('[data-analysis-tube]').forEach(row => {
    const activate = () => selectTube(Number(row.dataset.analysisTube), 'table');
    row.addEventListener('click', activate);
    row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); activate(); } });
  });
  const initialTube=defects[0]?.tube_id || tubes.find(tube => tube.tube_id)?.tube_id;
  if (initialTube) selectTube(Number(initialTube));
  else renderAnnualPlugging((lifeData.tube_projections || []).map(row => ({projectedDate: Date.parse(`${row.plugging_date}T00:00:00Z`)})), Number(lifeData.current_year), lifeData.allowable_plugging_count);
})();

document.querySelectorAll('[data-pdf-reports-open]').forEach(link => {
  link.addEventListener('click', () => {
    const reports = document.getElementById('analysis-pdf-reports');
    if (reports) reports.open = true;
  });
});
