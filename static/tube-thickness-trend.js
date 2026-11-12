((root) => {
  function series(history) {
    return history.filter(row => row.date && row.thickness_mm != null && typeof row.thickness_mm !== 'boolean'
      && String(row.thickness_mm).trim() !== '' && Number.isFinite(Number(row.thickness_mm)) && Number(row.thickness_mm) >= 0)
      .map(row => ({...row,time:Date.parse(`${row.date}T00:00:00Z`),value:Number(row.thickness_mm)}))
      .filter(row => Number.isFinite(row.time) && new Date(row.time).toISOString().slice(0,10) === row.date)
      .sort((a,b) => a.time-b.time || a.value-b.value);
  }
  function render(node,history,nominal,thresholdPercent,tubeNo) {
    node.replaceChildren();
    const points=series(history);
    if(!points.length) {node.textContent='그래프에 표시할 유효한 실제 측정값이 없습니다.';return;}
    const svg=(name,attrs={},text)=>{
      const element=document.createElementNS('http://www.w3.org/2000/svg',name);
      for(const [key,value] of Object.entries(attrs)) element.setAttribute(key,String(value));
      if(text!=null) element.textContent=text;
      return element;
    };
    const width=640,height=300,pad={left:60,right:26,top:32,bottom:42};
    let start=points[0].time,end=points.at(-1).time;
    if(start===end) {start-=180*86400000;end+=180*86400000;}
    const threshold=nominal>0?nominal*(1-thresholdPercent/100):null;
    const values=points.map(p=>p.value).concat(nominal>0?[nominal,threshold]:[]);
    const low=Math.max(0,Math.min(...values)*.9),high=Math.max(...values, .1)*1.08;
    const x=time=>pad.left+(time-start)/(end-start)*(width-pad.left-pad.right);
    const y=value=>height-pad.bottom-(value-low)/(high-low)*(height-pad.top-pad.bottom);
    const chart=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':`Tube ${tubeNo} 실제 검사 두께 추이 · 유효 측정 ${points.length}건`});
    for(let i=0;i<=4;i++) {
      const value=low+(high-low)*i/4;
      chart.append(svg('line',{x1:pad.left,x2:width-pad.right,y1:y(value),y2:y(value),stroke:'#d8e1e6','stroke-width':1}));
      chart.append(svg('text',{x:pad.left-8,y:y(value)+5,'text-anchor':'end',fill:'#526a79'},value.toFixed(2)));
      const time=start+(end-start)*i/4;
      chart.append(svg('text',{x:x(time),y:height-16,'text-anchor':i===0?'start':i===4?'end':'middle',fill:'#526a79'},new Date(time).toISOString().slice(0,10)));
    }
    chart.append(svg('text',{x:12,y:18,fill:'#526a79'},'두께 (mm)'));
    for(const [value,label,color] of [[nominal,'공칭두께','#6b7280'],[threshold,'Plugging 기준','#a3342c']]) {
      if(value==null||value<=0) continue;
      chart.append(svg('line',{x1:pad.left,x2:width-pad.right,y1:y(value),y2:y(value),stroke:color,'stroke-width':1,'stroke-dasharray':'4 3'}));
      chart.append(svg('text',{x:width-pad.right,y:y(value)-6,'text-anchor':'end',fill:color},`${label} ${value.toFixed(3)} mm`));
    }
    const current=new Map();
    for(const point of points) if(!point.historical&&!current.has(point.time)) current.set(point.time,point);
    if(current.size>1) chart.append(svg('polyline',{points:[...current.values()].map(p=>`${x(p.time)},${y(p.value)}`).join(' '),
      fill:'none',stroke:'#16846d','stroke-width':2}));
    for(const point of points) {
      const dot=svg('circle',{cx:x(point.time),cy:y(point.value),r:4,fill:point.historical?'#ffffff':'#16846d',stroke:point.historical?'#75828c':'#16846d','stroke-width':1.5});
      dot.append(svg('title',{},`${point.date} · ${point.value.toFixed(3)} mm${point.historical?' · 설치 이전 이력':''}`));
      chart.append(dot);
    }
    node.append(chart);
    const note=document.createElement('p');note.className='analysis-quality-note';
    note.textContent='실제 측정일과 측정 두께만 표시합니다. 회색 빈 원은 설치 이전 이력이며 현재 설치 이력의 선과 연결하지 않습니다.';
    node.append(note);
  }
  const api={series,render};
  if(typeof module!=='undefined'&&module.exports) module.exports=api;
  else root.TubeThicknessTrend=api;
})(globalThis);
