(() => {
  'use strict';
  const root=document.getElementById('plugging-operations');
  if(!root) return;
  const el=id=>document.getElementById('plugging-'+id);
  const selected=new Set(); let state=null,busy=false,retry=null;
  async function request(data) {
    const response=await fetch(root.dataset.url,{method:data?'POST':'GET',credentials:'same-origin',
      headers:data?{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf}:{},
      body:data?JSON.stringify(data):undefined});
    if(response.redirected) throw new Error('로그인 상태를 확인한 뒤 새로고침하세요.');
    if(!(response.headers.get('content-type')||'').includes('application/json')) throw new Error('조회·정비 편집 권한을 확인하세요.');
    const payload=await response.json();
    if(!response.ok) throw new Error(payload.error||'완료 등록을 처리하지 못했습니다.');
    return payload;
  }
  function update() {
    el('selection').textContent=selected.size?`실제 등록 튜브 ${selected.size}본 선택`:'선택한 튜브 없음';
    el('complete').disabled=busy||!state||!selected.size;
    document.querySelectorAll('#precision-tube-map [data-tube-id]').forEach(b=>{
      const on=selected.has(Number(b.dataset.tubeId));
      b.style.outline=on?'3px solid #111827':'';
      if(el('select-mode').checked) b.setAttribute('aria-pressed',String(on));
    });
  }
  document.addEventListener('plugging-select-tube',event=>{
    if(busy) return;
    const id=event.detail.tubeId;
    if(!state?.versions[String(id)]) return;
    if(selected.has(id)) selected.delete(id); else selected.add(id);
    update();
  });
  document.addEventListener('plugging-select-single',event=>{
    if(busy||el('select-mode').checked) return;
    selected.clear();
    if(state?.versions[String(event.detail.tubeId)]) selected.add(event.detail.tubeId);
    update();
  });
  el('clear').addEventListener('click',()=>{if(!busy){selected.clear();update();}});
  el('select-mode').addEventListener('change',update);
  async function save(data) {
    if(busy) return;
    busy=true;update();
    el('status').textContent='완료·취소 내용을 저장하고 있습니다.';
    const fingerprint=JSON.stringify(data);
    try {
      if(!retry||retry.fingerprint!==fingerprint) retry={fingerprint,key:Array.from(
        crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('')};
      await request({...data,request_key:retry.key});
      el('status').textContent='저장했습니다. 계산값과 Map을 새로 조회합니다.';
      window.location.reload();
    } catch(error) {
      el('status').textContent=error.message+' 상태를 확인한 뒤 다시 시도하세요.';
      try {state=await request();renderHistory();}catch{}
    } finally {busy=false;update();}
  }
  el('complete').addEventListener('click',()=>save({operation:'COMPLETE',tube_ids:[...selected].sort((a,b)=>a-b),
    date:el('date').value,reason:el('reason').value,versions:state?.versions}));
  function renderHistory() {
    const box=el('history');box.replaceChildren();
    if(!state.history.length){box.textContent='이 화면에서 등록한 완료·취소 이력이 없습니다.';return;}
    const table=document.createElement('table'),head=document.createElement('tr');
    for(const label of ['튜브','작업','완료일','등록시각','등록자','사유','취소']){const th=document.createElement('th');th.textContent=label;head.append(th);}
    table.append(head);
    for(const event of state.history){
      const row=document.createElement('tr');
      for(const value of [event.tube_no,event.operation==='COMPLETE'?'완료 등록':'등록 취소',event.date,
          new Date(event.registered_at).toLocaleString('ko-KR'),event.actor,event.reason]){
        const td=document.createElement('td');td.textContent=value;row.append(td);
      }
      const td=document.createElement('td');
      if(event.can_cancel){const button=document.createElement('button');button.type='button';button.className='button';button.textContent='잘못된 등록 취소';
        button.dataset.pluggingEvent=event.event_id;
        button.addEventListener('click',()=>save({operation:'CANCEL',event_ids:[event.event_id],reason:el('reason').value,versions:state.versions}));td.append(button);}
      row.append(td);table.append(row);
    }
    box.append(table);
  }
  request().then(payload=>{state=payload;renderHistory();update();}).catch(error=>{el('status').textContent=error.message;});
})();
