(function(root){
  const number=v=>v===null||v===undefined||v===''?null:Number.isFinite(Number(v))?Number(v):null;
  function ratio(position,length){
    const p=number(position),l=number(length);
    return p!==null&&l>0&&p>=0&&p<=l?p/l:null;
  }
  function describe(tube,spec){
    const length=number(spec?.length_mm),nominal=number(spec?.nominal_thickness_mm);
    const remaining=number(tube.minimum_wall_thickness_mm),depth=number(tube.wall_loss_depth_mm);
    const inferred=nominal===null&&remaining!==null&&depth!==null;
    const wall=nominal??(inferred?remaining+depth:null);
    const indications=(tube.indications||[]).map((item,index)=>({
      index,position:number(item.axial_position_mm),ratio:ratio(item.axial_position_mm,length),
      measured:item.position_quality==='MEASURED',angle:number(item.circumferential_angle_deg),
      loss:number(item.wall_loss_percent)??number(tube.wall_loss_percent),
      remaining:number(item.measured_thickness_mm)??remaining,
      length:number(item.defect_length_mm),reference:item.position_reference||{}
    }));
    return {length,wall,remaining,inferred,retained:wall>0&&remaining!==null&&remaining>=0&&remaining<=wall?remaining/wall:null,indications};
  }
  const api={ratio,describe};root.IrisTubeFocus=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
