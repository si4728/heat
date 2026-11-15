(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.TextSqlCharts = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const metadata = /(?:^|_)(?:id|code|tag|name|year|row|column|page)$|^(?:source_page|location_mm|row_no|column_no|pass_no|lifecycle_no)$/i;
  const counts = /(?:^|_)count$|_tubes$/i;
  function number(value) {
    if (typeof value === 'number') return Number.isFinite(value) ? value : null;
    if (typeof value !== 'string' || !/^-?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value.trim())) return null;
    const parsed = Number(value); return Number.isFinite(parsed) ? parsed : null;
  }
  function describe(result) {
    const rows = result.rows || [], columns = result.columns || Object.keys(rows[0] || {});
    const metrics = columns.filter(key => !metadata.test(key) && rows.some(row => number(row[key]) !== null));
    const categories = columns.filter(key => !metrics.includes(key) && rows.some(row => row[key] != null));
    const preferred = ['tube_no', 'source_tube_id', 'year', 'inspection_year', 'inspection_date', 'latest_inspection_date', 'equipment_tag', 'unit_code', 'equipment_name'];
    return {metrics, categories, metric:metrics.includes('inspection_count') ? 'inspection_count' : metrics[0],
      category:preferred.find(key => categories.includes(key)) || categories[0] || ''};
  }
  function points(result, metric, category) {
    const rows = result.rows || [];
    const values = rows.map((row, index) => {
      let label = category ? String(row[category] ?? '미등록') : (rows.length === 1 ? '집계 결과' : `${index + 1}행`);
      if (['tube_no', 'source_tube_id'].includes(category) && row.equipment_tag) label = `${row.equipment_tag} · ${label}`;
      return {label, value:number(row[metric]), categoryValue:row[category], index};
    });
    const seen = new Map();
    values.forEach(point => seen.set(point.label, (seen.get(point.label) || 0) + 1));
    return values.map(point => ({...point, label:seen.get(point.label) > 1 ? `${point.label} (${point.index + 1}행)` : point.label}));
  }
  function pie(points, metric) {
    if (!counts.test(metric)) return {reason:'파이는 검사 횟수·튜브 수처럼 합산 가능한 건수 항목에서 사용할 수 있습니다.'};
    const valid = points.filter(point => point.value !== null);
    if (valid.length < 2 || valid.some(point => point.value < 0)) return {reason:'파이는 음수가 없는 두 행 이상의 수치가 필요합니다.'};
    const total = valid.reduce((sum, point) => sum + point.value, 0);
    if (!Number.isFinite(total) || total <= 0) return {reason:'파이를 표시하려면 유효한 양수 합계가 필요합니다.'};
    const sorted = [...valid].sort((a,b) => b.value - a.value || a.index - b.index);
    const slices = sorted.length > 5 ? [...sorted.slice(0,4), {label:`기타 ${sorted.length - 4}행`, value:sorted.slice(4).reduce((sum,p) => sum+p.value,0)}] : sorted;
    return {total, slices};
  }
  function time(value, key) {
    if (/(?:^|_)year$/.test(key) && /^\d{4}$/.test(String(value))) {
      const year = Number(value); return year >= 1000 && year <= 9999 ? Date.UTC(year,0,1) : null;
    }
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}(?:$|[ T])/.test(value)) return null;
    const day = value.slice(0,10), parsed = Date.parse(`${day}T00:00:00Z`);
    return Number.isFinite(parsed) && new Date(parsed).toISOString().slice(0,10) === day ? parsed : null;
  }
  function line(points, category) {
    const series = points.map(point => ({...point, time:time(point.categoryValue, category)}));
    if (series.some(point => point.time === null)) return {reason:'선 그래프는 날짜 또는 연도 항목을 분류 기준으로 선택해야 합니다.'};
    if (new Set(series.map(point => point.time)).size !== series.length) return {reason:'같은 날짜의 행이 여러 개입니다. 날짜별 한 행으로 조회한 결과에서 선 그래프를 사용할 수 있습니다.'};
    if (series.filter(point => point.value !== null).length < 2) return {reason:'선 그래프에는 서로 다른 날짜의 유효 수치가 두 개 이상 필요합니다.'};
    return {series:[...series].sort((a,b) => a.time-b.time)};
  }
  function format(value) {
    if (value !== 0 && (Math.abs(value) >= 1e8 || Math.abs(value) < .0001)) return value.toExponential(3);
    return new Intl.NumberFormat('ko-KR', {maximumFractionDigits:6}).format(value);
  }
  function mount(panel, labels = {}) {
    if (!panel) return null;
    const get = key => panel.querySelector(`[data-chart="${key}"]`);
    const metric = get('metric'), category = get('category'), type = get('type'), area = get('area'), note = get('note'), hint = get('hint');
    let result = null;
    const caption = key => typeof labels[key] === 'string' ? labels[key] : key;
    const ns = 'http://www.w3.org/2000/svg';
    function svgNode(tag, attributes, text) {
      const node = document.createElementNS(ns, tag);
      Object.entries(attributes || {}).forEach(([key,value]) => node.setAttribute(key,String(value)));
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function text(svg, x, y, value, anchor = 'start') { svg.append(svgNode('text',{x,y,'text-anchor':anchor},value)); }
    function chartSvg(width, height, title) {
      const svg = svgNode('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'img','aria-label':title});
      svg.append(svgNode('title',{},title)); area.append(svg); return svg;
    }
    function extent(data) {
      const values = data.filter(p => p.value !== null).map(p => p.value);
      const min = Math.min(0,...values), max = Math.max(0,...values);
      return {min,max,range:max-min || 1};
    }
    function drawBar(data, width) {
      const valid = data.filter(point => point.value !== null), axis = extent(valid);
      if (!Number.isFinite(axis.range)) { hint.textContent = '수치 범위가 너무 커서 차트를 표시할 수 없습니다.'; return; }
      const left = width < 560 ? Math.min(112,width*.36) : 200, right = Math.min(86,width*.25), plot = width-left-right;
      const x = value => left + (value-axis.min)/axis.range*plot;
      const svg = chartSvg(width,44+valid.length*36,`${caption(metric.value)} 막대 그래프`);
      [axis.min, (axis.min+axis.max)/2, axis.max].filter((v,i,a) => a.indexOf(v)===i).forEach(value => {
        svg.append(svgNode('line',{x1:x(value),x2:x(value),y1:28,y2:32+valid.length*36,class:'sql-chart-grid'}));
        text(svg,x(value),18,format(value),'middle');
      });
      valid.forEach((point,i) => {
        const y = 34+i*36;
        const label = svgNode('text',{x:left-10,y:y+16,'text-anchor':'end'},shortLabel(point.label,width < 560 ? Math.floor(left/6)-2 : 30));
        label.append(svgNode('title',{},point.label)); svg.append(label);
        const rect = svgNode('rect',{x:Math.min(x(0),x(point.value)),y,width:Math.abs(x(point.value)-x(0)),height:23,class:'sql-chart-bar'});
        rect.append(svgNode('title',{},`${point.label}: ${format(point.value)}`)); svg.append(rect);
        text(svg,width-8,y+16,format(point.value),'end');
      });
    }
    function shortLabel(label, budget) {
      let used=0, output='';
      for (const char of label) { used += char.charCodeAt(0)>255 ? 2 : 1; if (used>budget) return output+'…'; output+=char; }
      return output;
    }
    function drawPie(data, width) {
      const model = pie(data,metric.value);
      if (model.reason) { hint.textContent=model.reason; return; }
      const figureWidth=Math.min(width,320);
      const svg=chartSvg(figureWidth,260,`${caption(metric.value)} 행별 비중`), cx=figureWidth/2, cy=130, radius=104;
      const colors=['#c45a0c','#64717c','#a3aeb7','#d7dde1','#303d47'];
      let angle=-Math.PI/2;
      const list=document.createElement('ul'); list.className='sql-chart-legend';
      model.slices.forEach((slice,i) => {
        const end=angle+slice.value/model.total*Math.PI*2;
        let shape;
        if (slice.value===model.total) shape=svgNode('circle',{cx,cy,r:radius,fill:colors[i]});
        else if (slice.value>0) shape=svgNode('path',{d:`M ${cx} ${cy} L ${cx+radius*Math.cos(angle)} ${cy+radius*Math.sin(angle)} A ${radius} ${radius} 0 ${end-angle>Math.PI?1:0} 1 ${cx+radius*Math.cos(end)} ${cy+radius*Math.sin(end)} Z`,fill:colors[i]});
        const share=(slice.value/model.total*100).toFixed(1);
        if (shape) { shape.append(svgNode('title',{},`${slice.label}: ${format(slice.value)} (${share}%)`)); svg.append(shape); }
        const item=document.createElement('li'), swatch=document.createElement('span'), name=document.createElement('span'), value=document.createElement('strong');
        swatch.className='sql-chart-swatch'; swatch.style.backgroundColor=colors[i]; swatch.setAttribute('aria-hidden','true');
        name.textContent=slice.label; value.textContent=`${format(slice.value)} · ${share}%`;
        item.append(swatch,name,value); list.append(item); angle=end;
      });
      area.append(list); hint.textContent=`표시된 행의 수치 합계 ${format(model.total)} 기준 비중입니다. 5개를 넘는 항목은 작은 값부터 ‘기타’로 합칩니다.`;
    }
    function drawLine(data,width) {
      const model=line(data,category.value);
      if (model.reason) { hint.textContent=model.reason; return; }
      const axis=extent(data);
      if (!Number.isFinite(axis.range)) { hint.textContent='수치 범위가 너무 커서 차트를 표시할 수 없습니다.'; return; }
      const height=290, left=64, right=24, top=20, bottom=58;
      const first=model.series[0].time, last=model.series.at(-1).time;
      const x=t => left+(t-first)/(last-first)*(width-left-right);
      const y=v => height-bottom-(v-axis.min)/axis.range*(height-top-bottom);
      const svg=chartSvg(width,height,`${caption(metric.value)} 날짜별 선 그래프`);
      for(let i=0;i<4;i++) {
        const value=axis.min+axis.range*i/3;
        svg.append(svgNode('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),class:'sql-chart-grid'}));
        text(svg,left-8,y(value)+4,format(value),'end');
      }
      const ticks=[];
      const yearly=/(?:^|_)year$/.test(category.value);
      if(yearly) {
        const startYear=new Date(first).getUTCFullYear(), endYear=new Date(last).getUTCFullYear();
        const step=Math.max(1,Math.ceil((endYear-startYear)/(width<560?2:4)));
        for(let year=startYear;year<=endYear;year+=step) ticks.push(Date.UTC(year,0,1));
      } else {
        const day=86400000, step=Math.max(day,Math.ceil((last-first)/(width<560?1:3)/day)*day);
        for(let stamp=first;stamp<=last;stamp+=step) ticks.push(stamp);
      }
      if(ticks.at(-1)!==last) ticks.push(last);
      ticks.forEach((stamp,i) => {
        const label=yearly ? String(new Date(stamp).getUTCFullYear()) : new Date(stamp).toISOString().slice(0,10);
        text(svg,x(stamp),height-22,label,i===0?'start':i===ticks.length-1?'end':'middle');
      });
      let segment=[];
      const flush=() => { if(segment.length>1) svg.append(svgNode('polyline',{points:segment.join(' '),class:'sql-chart-line'})); segment=[]; };
      model.series.forEach(point => {
        if(point.value===null) { flush(); return; }
        segment.push(`${x(point.time)},${y(point.value)}`);
        const marker=svgNode('circle',{cx:x(point.time),cy:y(point.value),r:4,class:'sql-chart-point'});
        marker.append(svgNode('title',{},`${point.label}: ${format(point.value)}`)); svg.append(marker);
      }); flush();
      hint.textContent='날짜순으로 표시합니다. 누락된 수치는 0으로 바꾸거나 선으로 연결하지 않습니다.';
    }
    function render() {
      if (!result || !metric.value) return;
      area.replaceChildren(); hint.textContent='';
      const data=points(result,metric.value,category.value), valid=data.filter(p => p.value!==null);
      const pieModel=pie(data,metric.value), lineModel=line(data,category.value);
      type.querySelector('[value="pie"]').disabled=!!pieModel.reason;
      type.querySelector('[value="line"]').disabled=!!lineModel.reason;
      // A previously valid selection may become unsuitable after changing fields.
      if (type.value==='pie' && pieModel.reason || type.value==='line' && lineModel.reason) type.value='bar';
      area.classList.toggle('is-pie',type.value==='pie');
      note.textContent=`현재 표에 반환된 ${data.length}행 기준 · 유효 수치 ${valid.length}행 · 결측 ${data.length-valid.length}행 제외. 전체 DB의 분포를 뜻하지 않습니다.${result.limit_reached ? ' 조회 개수 제한에 도달한 결과입니다.' : ''}`;
      if(!valid.length) { hint.textContent='선택한 항목에 표시할 유효 수치가 없습니다.'; return; }
      const width=Math.max(220,Math.floor(area.clientWidth));
      if(type.value==='pie') drawPie(data,width);
      else if(type.value==='line') drawLine(data,width);
      else { drawBar(data,width); if (!hint.textContent) hint.textContent=[pieModel.reason,lineModel.reason].filter(Boolean).join(' '); }
    }
    function clear(message='SQL 실행 후 조회 결과를 차트로 확인할 수 있습니다.') {
      result=null; metric.replaceChildren(); category.replaceChildren();
      [metric,category,type].forEach(control => { control.disabled=true; });
      area.replaceChildren(); area.classList.remove('is-pie'); note.textContent='차트는 결과 표의 데이터만 사용합니다.'; hint.textContent=message;
    }
    function setResult(value) {
      clear(); result=value;
      const fields=describe(value);
      if(!value.rows?.length) { hint.textContent='조회 결과가 없어 차트를 표시하지 않습니다.'; return; }
      if(!fields.metrics.length) { hint.textContent='ID를 제외한 수치 항목이 없어 차트를 표시할 수 없습니다.'; return; }
      fields.metrics.forEach(key => metric.add(new Option(caption(key),key)));
      if(!fields.categories.length) category.add(new Option('조회 행',''));
      else fields.categories.forEach(key => category.add(new Option(caption(key),key)));
      metric.value=fields.metric; category.value=fields.category; type.value='bar';
      metric.disabled=false; type.disabled=false; category.disabled=!fields.categories.length;
      render();
    }
    [metric,category,type].forEach(control => control.addEventListener('change',render));
    let previousWidth=0;
    if (typeof ResizeObserver!=='undefined') new ResizeObserver(() => {
      const width=area.clientWidth; if(width!==previousWidth) { previousWidth=width; render(); }
    }).observe(area);
    clear();
    return {clear,setResult};
  }
  return {number,describe,points,pie,line,mount};
});
