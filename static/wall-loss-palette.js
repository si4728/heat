/* Display palette is independent of engineering alarm/plugging thresholds. */
(function(root){
  const bands = [
    ['NOMINAL','Nominal · 0%', '#0000ff'],
    ['LOSS_10','01~10%', '#009fbf'], ['LOSS_20','11~20%', '#00ffff'],
    ['LOSS_30','21~30%', '#008000'], ['LOSS_40','31~40%', '#00ff00'],
    ['LOSS_50','41~50%', '#a0ff00'], ['LOSS_60','51~60%', '#ffff00'],
    ['LOSS_70','61~70%', '#ff8000'], ['LOSS_80','71~80%', '#ff80bf'],
    ['LOSS_90','81~90%', '#8080bf'], ['LOSS_99','91~99%', '#800040'],
    ['LOSS_100','100% 이상', '#ff0000'],
    ['NOT_INSPECTED','등록 튜브 · 미검사 / 감육률 미등록', '#ffffff'],
    ['UNREGISTERED','미등록 위치 · 상태 미확인', '#cbd5e1'],
    ['PLUGGED','Plugged · 사용중지', '#000000']
  ].map(([key,label,color])=>({key,label,color}));
  const byKey = new Map(bands.map(b=>[b.key,b]));
  function grade(value){
    if(value===null || value===undefined || value==='' || !Number.isFinite(Number(value)))return byKey.get('NOT_INSPECTED');
    const rounded=Math.max(0,Math.round(Number(value)));
    const index=rounded===0 ? 0 : rounded>=100 ? 11 : Math.ceil(rounded/10);
    return bands[index];
  }
  function tubeGrade(tube,value=tube?.wall_loss_percent){
    if(!tube)return byKey.get('NOT_INSPECTED');
    if(tube.managed===false || tube.category==='UNREGISTERED')return byKey.get('UNREGISTERED');
    if(tube.category==='PLUGGED'||(tube.operational_status||tube.current_status)==='PLUGGED')return byKey.get('PLUGGED');
    if(tube.category==='NOT_INSPECTED')return byKey.get('NOT_INSPECTED');
    return grade(value);
  }
  const api={bands,grade,tubeGrade}; root.IrisWallLossPalette=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
