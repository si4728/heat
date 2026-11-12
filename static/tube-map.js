(() => {
  const root = document.getElementById("tube-map-app");
  if (!root) return;
  const entryParams = new URLSearchParams(window.location.search);
  const entryTubeId = Number(entryParams.get('tube_id'));

  const palette = window.IrisWallLossPalette;
  const labels = { NOT_INSPECTED: "미검사", NORMAL: "정상", WARNING: "주의", CRITICAL: "위험", PLUGGED: "사용중지 (Plugged)" };
  const operationalLabels = { IN_SERVICE: "사용 중", PLUGGED: "사용중지 (Plugged)" };
  const inspectionLabels = { INSPECTED: "검사", NOT_INSPECTED: "미검사" };
  const campaignSelect = document.getElementById("tube-map-campaign");
  const colorModeSelect = document.getElementById("tube-map-color-mode");
  const canvas = document.getElementById("tube-map-2d"), ctx = canvas.getContext("2d");
  const surfaceViews = {
    INNER: {canvas:document.getElementById("tube-unwrapped-inner"),empty:document.getElementById("tube-unwrapped-inner-empty"),count:document.getElementById("inner-surface-count")},
    OUTER: {canvas:document.getElementById("tube-unwrapped-outer"),empty:document.getElementById("tube-unwrapped-outer-empty"),count:document.getElementById("outer-surface-count")},
    UNKNOWN: {canvas:document.getElementById("tube-unwrapped-unknown"),empty:document.getElementById("tube-unwrapped-unknown-empty"),count:document.getElementById("unknown-surface-count")},
  };
  const threeHost = document.getElementById("tube-map-3d");
  const labelToggle = document.getElementById("tube-map-labels");
  const editToggle = document.getElementById("tube-map-edit");
  const moveReason = document.getElementById("tube-map-move-reason");
  const rotationInput = document.getElementById("tube-map-rotation");
  const rotationValue = document.getElementById("tube-map-rotation-value");
  const loading = document.getElementById("tube-map-loading"), note = document.getElementById("map-data-note");
  const inspector = document.getElementById("tube-3d-inspector");
  const extractButton = document.getElementById("extract-tube"), restoreButton = document.getElementById("restore-array");
  const indicationPanel = document.getElementById("tube-indication-panel");
  const indicationRows = document.getElementById("tube-indication-rows");
  const state = { data: null, points: [], selected: null, mode: "2d", colorMode: "wall_loss", three: null, rotation: 0, drag2d: null, view2d: null, extracted: false };
  const format = (value, suffix = "") => value == null ? "-" : `${Number(value).toLocaleString("ko-KR")}${suffix}`;
  const finiteNumber = (value) => {
    if (value == null || value === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  const radians = () => state.rotation * Math.PI / 180;
  const sameTube = (left, right) => Boolean(left && right) && (
    left.tube_id && right.tube_id
      ? left.tube_id === right.tube_id
      : left.display_slot === right.display_slot
  );
  const tubeIdentityLabel = tube => {
    if(!tube)return "튜브를 선택하세요";
    const grid=finiteNumber(tube.row)!=null&&finiteNumber(tube.column)!=null ? ` · R${tube.row}/C${tube.column}` : "";
    return `Tube ${tube.tube_no}${grid}`;
  };
  const tubeDimensions = () => {
    const length = Number(state.data?.tube_spec?.length_mm), diameter = Number(state.data?.tube_spec?.outer_diameter_mm);
    return {
      lengthMm: Number.isFinite(length) && length > 0 ? length : null,
      height: Number.isFinite(length) && length > 0 ? Math.max(4, Math.min(16, length / 500)) : 8,
      radius: Number.isFinite(diameter) && diameter > 0 ? Math.max(.25, Math.min(.55, diameter / 80)) : .34,
    };
  };

  function equivalentWallLoss(item) {
    const nominal = finiteNumber(state.data?.tube_spec?.nominal_thickness_mm);
    if (state.colorMode === "depth") {
      const depth = finiteNumber(item?.wall_loss_depth_mm);
      if (depth != null && nominal != null && nominal > 0) return depth / nominal * 100;
    }
    if (state.colorMode === "remaining") {
      const remaining = finiteNumber(item?.measured_thickness_mm ?? item?.minimum_wall_thickness_mm);
      if (remaining != null && nominal != null && nominal > 0) return (nominal - remaining) / nominal * 100;
    }
    return finiteNumber(item?.wall_loss_percent);
  }

  function colorFromLossPercent(loss) { return palette.grade(loss).color; }
  function tubeColor(tube) { return palette.tubeGrade(tube, equivalentWallLoss(tube)).color; }
  function lossGrade(tube) { return palette.tubeGrade(tube, equivalentWallLoss(tube)); }

  function indicationColor(indication, tube) {
    const loss = equivalentWallLoss(indication);
    if (!Number.isFinite(loss)) return tubeColor(tube);
    return colorFromLossPercent(loss);
  }

  function colorModeLabel() {
    const label = {wall_loss: "감육률 (%)", depth: "감육 깊이 (mm)", remaining: "잔존 두께 (mm)"}[state.colorMode];
    const nominal = finiteNumber(state.data?.tube_spec?.nominal_thickness_mm);
    return state.colorMode !== "wall_loss" && !(nominal > 0) ? `${label} 요청 · 명목두께 미등록으로 감육률 대체` : label;
  }

  function positionQualityLabel(indication) {
    const angleUnknown = indication.circumferential_angle_deg == null;
    if (indication.position_quality === "MEASURED") return angleUnknown ? "원주 위치 미확정" : "상세 위치";
    if (indication.position_quality === "RESULT_REPRESENTATIVE") return angleUnknown ? "축 위치 보조값 · 원주 위치 미확정" : "축 위치 보조값";
    return "위치 미확인";
  }

  function positionReferenceLabel(indication) {
    const reference = indication?.position_reference || {};
    const direction = (reference.direction_labels || []).join(" → ");
    const endpoints = [reference.start_point, reference.end_point].filter(Boolean).join(" → ");
    return [endpoints, direction].filter(Boolean).join(" · ") || "기준방향 미등록";
  }

  function renderIndicationTable(tube) {
    indicationRows.replaceChildren();
    indicationPanel.hidden = !tube;
    if (!tube) return;
    const indications = tube.indications || [];
    document.getElementById("indication-panel-title").textContent = `Tube ${tube.tube_no} 검사 위치·측정값`;
    document.getElementById("position-axis-start").textContent = `0 mm · ${positionReferenceLabel(indications[0])}`;
    document.getElementById("position-axis-end").textContent = state.data?.tube_spec?.length_mm
      ? `${Number(state.data.tube_spec.length_mm).toLocaleString("ko-KR")} mm`
      : "Tube 끝 · 길이 미등록";
    if (!indications.length) {
      const row = document.createElement("tr"), cell = document.createElement("td");
      cell.colSpan = 13; cell.className = "empty"; cell.textContent = "이 검사연도에 등록된 결함 지시가 없습니다.";
      row.append(cell); indicationRows.append(row); drawUnwrappedTube(tube); return;
    }
    indications.forEach((indication, index) => {
      const row = document.createElement("tr");
      const values = [
        indication.sequence_no ?? index + 1,
        indication.axial_position_mm == null ? "미등록" : `${format(indication.axial_position_mm)} mm`,
        positionReferenceLabel(indication),
        ({INNER:"내면 (ID)", OUTER:"외면 (OD)", UNKNOWN:"미확정"})[indication.surface_side || "UNKNOWN"] || "미확정",
        indication.circumferential_angle_deg == null ? "위치 미확정" : `${format(indication.circumferential_angle_deg)}°`,
        indication.measured_thickness_mm == null ? "-" : `${format(indication.measured_thickness_mm)} mm`,
        indication.wall_loss_depth_mm == null ? "-" : `${format(indication.wall_loss_depth_mm)} mm`,
        indication.wall_loss_percent == null ? "-" : `${format(indication.wall_loss_percent)}%`,
        indication.defect_length_mm == null ? "-" : `${format(indication.defect_length_mm)} mm`,
        [indication.defect_type, indication.judgement].filter(Boolean).join(" / ") || "-",
        [indication.scope_code, indication.inspection_date].filter(Boolean).join(" · ") || "-",
        positionQualityLabel(indication),
      ];
      values.forEach((value, column) => {
        const cell = document.createElement("td"); cell.textContent = value;
        if (column === 7 && indication.wall_loss_percent != null) {
          cell.style.color = indicationColor(indication, tube); cell.className = "indication-value";
        }
        row.append(cell);
      });
      const sourceCell = document.createElement("td");
      if (indication.inspection_id) {
        const link = document.createElement("a");
        link.className = "strong-link";
        link.href = root.dataset.pdfUrlTemplate.replace("999999", indication.inspection_id)
          + (indication.source_page ? `#page=${indication.source_page}` : "");
        link.target = root.dataset.pdfTarget || "_blank";
        if (link.target === "_blank") link.rel = "noopener";
        link.textContent = indication.source_page ? `PDF p.${indication.source_page}` : "검사 PDF";
        sourceCell.append(link);
      } else sourceCell.textContent = "-";
      row.append(sourceCell); indicationRows.append(row);
    });
    drawUnwrappedTube(tube);
  }

  function drawUnwrappedSurface(tube, surfaceSide, view, lengthMm) {
    if (!view?.canvas) return;
    const surfaceIndications = (tube.indications || []).filter(item => (item.surface_side || "UNKNOWN") === surfaceSide);
    const indications = surfaceIndications.filter(item => finiteNumber(item.axial_position_mm) != null);
    view.count.textContent = `${surfaceIndications.length}건`;
    view.empty.hidden = indications.length > 0 && lengthMm > 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const canvas=view.canvas, ctx=canvas.getContext("2d");
    const width = Math.max(canvas.clientWidth, 280), height = canvas.clientHeight;
    canvas.width = width*dpr; canvas.height = height*dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const margin = {left:46, right:14, top:14, bottom:31};
    const plotWidth = width-margin.left-margin.right, plotHeight = height-margin.top-margin.bottom;
    ctx.fillStyle="#f8fafc";ctx.fillRect(margin.left,margin.top,plotWidth,plotHeight);
    ctx.font = "10px system-ui"; ctx.fillStyle = "#64748b"; ctx.strokeStyle = "#dce4e8";
    [0,90,180,270,360].forEach(angle => {
      const y = margin.top + plotHeight*(angle/360);
      ctx.beginPath(); ctx.moveTo(margin.left,y); ctx.lineTo(width-margin.right,y); ctx.stroke();
      ctx.textAlign="right"; ctx.textBaseline="middle"; ctx.fillText(`${angle}°`,margin.left-7,y);
    });
    [0,.25,.5,.75,1].forEach(ratio => {
      const x=margin.left+plotWidth*ratio;
      ctx.beginPath();ctx.moveTo(x,margin.top);ctx.lineTo(x,height-margin.bottom);ctx.stroke();
      ctx.textAlign="center";ctx.textBaseline="top";ctx.fillText(lengthMm > 0 ? `${Math.round(lengthMm*ratio).toLocaleString("ko-KR")} mm` : "-",x,height-margin.bottom+7);
    });
    if (!(lengthMm > 0)) return;
    indications.forEach(indication => {
      const location=finiteNumber(indication.axial_position_mm), defectLength=finiteNumber(indication.defect_length_mm);
      const centerX=margin.left+plotWidth*Math.max(0,Math.min(1,location/lengthMm));
      const patchWidth=defectLength != null ? Math.max(5,plotWidth*defectLength/lengthMm) : 6;
      const angle=finiteNumber(indication.circumferential_angle_deg), knownAngle=angle != null;
      const y=knownAngle ? margin.top+plotHeight*((((angle%360)+360)%360)/360) : margin.top+plotHeight/2;
      const patchHeight=knownAngle ? Math.max(8,plotHeight/36) : plotHeight;
      ctx.save();
      ctx.globalAlpha=knownAngle ? .94 : .4;
      ctx.fillStyle=indicationColor(indication,tube);
      ctx.fillRect(centerX-patchWidth/2,y-patchHeight/2,patchWidth,patchHeight);
      ctx.globalAlpha=1;ctx.strokeStyle=indicationColor(indication,tube);ctx.lineWidth=2;
      ctx.setLineDash(indication.position_quality === "MEASURED" ? [] : [4,3]);
      ctx.strokeRect(centerX-patchWidth/2,y-patchHeight/2,patchWidth,patchHeight);
      ctx.restore();
    });
  }

  function drawUnwrappedTube(tube) {
    if (!tube) return;
    const allIndications=(tube.indications || []).filter(item=>finiteNumber(item.axial_position_mm)!=null);
    const registeredLength=finiteNumber(state.data?.tube_spec?.length_mm);
    const maximumLocation=Math.max(...allIndications.map(item=>finiteNumber(item.axial_position_mm)),0);
    const lengthMm=registeredLength != null && registeredLength > 0 ? registeredLength : maximumLocation;
    Object.entries(surfaceViews).forEach(([surfaceSide,view])=>drawUnwrappedSurface(tube,surfaceSide,view,lengthMm));
    const unknown=(tube.indications || []).filter(item=>(item.surface_side || "UNKNOWN") === "UNKNOWN").length;
    const warning=document.getElementById("surface-data-warning");
    warning.textContent=unknown
      ? `내면·외면 구분 미등록 ${unknown}건은 임의 배정하지 않고 표면 미확정 영역에 표시합니다.`
      : "검사 원본의 내면·외면 구분에 따라 분리 표시합니다.";
    warning.classList.toggle("is-limited",unknown>0);
  }

  function normalizedPositions(tubes, targetSpan = 34) {
    const points = tubes.map((tube, index) => ({ tube,
      x: Number.isFinite(Number(tube.x)) ? Number(tube.x) : index % 20,
      y: Number.isFinite(Number(tube.y)) ? Number(tube.y) : Math.floor(index / 20) }));
    if (!points.length) return points;
    const xs = points.map(p => p.x), ys = points.map(p => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const centerX = (minX + maxX) / 2, centerY = (minY + maxY) / 2;
    const scale = targetSpan / Math.max(maxX - minX, maxY - minY, 1);
    return points.map(p => ({ ...p, nx: (p.x - centerX) * scale, ny: (p.y - centerY) * scale,
      centerX, centerY, scale }));
  }

  function geometryShape() {
    const geometry = state.data?.layout?.pdf_geometry;
    if (!geometry || geometry.review_status === "REJECTED") return null;
    if (geometry.consensus_shape_code && Number(geometry.consensus_confidence || 0) >= .6) {
      return geometry.consensus_shape_code;
    }
    return geometry.shape_code || null;
  }

  function geometryTone() {
    const geometry = state.data?.layout?.pdf_geometry;
    return geometry?.review_status === "CONFLICT" || geometry?.verification_status === "WARNING"
      ? {stroke:"#f59e0b",fill:"rgba(245,158,11,.08)"}
      : {stroke:"#2dd4bf",fill:"rgba(45,212,191,.07)"};
  }

  function roundedRectanglePath(context, x, y, width, height, radius) {
    const r = Math.max(0, Math.min(radius, width/2, height/2));
    context.moveTo(x+r,y);context.lineTo(x+width-r,y);context.quadraticCurveTo(x+width,y,x+width,y+r);
    context.lineTo(x+width,y+height-r);context.quadraticCurveTo(x+width,y+height,x+width-r,y+height);
    context.lineTo(x+r,y+height);context.quadraticCurveTo(x,y+height,x,y+height-r);
    context.lineTo(x,y+r);context.quadraticCurveTo(x,y,x+r,y);context.closePath();
  }

  function draw2dBoundary(width, height, spanX, spanY, angle, tubeRadius) {
    const shape=geometryShape();if(!shape)return;
    const margin=Math.max(10,tubeRadius*1.8),boundaryWidth=spanX+margin*2,boundaryHeight=spanY+margin*2;
    const tone=geometryTone();ctx.save();ctx.translate(width/2,height/2);ctx.rotate(angle);ctx.beginPath();
    if(shape==="CIRCULAR"){
      const radius=Math.max(boundaryWidth,boundaryHeight)/2;ctx.arc(0,0,radius,0,Math.PI*2);
    }else if(shape==="ELLIPTICAL"){
      ctx.ellipse(0,0,boundaryWidth/2,boundaryHeight/2,0,0,Math.PI*2);
    }else if(shape==="RECTANGULAR"){
      ctx.rect(-boundaryWidth/2,-boundaryHeight/2,boundaryWidth,boundaryHeight);
    }else{
      const radius=shape==="OBROUND"?Math.min(boundaryWidth,boundaryHeight)/2:Math.min(boundaryWidth,boundaryHeight)*.18;
      roundedRectanglePath(ctx,-boundaryWidth/2,-boundaryHeight/2,boundaryWidth,boundaryHeight,radius);
    }
    ctx.fillStyle=tone.fill;ctx.fill();ctx.strokeStyle=tone.stroke;ctx.lineWidth=2;
    ctx.setLineDash(state.data?.layout?.pdf_geometry?.review_status==="CONFLICT"?[8,5]:[]);ctx.stroke();ctx.restore();
  }

  function updateSummary() {
    const s = state.data.summary;
    for (const [id, value, suffix] of [["expected",s.expected_tube_count],["mapped",s.mapped_tube_count],["display",s.display_position_count ?? s.display_tube_count],["inspected",s.inspected_count],["coverage",s.inspection_coverage_percent,"%"],["in-service",s.operational.IN_SERVICE],["plugged",s.operational.PLUGGED]])
      document.getElementById(`metric-${id}`).textContent = format(value, suffix || "");
    const c = state.data.selected_campaign;
    document.getElementById("map-title").textContent = c ? `${c.year}년 검사 · ${c.report_count}개 보고서` : "검사 이력 없음";
    const nominal = finiteNumber(state.data?.tube_spec?.nominal_thickness_mm);
    const legend = document.querySelector('.map-legend');
    legend.replaceChildren();
    palette.bands.forEach(band => {
      const entry = document.createElement('span'), icon = document.createElement('i');
      icon.style.background = band.color;
      icon.style.border = '1px solid #64748b';
      const count = state.data.tubes.filter(tube => lossGrade(tube).key === band.key).length;
      entry.append(icon, document.createTextNode(`${band.label} · ${count}`));
      legend.append(entry);
    });
    if ((s.unlinked_layout_count||0) > 0) { note.hidden = false; note.textContent = `승인 Layout 위치 ${(s.display_position_count ?? s.display_tube_count).toLocaleString("ko-KR")}개 중 물리 튜브 마스터와 연결되지 않은 ${(s.unlinked_layout_count||0).toLocaleString("ko-KR")}개는 원본 좌표로 표시되며 이동할 수 없습니다.`; }
    else if (s.unmapped_expected_count > 0) { note.hidden = false; note.textContent = `전체 ${s.display_tube_count.toLocaleString("ko-KR")}개 중 좌표가 없는 ${s.unmapped_expected_count.toLocaleString("ko-KR")}개는 추정 위치이며 이동할 수 없습니다.`; }
    else note.hidden = true;
    const q = state.data.data_quality || {};
    const qualityNote = document.getElementById("map-quality-note");
    const physical = q.layout_coordinates_complete
      ? `승인 Layout Grid ${format(q.approved_layout_coordinate_count)}개`
      : q.physical_coordinates_complete
      ? `검증 좌표 ${format(q.verified_xy_count)}개`
      : `검증 좌표 ${format(q.verified_xy_count)}개 · 보고서 행/열 ${format(q.report_grid_count)}개 · 추정 ${format(q.estimated_display_count)}개`;
    qualityNote.textContent = `${physical} · 정밀 축 위치 ${format(q.measured_axial_position_count)}/${format(q.indication_count)}건 · 내면 ${format(q.inner_surface_count)}건 · 외면 ${format(q.outer_surface_count)}건 · 표면 미확정 ${format(q.unknown_surface_count)}건 · 원주각 ${format(q.circumferential_angle_count)}건 · 결함 길이 ${format(q.defect_length_count)}건`;
    const geometry=state.data?.layout?.pdf_geometry,shape=geometryShape();
    if(geometry&&shape){qualityNote.textContent+=` · PDF 튜브 배열 형상 ${shape} · ${geometry.review_status} · 신뢰도 ${format(Math.round(Number(geometry.shape_confidence||0)*100),"%")}`;}
    qualityNote.classList.toggle("is-limited", (!q.layout_coordinates_complete && !q.physical_coordinates_complete) || q.circumferential_angle_count < q.indication_count || geometry?.review_status==="CONFLICT");
    document.getElementById("inspect-color-description").textContent = `색상 기준: ${colorModeLabel()}. 원주각이 있으면 국부 패치로, 없으면 원주 전체 밴드로 표시합니다.`;
  }

  function populateCampaigns() {
    campaignSelect.innerHTML = "";
    if (!state.data.campaigns.length) { campaignSelect.add(new Option("검사 이력 없음", "")); campaignSelect.disabled = true; return; }
    state.data.campaigns.forEach(c => { const option = new Option(`${c.year}년 · ${c.report_count}개 보고서`, c.campaign_id); option.selected = state.data.selected_campaign?.campaign_id === c.campaign_id; campaignSelect.add(option); });
    campaignSelect.disabled = false;
  }

  function draw2d() {
    if (!state.data || canvas.hidden || canvas.clientWidth <= 0 || canvas.clientHeight <= 0) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2), width = Math.max(canvas.clientWidth, 320), height = canvas.clientHeight;
    canvas.width = width * dpr; canvas.height = height * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, width, height);
    const positions = normalizedPositions(state.data.tubes, 1);
    if (!positions.length) { ctx.fillStyle = "#94a3b8"; ctx.textAlign = "center"; ctx.fillText("표시할 위치가 없습니다.", width/2, height/2); return; }
    const xs = positions.map(p=>p.x), ys=positions.map(p=>p.y), minX=Math.min(...xs), maxX=Math.max(...xs), minY=Math.min(...ys), maxY=Math.max(...ys);
    const padding=48, baseScale=Math.max(.01,Math.min((width-padding*2)/Math.max(maxX-minX,1),(height-padding*2)/Math.max(maxY-minY,1))), scale=baseScale*.96;
    const centerX=(minX+maxX)/2, centerY=(minY+maxY)/2, angle=radians(), cos=Math.cos(angle), sin=Math.sin(angle);
    const radius=1.4*Math.max(4,Math.min(12,baseScale*.34)); state.view2d={width,height,scale,centerX,centerY,angle};
    state.points=positions.map(point=>{ const dx=(point.x-centerX)*scale,dy=(point.y-centerY)*scale; return {tube:point.tube,sx:width/2+dx*cos-dy*sin,sy:height/2+dx*sin+dy*cos,radius}; });
    draw2dBoundary(width,height,(maxX-minX)*scale,(maxY-minY)*scale,angle,radius);
    state.points.forEach(point=>{ const selected=sameTube(state.selected,point.tube); ctx.beginPath();ctx.arc(point.sx,point.sy,point.radius,0,Math.PI*2);ctx.fillStyle=tubeColor(point.tube);ctx.fill();ctx.lineWidth=selected?4:1;ctx.strokeStyle=selected?"#facc15":"rgba(241,245,249,.3)";ctx.stroke();
      (point.tube.indications||[]).filter(item=>finiteNumber(item.circumferential_angle_deg)!=null).forEach(item=>{const markerAngle=(finiteNumber(item.circumferential_angle_deg)-90)*Math.PI/180,markerRadius=point.radius*.72;ctx.save();ctx.beginPath();ctx.arc(point.sx+Math.cos(markerAngle)*markerRadius,point.sy+Math.sin(markerAngle)*markerRadius,Math.max(1.8,point.radius*.19),0,Math.PI*2);ctx.fillStyle=indicationColor(item,point.tube);ctx.globalAlpha=item.position_quality==="MEASURED"?1:.5;ctx.fill();ctx.globalAlpha=1;ctx.setLineDash(item.position_quality==="MEASURED"?[]:[2,2]);ctx.strokeStyle="#fff";ctx.lineWidth=1;ctx.stroke();ctx.restore();});
      if((point.tube.indication_count||0)>1){ctx.fillStyle="#fff";ctx.strokeStyle="#0f172a";ctx.lineWidth=2;ctx.textAlign="center";ctx.textBaseline="middle";ctx.font=`700 ${Math.max(7,Math.min(10,point.radius))}px system-ui`;ctx.strokeText(String(point.tube.indication_count),point.sx+point.radius*.72,point.sy-point.radius*.72);ctx.fillText(String(point.tube.indication_count),point.sx+point.radius*.72,point.sy-point.radius*.72);}
      if(labelToggle.checked&&state.points.length<=350){ctx.fillStyle=point.tube.category==="NOT_INSPECTED"?"#f1f5f9":"#fff";ctx.textAlign="center";ctx.textBaseline="middle";ctx.font=`${Math.max(8,Math.min(10,point.radius))}px system-ui`;ctx.fillText(point.tube.tube_no,point.sx,point.sy);} });
  }

  function canMove(tube, showMessage=true) {
    let message="";
    if (!editToggle.checked) message="튜브 이동을 먼저 켜 주세요.";
    else if (!tube?.managed || !tube?.tube_id) message="추정 위치 튜브는 이동할 수 없습니다.";
    else if (tube.coordinate_source === "APPROVED_LAYOUT") message="승인 Layout 좌표는 Revision 검토 절차에서만 변경할 수 있습니다.";
    else if (tube.position_locked) message="잠긴 튜브는 튜브 관리 화면에서 잠금을 해제해야 합니다.";
    else if (!moveReason.value.trim()) message="이동 사유를 입력해 주세요.";
    if (message && showMessage) document.getElementById("map-interaction-note").textContent=message;
    return !message;
  }

  async function savePosition(tube, x, y) {
    const url=root.dataset.positionUrlTemplate.replace("999999",tube.tube_id);
    const response=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({position_x:x,position_y:y,position_z:tube.z??0,position_locked:false,reason:moveReason.value.trim()})});
    const result=await response.json();
    if(!response.ok){document.getElementById("map-interaction-note").textContent=`저장 실패: ${result.error}`;await load(campaignSelect.value);return false;}
    tube.x=x;tube.y=y;tube.source_x=x;tube.source_y=y;document.getElementById("map-interaction-note").textContent=`Tube ${tube.tube_no} 위치를 저장했습니다.`;return true;
  }

  function initialInspectedTube() {
    return (state.data?.tubes || []).filter(tube => tube.inspected)
      .slice().sort((a,b) => (finiteNumber(a.row) ?? Infinity) - (finiteNumber(b.row) ?? Infinity)
        || (finiteNumber(a.column) ?? Infinity) - (finiteNumber(b.column) ?? Infinity)
        || String(a.tube_no).localeCompare(String(b.tube_no), undefined, {numeric:true}))[0] || null;
  }

  function selectTube(tube) {
    const coordinateLabels={APPROVED_LAYOUT:"승인 Layout Grid",VERIFIED:"검증좌표",REGISTERED:"등록좌표",REPORT_GRID:"보고서 행/열",UNKNOWN:"추정위치"};
    state.selected=tube;document.getElementById("selected-tube").textContent=tube?`${tubeIdentityLabel(tube)} · ${coordinateLabels[tube.coordinate_quality]||"추정위치"}${tube.position_locked?" · 잠김":""}`:"튜브를 선택하세요";
    document.getElementById("selected-operational").textContent=tube?(operationalLabels[tube.operational_status]||"상태 미등록"):"-";
    document.getElementById("selected-operational").title = tube?.operational_status_source === "DEFAULT_NO_PLUGGING_INFO" ? "Plugging 정보가 없어 사용 중으로 기본 분류합니다. 검사 완료 또는 실물 확인을 뜻하지 않습니다." : "등록된 튜브 운전 상태";
    document.getElementById("selected-status").textContent=tube?`${inspectionLabels[tube.inspection_status]||tube.inspection_status} / ${labels[tube.category]}`:"-";
    const grade=lossGrade(tube),selectedLoss=document.getElementById("selected-loss"),selectedGrade=document.getElementById("selected-loss-grade");
    selectedLoss.textContent=tube?format(tube.wall_loss_percent,"%"):"-";selectedLoss.style.color=tube?tubeColor(tube):"";
    selectedGrade.textContent=tube?grade.label:"-";selectedGrade.style.color=tube?"#334155":"";selectedGrade.style.background=tube?`${grade.color}18`:"";
    document.getElementById("selected-thickness").textContent=tube?format(tube.minimum_wall_thickness_mm," mm"):"-";
    const spec=state.data?.tube_spec, sourceLabel=spec?.source_label||{MASTER:"기본 사양",INSPECTION_SNAPSHOT:"검사 보고서",EXCHANGER_AVERAGE:"해당 열교환기 평균",GLOBAL_AVERAGE:"전체 열교환기 평균",UNREGISTERED:"미등록"}[spec?.source]||"미등록";
    document.getElementById("selected-length").textContent=spec?.length_mm?`${Number(spec.length_mm).toLocaleString("ko-KR")} mm · ${sourceLabel}`:`미등록 · ${sourceLabel}`;
    document.getElementById("selected-corrosion").textContent=tube?`${tube.corrosion_type||"-"} / ${(tube.scopes||[]).join(", ")||"-"}`:"-";
    document.getElementById("selected-indications").textContent=tube?`${tube.indication_count||0}건 · 실제 축 위치 ${tube.measured_indication_count||0}건 · 원주 위치 ${tube.circumferential_indication_count||0}건`:"-";
    const history=document.getElementById("selected-history");if(tube?.tube_id){history.href=root.dataset.tubeUrlTemplate.replace("999999",tube.tube_id);history.hidden=false;}else history.hidden=true;
    extractButton.disabled=!tube||!tube.managed||!tube.tube_id;
    if(tube){document.getElementById("inspect-tube-no").textContent=tubeIdentityLabel(tube);document.getElementById("inspect-tube-length").textContent=spec?.length_mm?`${Number(spec.length_mm).toLocaleString("ko-KR")} mm (${sourceLabel})`:`미등록 (${sourceLabel})`;document.getElementById("inspect-position-basis").textContent=positionReferenceLabel((tube.indications||[])[0]);document.getElementById("inspect-indication-count").textContent=`${tube.indication_count||0}건 (실제 축 위치 ${tube.measured_indication_count||0}건 · 원주 위치 ${tube.circumferential_indication_count||0}건)`;document.getElementById("inspect-wall-loss").textContent=format(tube.wall_loss_percent,"%");document.getElementById("inspect-min-thickness").textContent=format(tube.minimum_wall_thickness_mm," mm");document.getElementById("inspect-loss-depth").textContent=format(tube.wall_loss_depth_mm," mm");document.getElementById("inspect-location").textContent=format(tube.location_mm," mm");}
    if(tube&&state.mode==="3d"&&!state.extracted)document.getElementById("map-interaction-note").textContent=`선택 확인: ${tubeIdentityLabel(tube)} · 노란 원위치 표시에서 축 방향으로 자동 인출했습니다.`;
    renderIndicationTable(tube);
    const directSelect=document.getElementById('tube-map-direct-select');
    if(directSelect)directSelect.value=String((state.data?.tubes||[]).indexOf(tube));
    draw2d();updateThreeSelection();
    if(state.extracted&&state.three)renderExtractedTube();
    if(state.three && state.mode==='3d'){
      state.three.scene.updateMatrixWorld(true);updateSelectionBadge();updateFocusLabelVisibility();
      state.three.renderer.render(state.three.scene,state.three.camera);
    }
  }

  function hit2d(event){
    const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;
    let nearest=null,nearestDistance=Infinity;
    for(const point of state.points){
      const distance=Math.hypot(point.sx-x,point.sy-y);
      if(distance<=point.radius+5 && distance<nearestDistance){nearest=point;nearestDistance=distance;}
    }
    return nearest;
  }
  const tooltip=document.createElement("div");tooltip.className="map-tooltip";tooltip.hidden=true;canvas.parentElement.append(tooltip);
  canvas.addEventListener("pointerdown",event=>{const hit=hit2d(event);if(!hit)return;selectTube(hit.tube);if(canMove(hit.tube,false)){state.drag2d={tube:hit.tube};canvas.setPointerCapture(event.pointerId);}});
  canvas.addEventListener("pointermove",event=>{if(state.drag2d&&state.view2d){const rect=canvas.getBoundingClientRect(),dx=event.clientX-rect.left-state.view2d.width/2,dy=event.clientY-rect.top-state.view2d.height/2,a=-state.view2d.angle,cos=Math.cos(a),sin=Math.sin(a);state.drag2d.tube.x=state.view2d.centerX+(dx*cos-dy*sin)/state.view2d.scale;state.drag2d.tube.y=state.view2d.centerY+(dx*sin+dy*cos)/state.view2d.scale;tooltip.hidden=true;draw2d();return;}const hit=hit2d(event);if(!hit){tooltip.hidden=true;return;}const grade=lossGrade(hit.tube);tooltip.textContent=`Tube ${hit.tube.tube_no} · ${grade.label} · 감육률 ${format(hit.tube.wall_loss_percent,"%")} · 최소두께 ${format(hit.tube.minimum_wall_thickness_mm," mm")}`;tooltip.style.left=`${canvas.offsetLeft+event.offsetX}px`;tooltip.style.top=`${canvas.offsetTop+event.offsetY}px`;tooltip.hidden=false;});
  canvas.addEventListener("pointerup",async()=>{if(!state.drag2d)return;const tube=state.drag2d.tube;state.drag2d=null;await savePosition(tube,tube.x,tube.y);draw2d();if(state.mode==="3d")draw3d();});
  canvas.addEventListener("pointerleave",()=>{tooltip.hidden=true;});

  function initThree(){if(state.three||typeof THREE==="undefined")return;const scene=new THREE.Scene();scene.background=new THREE.Color(0x0f172a);const camera=new THREE.PerspectiveCamera(48,1,.1,500);camera.position.set(30,34,38);const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));renderer.setSize(threeHost.clientWidth,threeHost.clientHeight);const selectionBadge=document.createElement("div");selectionBadge.className="tube-selection-badge";selectionBadge.hidden=true;selectionBadge.setAttribute("role","status");threeHost.replaceChildren(renderer.domElement,selectionBadge);const controls=new THREE.OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.enableRotate=true;controls.enableZoom=true;controls.enablePan=true;controls.screenSpacePanning=true;controls.minDistance=1.5;controls.maxDistance=180;controls.target.set(0,1.5,0);controls.update();scene.add(new THREE.AmbientLight(0xffffff,.72));const light=new THREE.DirectionalLight(0xffffff,.85);light.position.set(15,25,20);scene.add(light);const grid=new THREE.GridHelper(42,21,0x475569,0x334155);grid.userData.tubeMapGrid=true;scene.add(grid);const group=new THREE.Group(),boundaryGroup=new THREE.Group(),selectionGroup=new THREE.Group(),focusGroup=new THREE.Group();selectionGroup.visible=false;focusGroup.visible=false;scene.add(boundaryGroup);scene.add(group);scene.add(selectionGroup);scene.add(focusGroup);
    let transform=null;if(THREE.TransformControls){transform=new THREE.TransformControls(camera,renderer.domElement);transform.setMode("translate");transform.setSpace("local");transform.showY=false;scene.add(transform);transform.addEventListener("dragging-changed",e=>controls.enabled=!e.value);transform.addEventListener("mouseUp",async()=>{const mesh=transform.object;if(!mesh?.userData?.tube)return;const p=mesh.userData.point,tube=mesh.userData.tube,x=p.x+(mesh.position.x-p.nx)/p.scale,y=p.y+(mesh.position.z-p.ny)/p.scale;mesh.position.y=mesh.userData.baseY;if(await savePosition(tube,x,y)){p.x=x;p.y=y;p.nx=mesh.position.x;p.ny=mesh.position.z;}updateThreeSelection();});}
    let pointerStart=null;
    renderer.domElement.addEventListener('pointerdown',event=>{
      if(event.button!==0 || transform?.dragging || state.mode!=='3d')return;
      pointerStart={x:event.clientX,y:event.clientY,id:event.pointerId,maxMovement:0};
    },true);
    window.addEventListener('pointermove',event=>{
      if(pointerStart?.id===event.pointerId)pointerStart.maxMovement=Math.max(pointerStart.maxMovement,Math.hypot(event.clientX-pointerStart.x,event.clientY-pointerStart.y));
    },true);
    window.addEventListener('pointercancel',()=>{pointerStart=null;},true);
    window.addEventListener('pointerup',event=>{
      if(!pointerStart || pointerStart.id!==event.pointerId)return;
      const gesture=pointerStart;pointerStart=null;
      if(transform?.dragging || state.mode!=='3d' || state.extracted || Math.max(gesture.maxMovement,Math.hypot(event.clientX-gesture.x,event.clientY-gesture.y))>6)return;
      const tube=pickThreeTube(event.clientX,event.clientY);
      if(tube)selectTube(tube);
    },true);

    state.three={scene,camera,renderer,controls,group,boundaryGroup,selectionGroup,selectionBadge,selectedMesh:null,focusGroup,transform};(function animate(){requestAnimationFrame(animate);controls.update();updateSelectionBadge();updateFocusLabelVisibility();if(state.mode==="3d")renderer.render(scene,camera);})();}

  function pickThreeTube(clientX,clientY) {
    const v=state.three;if(!v||state.extracted)return null;
    const rect=v.renderer.domElement.getBoundingClientRect();
    if(rect.width<=0||rect.height<=0||clientX<rect.left||clientX>rect.right||clientY<rect.top||clientY>rect.bottom)return null;
    v.camera.updateMatrixWorld(true);v.scene.updateMatrixWorld(true);
    const pointer=new THREE.Vector2((clientX-rect.left)/rect.width*2-1,-(clientY-rect.top)/rect.height*2+1);
    const raycaster=new THREE.Raycaster();raycaster.setFromCamera(pointer,v.camera);
    for(const hit of raycaster.intersectObjects(v.group.children,true)){
      let mesh=hit.object;
      while(mesh && mesh!==v.group){if(mesh.userData?.tube)return mesh.userData.tube;mesh=mesh.parent;}
    }
    // Thin cylinders remain selectable within eight CSS pixels of their projected axis.
    let nearest=null,best=8;
    const halfHeight=tubeDimensions().height/2;
    for(const mesh of v.group.children){
      if(!mesh.visible||!mesh.userData?.tube)continue;
      const a=mesh.localToWorld(new THREE.Vector3(0,-halfHeight,0)).project(v.camera);
      const b=mesh.localToWorld(new THREE.Vector3(0,halfHeight,0)).project(v.camera);
      if(a.z< -1||a.z>1||b.z< -1||b.z>1)continue;
      const ax=rect.left+(a.x+1)*rect.width/2,ay=rect.top+(1-a.y)*rect.height/2;
      const bx=rect.left+(b.x+1)*rect.width/2,by=rect.top+(1-b.y)*rect.height/2;
      const dx=bx-ax,dy=by-ay,t=Math.max(0,Math.min(1,((clientX-ax)*dx+(clientY-ay)*dy)/(dx*dx+dy*dy||1)));
      const distance=Math.hypot(clientX-ax-t*dx,clientY-ay-t*dy);
      if(distance<best){best=distance;nearest=mesh.userData.tube;}
    }
    return nearest;
  }

  function disposeGroup(group){while(group.children.length){const child=group.children.pop();child.traverse?.(item=>{item.geometry?.dispose?.();if(Array.isArray(item.material))item.material.forEach(material=>material.dispose?.());else {item.material?.map?.dispose?.();item.material?.dispose?.();}});}}

  function updateSelectionBadge(){
    const v=state.three,badge=v?.selectionBadge,mesh=v?.selectedMesh;
    if(!badge)return;
    if(!mesh||state.extracted||state.mode!=="3d"){badge.hidden=true;return;}
    const dimensions=tubeDimensions(),worldPosition=new THREE.Vector3(0,dimensions.height/2+.7,0);
    mesh.localToWorld(worldPosition);worldPosition.project(v.camera);
    const width=threeHost.clientWidth,height=threeHost.clientHeight;
    const x=(worldPosition.x*.5+.5)*width,y=(-worldPosition.y*.5+.5)*height;
    if(worldPosition.z>1||x<0||x>width||y<0||y>height){badge.hidden=true;return;}
    badge.textContent=`선택됨 · ${tubeIdentityLabel(mesh.userData.tube)}`;
    badge.style.transform=`translate(${Math.round(x)}px, ${Math.round(y)}px) translate(-50%, -115%)`;
    badge.hidden=false;
  }

  function resetArrayCamera(){if(!state.three)return;state.three.camera.position.set(30,34,38);state.three.controls.target.set(0,1.5,0);state.three.controls.update();}

  function resetFocusView() {
    if (!state.three || !state.selected) return;
    const dimensions=tubeDimensions(), distance=Math.max(9,dimensions.height*1.15);
    state.three.focusGroup.rotation.set(0,0,0);
    state.three.focusGroup.position.set(0,0,0);
    state.three.camera.position.set(distance*.72,dimensions.height*.7,distance);
    state.three.controls.target.set(0,dimensions.height/2,0);
    state.three.controls.update();
  }

  function rotateFocusedTube(degrees) {
    if (!state.extracted || !state.three) return;
    state.three.focusGroup.rotation.y += degrees*Math.PI/180;
  }

  function zoomFocusedTube(factor) {
    if (!state.extracted || !state.three) return;
    const {camera,controls}=state.three;
    const offset=camera.position.clone().sub(controls.target);
    const nextDistance=Math.max(controls.minDistance,Math.min(controls.maxDistance,offset.length()*factor));
    offset.setLength(nextDistance);camera.position.copy(controls.target).add(offset);controls.update();
  }

  function indicationPosition(indication, dimensions) {
    return window.IrisTubeFocus.ratio(indication.axial_position_mm,dimensions.lengthMm);
  }

  function addIndicationGeometry(parent, tube, dimensions, coordinateMode, detailed=false) {
    const {height, radius} = dimensions;
    (tube.indications || []).forEach(indication => {
      const ratio = indicationPosition(indication, dimensions);
      if (ratio == null) return;
      const localY = coordinateMode === "centered" ? -height/2 + height*ratio : height*ratio;
      const defectLength = finiteNumber(indication.defect_length_mm);
      const scaledLength = dimensions.lengthMm && defectLength != null
        ? height * defectLength / dimensions.lengthMm : height*.018;
      const bandHeight = Math.max(detailed ? .08 : .035, Math.min(height*.12, scaledLength));
      const color = indicationColor(indication, tube);
      const angle = finiteNumber(indication.circumferential_angle_deg);
      if (angle != null) {
        const radiansAtSurface = (angle-90)*Math.PI/180;
        const markerRadius = detailed ? radius*.2 : radius*.15;
        const severity = Math.max(0, Math.min(1, equivalentWallLoss(indication)/100 || 0));
        const marker = new THREE.Mesh(
          new THREE.SphereGeometry(markerRadius, 16, 10),
          new THREE.MeshStandardMaterial({color, emissive: color, emissiveIntensity: .55, transparent:true, opacity:indication.position_quality==="MEASURED"?1:.55})
        );
        marker.scale.y=Math.max(1,bandHeight/(markerRadius*2));
        marker.position.set(
          Math.cos(radiansAtSurface)*radius*(1.04+severity*.08),
          localY,
          Math.sin(radiansAtSurface)*radius*(1.04+severity*.08)
        );
        parent.add(marker);
      } else {
        const band = new THREE.Mesh(
          new THREE.CylinderGeometry(radius*1.025, radius*1.025, bandHeight, detailed ? 32 : 12, 1, true),
          new THREE.MeshStandardMaterial({color, emissive: color, emissiveIntensity: .28, roughness: .32, transparent:true, opacity:indication.position_quality==="MEASURED"?.85:.45})
        );
        band.position.y = localY;
        parent.add(band);
        if(detailed && indication.position_quality!=="MEASURED"){
          const points=Array.from({length:65},(_,i)=>new THREE.Vector3(Math.cos(i*Math.PI/32)*radius*1.05,localY+bandHeight/2,Math.sin(i*Math.PI/32)*radius*1.05));
          const outline=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineDashedMaterial({color:0xffffff,dashSize:.06,gapSize:.04}));
          outline.computeLineDistances();parent.add(outline);
        }
      }
    });
  }

  function updateFocusLabelVisibility(){
    const v=state.three;if(!v||!state.extracted)return;
    v.camera.updateMatrixWorld(true);v.focusGroup.updateMatrixWorld(true);
    let body=null;const labels=[];
    v.focusGroup.traverse(item=>{if(item.userData.focusTubeBody)body=item;if(item.userData.focusLabel)labels.push(item);});
    if(!body)return;
    const width=v.renderer.domElement.clientWidth,height=v.renderer.domElement.clientHeight;
    if(!width||!height)return;
    const box=new THREE.Box3().setFromObject(body),points=[];
    for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
      const p=new THREE.Vector3(x,y,z).project(v.camera);points.push({x:(p.x+1)*width/2,y:(1-p.y)*height/2});
    }
    const protectedBox={left:Math.min(...points.map(p=>p.x))-10,right:Math.max(...points.map(p=>p.x))+10,top:Math.min(...points.map(p=>p.y))-10,bottom:Math.max(...points.map(p=>p.y))+10};
    for(const label of labels){
      const world=label.getWorldPosition(new THREE.Vector3()),view=world.clone().applyMatrix4(v.camera.matrixWorldInverse),p=world.project(v.camera);
      if(view.z>=0||p.z< -1||p.z>1){label.visible=false;continue;}
      const factor=height/(-2*view.z*Math.tan(v.camera.fov*Math.PI/360));
      const w=label.scale.x*factor,h=label.scale.y*factor,cx=(p.x+1)*width/2,cy=(1-p.y)*height/2;
      const bounds={left:cx-label.center.x*w,right:cx+(1-label.center.x)*w,top:cy-(1-label.center.y)*h,bottom:cy+label.center.y*h};
      label.visible=bounds.right<protectedBox.left||bounds.left>protectedBox.right||bounds.bottom<protectedBox.top||bounds.top>protectedBox.bottom;
    }
  }

  function addFocusLabel(parent,text,x,y,color='#e2e8f0',align='center'){
    const image=document.createElement('canvas'),context=image.getContext('2d');
    context.font='46px sans-serif';image.width=Math.min(2048,Math.ceil(context.measureText(text).width)+24);image.height=80;
    context.fillStyle='rgba(15,23,42,.9)';context.fillRect(0,0,image.width,80);
    context.fillStyle=color;context.font='46px sans-serif';context.textBaseline='middle';context.fillText(text,12,40,image.width-24);
    const texture=new THREE.CanvasTexture(image),material=new THREE.SpriteMaterial({map:texture,depthTest:false,transparent:true});
    const sprite=new THREE.Sprite(material);sprite.scale.set(image.width/image.height*.65,.65,1);if(align==='left')sprite.center.set(0,.5);sprite.position.set(x,y,0);sprite.renderOrder=8;sprite.userData.focusLabel=true;parent.add(sprite);
  }

  function renderFocusVisual(tube){
    const panel=document.getElementById('tube-focus-visual'),data=window.IrisTubeFocus.describe(tube,state.data?.tube_spec);
    panel.hidden=false;panel.replaceChildren();
    const heading=document.createElement('h3');heading.textContent=`${tubeIdentityLabel(tube)} · 위치와 감육 비교`;panel.append(heading);
    const note=document.createElement('p');note.textContent='저장 단위: mm. 점선은 대표·추정 위치입니다. 기준방향이 없으면 어느 끝에서 잰 거리인지 확정할 수 없습니다. 띠 폭은 가시성을 위한 표시이며, 원주 전체의 손상이나 실제 결함 길이를 뜻하지 않습니다.';panel.append(note);
    const layout=document.createElement('div');layout.className='tube-focus-layout';panel.append(layout);
    const axis=document.createElement('div');layout.append(axis);
    const title=document.createElement('strong');title.textContent=`길이별 위치 · ${format(data.length,' mm')}`;axis.append(title);
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 650 100');svg.setAttribute('role','img');svg.setAttribute('aria-label','튜브 길이와 결함 위치');
    const element=(tag,attrs,text)=>{const node=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value)));if(text)node.textContent=text;svg.append(node);return node;};
    element('line',{x1:35,x2:615,y1:45,y2:45,stroke:'#64748b','stroke-width':12});
    if(data.length>0)for(let i=0;i<=6;i++){
      const x=35+i*580/6;element('line',{x1:x,x2:x,y1:35,y2:60,stroke:'#334155'});element('text',{x,y:82,'text-anchor':'middle','font-size':12,fill:'#334155'},Math.round(data.length*i/6).toLocaleString('ko-KR'));
    }
    data.indications.forEach(item=>{if(item.ratio===null)return;const x=35+580*item.ratio;
      const marker=element('circle',{cx:x,cy:45,r:8,fill:palette.grade(item.loss).color,stroke:'#334155','stroke-width':2,'stroke-dasharray':item.measured?'none':'3 2',tabindex:0,role:'button','aria-label':`결함 ${item.index+1} · ${format(item.position,' mm')}`});
      const focus=()=>{resetFocusView();const target=state.three.controls.target;target.y=tubeDimensions().height*item.ratio;state.three.controls.update();};
      marker.addEventListener('click',focus);marker.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();focus();}});
    });axis.append(svg);
    const wall=document.createElement('div');layout.append(wall);const wallTitle=document.createElement('strong');wallTitle.textContent='측정점 벽 두께 비교 · 개념도';wall.append(wallTitle);
    for(const [label,value,share,color] of [['기준 두께',data.wall,1,'#94a3b8'],['최소 잔존 두께',data.remaining,data.retained,palette.grade(tube.wall_loss_percent).color]]){
      const row=document.createElement('div');row.textContent=`${label} ${format(value,' mm')}`;const bar=document.createElement('div');bar.className='focus-thickness-track';const fill=document.createElement('i');fill.style.width=(share===null||value===null)?'0':`${share*100}%`;fill.style.background=color;bar.append(fill);row.append(bar);wall.append(row);
    }
    const retained=document.createElement('p');retained.textContent=data.retained===null?'잔존 비율 산정 불가':`잔존 ${(data.retained*100).toFixed(2)}% · 감육률 ${format(tube.wall_loss_percent,'%')}${data.inferred?' · 기준 두께는 최소두께+감육깊이로 유도':''}`;wall.append(retained);
    const list=document.createElement('ul');panel.append(list);
    data.indications.forEach(item=>{const li=document.createElement('li');li.textContent=`#${item.index+1} · ${format(item.position,' mm')} · ${item.ratio===null?'위치 누락·길이 미등록 또는 범위 밖: 배열에 표시하지 않음':`${(item.ratio*100).toFixed(1)}% 지점 · ${item.measured?'실측 위치':'대표·추정 위치'}`} · ${positionReferenceLabel({position_reference:item.reference})} · ${item.angle===null?'원주 방향 미확정':`원주각 ${item.angle}°`} · 감육률 ${format(item.loss,'%')} · 최소두께 ${format(item.remaining,' mm')} · 결함 길이 ${format(item.length,' mm')}`;list.append(li);});
    if(!data.indications.length){const li=document.createElement('li');li.textContent='등록된 결함 위치 정보가 없습니다. 튜브 전체를 정상으로 판단하지 않습니다.';list.append(li);}
  }

  function renderExtractedTube(){
    const v=state.three,tube=state.selected;if(!v||!tube)return;
    v.transform?.detach();v.group.visible=false;v.selectionGroup.visible=false;v.selectedMesh=null;v.selectionBadge.hidden=true;v.focusGroup.visible=true;disposeGroup(v.selectionGroup);disposeGroup(v.focusGroup);
    const dimensions=tubeDimensions(),height=dimensions.height,radius=dimensions.radius,tubeGroup=new THREE.Group();
    const mainMaterial=new THREE.MeshStandardMaterial({color:0x94a3b8,roughness:.42,metalness:.08,transparent:true,opacity:.38,side:THREE.DoubleSide}),fullTube=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,height,32,1,true),mainMaterial);fullTube.position.y=height/2;fullTube.userData.focusTubeBody=true;tubeGroup.add(fullTube);
    v.scene.children.filter(item=>item.userData.tubeMapGrid).forEach(item=>item.visible=false);
    addIndicationGeometry(tubeGroup,tube,dimensions,"baseline",true);
    const ringMaterial=new THREE.MeshStandardMaterial({color:0xe2e8f0,roughness:.35});[0,height].forEach(y=>{const ring=new THREE.Mesh(new THREE.TorusGeometry(radius,.035,8,32),ringMaterial.clone());ring.rotation.x=Math.PI/2;ring.position.y=y;tubeGroup.add(ring);});
    const dimensionX=radius+1.15,lineMaterial=new THREE.LineBasicMaterial({color:0x2dd4bf}),lineGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(dimensionX,0,0),new THREE.Vector3(dimensionX,height,0)]);tubeGroup.add(new THREE.Line(lineGeometry,lineMaterial));
    [0,1/6,2/6,.5,4/6,5/6,1].forEach(ratio=>{const y=height*ratio,tickGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(dimensionX-.28,y,0),new THREE.Vector3(dimensionX+.28,y,0)]);tubeGroup.add(new THREE.Line(tickGeometry,lineMaterial.clone()));addFocusLabel(tubeGroup,dimensions.lengthMm?`${Math.round(dimensions.lengthMm*ratio).toLocaleString('ko-KR')} mm`:'길이 미등록',dimensionX+.5,y,'#e2e8f0','left');});
    (tube.indications||[]).slice(0,6).forEach((item,index)=>{const ratio=indicationPosition(item,dimensions);if(ratio===null)return;addFocusLabel(tubeGroup,`#${index+1} ${format(item.axial_position_mm,' mm')} · ${format(item.wall_loss_percent??tube.wall_loss_percent,'%')} · ${item.position_quality==='MEASURED'?'실측':'대표·추정'}`,-4.7,height*ratio,palette.grade(item.wall_loss_percent??tube.wall_loss_percent).color);});
    renderFocusVisual(tube);
    v.focusGroup.add(tubeGroup);resetFocusView();inspector.hidden=false;extractButton.hidden=true;restoreButton.hidden=false;
  }

  function roundedThreeShape(width, depth, radius) {
    const x=-width/2,z=-depth/2,r=Math.max(0,Math.min(radius,width/2,depth/2)),shape=new THREE.Shape();
    shape.moveTo(x+r,z);shape.lineTo(x+width-r,z);shape.quadraticCurveTo(x+width,z,x+width,z+r);
    shape.lineTo(x+width,z+depth-r);shape.quadraticCurveTo(x+width,z+depth,x+width-r,z+depth);
    shape.lineTo(x+r,z+depth);shape.quadraticCurveTo(x,z+depth,x,z+depth-r);
    shape.lineTo(x,z+r);shape.quadraticCurveTo(x,z,x+r,z);return shape;
  }

  function renderThreeBoundary(points) {
    const v=state.three,shape=geometryShape();disposeGroup(v.boundaryGroup);if(!shape||!points.length)return;
    const xs=points.map(point=>point.nx),zs=points.map(point=>point.ny),margin=1.25;
    const width=Math.max(...xs)-Math.min(...xs)+margin*2,depth=Math.max(...zs)-Math.min(...zs)+margin*2;
    let geometry,scaleX=1,scaleZ=1;
    if(shape==="CIRCULAR"){
      geometry=new THREE.CircleGeometry(1,64);scaleX=scaleZ=Math.max(width,depth)/2;
    }else if(shape==="ELLIPTICAL"){
      geometry=new THREE.CircleGeometry(1,64);scaleX=width/2;scaleZ=depth/2;
    }else if(shape==="RECTANGULAR"){
      geometry=new THREE.ShapeGeometry(roundedThreeShape(width,depth,0));
    }else{
      const radius=shape==="OBROUND"?Math.min(width,depth)/2:Math.min(width,depth)*.18;
      geometry=new THREE.ShapeGeometry(roundedThreeShape(width,depth,radius));
    }
    const conflict=state.data?.layout?.pdf_geometry?.review_status==="CONFLICT",color=conflict?0xf59e0b:0x2dd4bf;
    const material=new THREE.MeshBasicMaterial({color,transparent:true,opacity:.12,side:THREE.DoubleSide,depthWrite:false});
    const plate=new THREE.Mesh(geometry,material);plate.scale.set(scaleX,scaleZ,1);plate.rotation.x=Math.PI/2;plate.position.y=-.08;
    const outline=new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color,transparent:true,opacity:.9}));
    outline.scale.set(scaleX,scaleZ,1);outline.rotation.x=Math.PI/2;outline.position.y=-.03;
    v.boundaryGroup.add(plate);v.boundaryGroup.add(outline);v.boundaryGroup.rotation.y=radians();
  }

  function draw3d(){
    document.getElementById("tube-focus-visual").hidden=!state.extracted;
    initThree();const v=state.three;if(!v||!state.data)return;v.transform?.detach();v.selectedMesh=null;
    disposeGroup(v.group);disposeGroup(v.selectionGroup);disposeGroup(v.focusGroup);
    const dimensions=tubeDimensions(),height=dimensions.height,radius=dimensions.radius,positions=normalizedPositions(state.data.tubes);
    v.scene.children.filter(item=>item.userData.tubeMapGrid).forEach(item=>item.visible=!state.extracted);
    renderThreeBoundary(positions);
    positions.forEach(p=>{const mesh=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,height,12),new THREE.MeshStandardMaterial({color:tubeColor(p.tube),roughness:.55,transparent:true,opacity:p.tube.inspected?1:.62}));mesh.position.set(p.nx,height/2,p.ny);mesh.userData={tube:p.tube,point:p,baseY:height/2};addIndicationGeometry(mesh,p.tube,dimensions,"centered",false);v.group.add(mesh);});
    v.group.rotation.y=radians();v.boundaryGroup.rotation.y=radians();v.selectionGroup.rotation.y=radians();
    v.group.visible=!state.extracted;v.boundaryGroup.visible=!state.extracted;v.selectionGroup.visible=!state.extracted;v.focusGroup.visible=state.extracted;
    if(state.extracted&&state.selected)renderExtractedTube();else{inspector.hidden=true;extractButton.hidden=false;restoreButton.hidden=true;resetArrayCamera();updateThreeSelection();}resizeThree();
  }
  function updateThreeSelection(){
    if(!state.three||state.extracted)return;
    const v=state.three,dimensions=tubeDimensions(),pullDistance=Math.max(3,dimensions.height*.95);
    let selectedMesh=null;v.transform?.detach();v.selectedMesh=null;disposeGroup(v.selectionGroup);
    v.group.children.forEach(mesh=>{
      const selected=sameTube(state.selected,mesh.userData.tube);
      mesh.position.y=mesh.userData.baseY+(selected?pullDistance:0);
      mesh.scale.set(selected?1.38:1,1,selected?1.38:1);
      mesh.material.emissive.setHex(selected?0x6b5600:0);
      mesh.material.emissiveIntensity=selected ? .85 : 1;
      mesh.renderOrder=selected?2:0;
      if(selected)selectedMesh=mesh;
    });
    if(selectedMesh){
      const p=selectedMesh.userData.point,r=dimensions.radius;
      const ghost=new THREE.Mesh(new THREE.CylinderGeometry(r*1.04,r*1.04,dimensions.height,12,1,true),new THREE.MeshBasicMaterial({color:0xfacc15,wireframe:true,transparent:true,opacity:.28}));
      ghost.position.set(p.nx,dimensions.height/2,p.ny);v.selectionGroup.add(ghost);
      const ring=new THREE.Mesh(new THREE.TorusGeometry(r*1.55,.08,8,32),new THREE.MeshBasicMaterial({color:0xfacc15}));
      ring.rotation.x=Math.PI/2;ring.position.set(p.nx,dimensions.height+.08,p.ny);v.selectionGroup.add(ring);
      const liftedRing=ring.clone();liftedRing.material=ring.material.clone();liftedRing.position.y=dimensions.height+pullDistance;v.selectionGroup.add(liftedRing);
      const guideGeometry=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(p.nx,dimensions.height,p.ny),new THREE.Vector3(p.nx,dimensions.height+pullDistance,p.ny)]);
      v.selectionGroup.add(new THREE.Line(guideGeometry,new THREE.LineBasicMaterial({color:0xfacc15})));
      v.selectedMesh=selectedMesh;
    }
    v.selectionGroup.visible=Boolean(selectedMesh);
    if(selectedMesh&&canMove(selectedMesh.userData.tube,false)&&editToggle.checked)v.transform?.attach(selectedMesh);
    updateSelectionBadge();
  }
  function resizeThree(){if(!state.three||threeHost.hidden)return;const width=threeHost.clientWidth,height=threeHost.clientHeight;state.three.camera.aspect=width/height;state.three.camera.updateProjectionMatrix();state.three.renderer.setSize(width,height);}
  function applyRotation(value){state.rotation=(Number(value)+360)%360;rotationInput.value=state.rotation;rotationValue.textContent=`${state.rotation}°`;draw2d();if(state.three){state.three.group.rotation.y=radians();state.three.boundaryGroup.rotation.y=radians();state.three.selectionGroup.rotation.y=radians();}}

  async function load(campaignId=null){loading.hidden=false;try{const url=new URL(root.dataset.apiUrl,window.location.origin);if(campaignId)url.searchParams.set("campaign_id",campaignId);const response=await fetch(url);if(!response.ok)throw new Error(`HTTP ${response.status}`);state.data=await response.json();state.selected=null;state.extracted=false;inspector.hidden=true;extractButton.hidden=false;restoreButton.hidden=true;const initialRotation=Number(state.data?.layout?.initial_rotation_degrees);state.rotation=Number.isFinite(initialRotation)?((initialRotation%360)+360)%360:0;rotationInput.value=state.rotation;rotationValue.textContent=`${state.rotation}°`;populateCampaigns();updateSummary();
const directSelect=document.getElementById('tube-map-direct-select');
directSelect.replaceChildren(...state.data.tubes.map((tube,index)=>{const option=document.createElement('option');option.value=String(index);option.textContent=tubeIdentityLabel(tube);return option;}));
selectTube(state.data.tubes.find(tube=>entryTubeId>0 && Number(tube.tube_id)===entryTubeId) || initialInspectedTube());draw2d();if(state.mode==="3d")draw3d();}catch(error){loading.textContent=`데이터를 불러오지 못했습니다: ${error.message}`;return;}loading.hidden=true;}
  document.getElementById('tube-map-direct-select').addEventListener('change',event=>{
    const tube=state.data?.tubes[Number(event.target.value)];
    if(!tube)return;
    if(state.extracted&&(!tube.managed||!tube.tube_id)){state.extracted=false;draw3d();}
    selectTube(tube);
  });
  campaignSelect.addEventListener("change",()=>load(campaignSelect.value));colorModeSelect.addEventListener("change",()=>{state.colorMode=colorModeSelect.value;updateSummary();draw2d();if(state.selected)drawUnwrappedTube(state.selected);if(state.mode==="3d")draw3d();});labelToggle.addEventListener("change",draw2d);editToggle.addEventListener("change",updateThreeSelection);moveReason.addEventListener("input",updateThreeSelection);rotationInput.addEventListener("input",()=>applyRotation(rotationInput.value));document.getElementById("tube-map-rotate-left").addEventListener("click",()=>applyRotation(state.rotation-15));document.getElementById("tube-map-rotate-right").addEventListener("click",()=>applyRotation(state.rotation+15));
  function switchView(mode){state.mode=mode;if(mode==="2d")document.getElementById("tube-focus-visual").hidden=true;document.querySelectorAll("[data-view]").forEach(item=>{const active=item.dataset.view===mode;item.classList.toggle("primary",active);item.setAttribute("aria-pressed",String(active));});canvas.hidden=mode!=="2d";threeHost.hidden=mode!=="3d";if(mode==="2d"){state.extracted=false;inspector.hidden=true;extractButton.hidden=false;restoreButton.hidden=true;draw2d();}else draw3d();}
  document.querySelectorAll("[data-view]").forEach(button=>button.addEventListener("click",()=>switchView(button.dataset.view)));
  extractButton.addEventListener("click",()=>{if(!state.selected)return;state.extracted=true;switchView("3d");document.getElementById("map-interaction-note").textContent=`${tubeIdentityLabel(state.selected)} 단일 보기 · 왼쪽 드래그 회전 · 휠 확대/축소 · 오른쪽 드래그 이동`;});
  restoreButton.addEventListener("click",()=>{state.extracted=false;draw3d();document.getElementById("map-interaction-note").textContent="선택: 튜브 클릭 · 전체 회전: 슬라이더 또는 3D 배경 드래그 · 이동: 편집 모드와 사유 입력 후 실제 튜브 드래그";});
  document.getElementById("focus-rotate-left").addEventListener("click",()=>rotateFocusedTube(-15));
  document.getElementById("focus-rotate-right").addEventListener("click",()=>rotateFocusedTube(15));
  document.getElementById("focus-zoom-in").addEventListener("click",()=>zoomFocusedTube(.8));
  document.getElementById("focus-zoom-out").addEventListener("click",()=>zoomFocusedTube(1.25));
  document.getElementById("focus-reset").addEventListener("click",resetFocusView);
  new ResizeObserver(()=>{draw2d();resizeThree();if(state.selected)drawUnwrappedTube(state.selected);}).observe(root);load(entryParams.get('campaign_id')).then(()=>{if(state.data && entryParams.get('view')==='3d')switchView('3d');});
})();
