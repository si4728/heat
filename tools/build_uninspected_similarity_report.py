"""Build a review report from held-out predictions; no database or model mutation."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def escape(value):return str(value).replace('|','/').replace('\n',' ')

def build(run, output):
    manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('input_policy','').startswith('EXCEL_MASTER_ONLY'):raise ValueError('Excel-only run required')
    dataset=read_csv(run/'dataset.csv')
    candidates=read_csv(run/'uninspected_review_candidates.csv')
    evaluation=json.loads((run/'evaluation.json').read_text(encoding='utf-8'))
    inspected=[r for r in dataset if r['inspected']=='1']
    assert all(r['inspected']=='0' for r in candidates)
    selected=[r for r in candidates if float(r['historical_selection_score_oof'])>=.5]
    evidence=[]
    for r in selected:
        peers=[x for x in inspected if all(x[k]==r[k] for k in ('unit_code','process_code','service_role')) and x['family_group']!=r['family_group']]
        peers.sort(key=lambda x:(abs(int(x['installation_year'])-int(r['installation_year'])),x['item_code']))
        peer=peers[0] if peers else None
        gap=abs(int(peer['installation_year'])-int(r['installation_year'])) if peer else None
        spare='SPARE' in (r['item_code']+' '+r['equipment_name']).upper() or '(구' in r['item_code']
        if spare:bucket='예비·구설비 표기 확인'
        elif r['service_role']=='OTHER':bucket='용도 보완 우선'
        elif not peer:bucket='동일 조건 비교설비 없음'
        elif gap<=5:bucket='입력 특성 유사'
        else:bucket='설치연도 차이 큼'
        evidence.append({'candidate':r,'peer':peer,'year_gap':gap,'comparison_count':len(peers),'bucket':bucket})
    counts=Counter(r['bucket'] for r in evidence)
    m=evaluation['logistic']['mean_oof_metrics']
    lines=[
        '# 검사 설비와 유사한 미검사 열교환기 검토 보고서','',
        '작성일: 2026-10-30 · 대상: VCM1·VCM2 · 기준: 검사기록이 없으면 미검사로 분류','',
        '## 1. 검토 결론','',
        f"검사 {len(inspected)}대와 미검사 {len(candidates)}대를 비교한 결과, 미검사 중 **{len(selected)}대**가 과거 검사 설비의 특성에 가까운 것으로 분류되었다. 그러나 이번 입력 자료에는 미검사 사유가 없으므로, 실제 이유를 확정할 수 없다. 이 29대는 검사 누락이 확정된 설비가 아니라 **미검사 사유를 확인할 후보**다.",'',
        '단순 점수 순으로 검사계획을 만들기보다 예비·구설비 여부, 용도 정보, 비교설비의 적합성을 먼저 구분해야 한다. 같은 COOLER·HEATER로 분류되어도 실제 공정 역할·구조·유체가 다를 수 있다.','',
        '## 2. 자료와 입력 기준','',
        '| 항목 | 적용 내용 |','|---|---|',
        '| 원본 | Master_HeatExchanger_Team_process_install.xlsx |',
        '| 입력 | Excel I열 설치일의 연도, F열 설비Tag에서 얻은 라인, E열 공정, H열 설비내역에서 추출한 용도 |',
        '| 제외 | 공칭두께·감육률·측정두께·검사 상태·수명 및 Excel에 없는 JSON/DB 전용 값 |',
        '| 식별자 | 자산번호는 결합, Item No.는 같은 계열 그룹 구분에만 사용하며 학습 입력에서 제외 |',
        '| 정답 | DB 검사 이력 있음=1, 없음=0. DB 정보는 모델 입력값으로 보충하지 않음 |',
        '| 검증 | 같은 라인의 같은 코드 계열을 묶은 5분할 교차검증을 3개 시드로 반복 |',
        '| 후보 점수 | 해당 설비와 같은 계열을 학습에서 제외한 OOF 점수의 반복 평균 |','',
        '점수 0.5는 분류 결과에서 검토 후보를 구분한 기준이며 안전·검사 시급성 기준이 아니다. 점수는 보정된 검사 필요 확률이 아니다. 낮은 점수도 안전하거나 검사 불필요하다는 뜻이 아니다.','',
        '## 3. 후보 집계','',
        '| 구분 | 설비 수 |','|---|---:|',
        f'| 전체 미검사 | {len(candidates)} |',f'| 모델상 검사 그룹에 가까운 미검사 | {len(selected)} |',
        f"| 그중 VCM1 | {sum(x['candidate']['unit_code']=='VCM1' for x in evidence)} |",
        f"| 그중 VCM2 | {sum(x['candidate']['unit_code']=='VCM2' for x in evidence)} |",
        f'| 그 밖의 미검사: 이 결과만으로 검사 불필요 판정 불가 | {len(candidates)-len(selected)} |','',
        '| 검토 유형 | 설비 수 | 확인 방향 |','|---|---:|---|']
    actions={
        '입력 특성 유사':'같은 라인·공정·용도이며 설치연도 차이 5년 이내인 타계열 검사 설비와 선정 기준 비교',
        '예비·구설비 표기 확인':'실제 운전·예비·철거·교체 상태 및 현 설비와의 연결 확인',
        '용도 보완 우선':'OTHER를 실제 용도로 보완한 뒤 결과 재검토',
        '동일 조건 비교설비 없음':'모델 점수만으로 유사 설비라고 결론 내리지 말고 담당자 비교 필요',
        '설치연도 차이 큼':'동일 용도라도 연령·세대·구조 차이가 커 비교 적합성 확인'}
    for bucket in actions:lines.append(f'| {bucket} | {counts[bucket]} | {actions[bucket]} |')
    lines+=['','유형은 예비·구설비 표기 → OTHER → 비교설비 없음 → 연도 차이 순으로 하나씩 부여했다. 연도 차이 5년은 비교 설명을 위한 구분이며 검사 기준이 아니다. OTHER끼리는 용도가 같다고 인정하지 않는다.','',
        '## 4. 주요 설비별 검토','',
        '| 미검사 설비 | 확인된 비교 근거 | 아직 확인할 사항 |','|---|---|---|',
        '| VCM1 E-220B, 1972 | 같은 라인·공정의 REBOILER인 검사 설비 E-210A도 1972년 설치 | 실제 구조·운전조건과 검사 대상 선정 기준이 같은지, 별도 관리계획이 있는지 |',
        '| VCM1 E-103, 1971 | 같은 라인·공정의 REBOILER인 검사 설비 E-111도 1971년 설치 | 현 운전 상태·교체 이력·검사 적용성·계획 확인 |',
        '| VCM2 E-704, 1990 | 같은 라인·공정의 REBOILER인 검사 설비 E-210도 1990년 설치 | 같은 용도 분류 안에서 실제 구조·서비스가 다른지 확인 |',
        '| VCM2 E-513, 1990 | EDC 공정 INTERCHANGER인 검사 설비 E-130도 1990년 설치 | 검사방법 및 운전조건 차이, 미검사 결정 기록 확인 |',
        '| VCM2 E-506(구,Spare), 2010 | 높은 점수지만 원본 코드에 구·Spare 표기 | 운휴·예비·철거 여부를 확인하기 전 검사 누락으로 분류하지 않음 |',
        '| VCM1 E-805, 2007 / E-812(구,Spare), 1993 | 설비내역 또는 코드에 Spare 표기 | 예비 설비 관리기준과 실제 사용 이력 확인 |',
        '| VCM1 E-320 / VCM2 E-507·E-208 | 용도 추출이 OTHER여서 높은 점수의 해석 근거가 약함 | 실제 기능을 보완하고 재분류. OTHER 비교설비를 동종 설비로 간주하지 않음 |',
        '| VCM1 E-807 / E-230 | 같은 라인·공정·용도의 타계열 검사 설비를 찾지 못함 | 통계적 점수는 존재하지만 직접 비교 근거가 부족하므로 개별 기술검토 |',
        '| VCM1 E-805A·E-805B | 같은 조건의 검사 CONDENSER와 가장 가까운 설치연도 차이가 각각 50년·31년 | 단순 동종 설비 비교로 보기 어려움. 설치·교체·구조 차이 확인 |',
        '| VCM1 EC-801A·EC-801B·EC-401 | 같은 연도·라인·공정의 COOLER 검사 설비가 있음 | LUBE OIL COOLER와 비교 설비의 실제 서비스 차이 확인. 공통 COOLER 분류만으로 등가 판단 금지 |','',
        '## 5. “왜 미검사인가”의 확인 경로','',
        '| 가능한 설명: 현재는 미확정 | 확인할 자료 | 확인 후 처리 |','|---|---|---|',
        '| 예비·운휴·철거 또는 교체 전 설비 | 설비 운전 상태, 교체·폐기 기록, 현행 Item 연결 | 검사 대상 유지 여부와 현 설비 연결 정리 |',
        '| 구조·재질·접근성 때문에 검사방법이 다름 | 도면·사양서·검사 적용성 검토, 다른 검사방식 계획 | 적합한 검사방법과 관리계획 확인 |',
        '| 최근 설치·교체로 검사 시점이 아직 오지 않음 | 설치·교체 기록, 최초 검사 기준 및 예정일 | 정당한 일정이면 사유와 예정일 기록 |',
        '| 별도 정비계획이나 검사 제외 판단이 있음 | 승인된 검사계획·정비계획·검사 제외 사유 | 근거 문서와 재검토일 연결 |',
        '| 검사 대상 선정 또는 일정 반영에서 누락 | 위 사유가 없는지 확인 후 담당자 검토 | 검사 필요성을 판단해 계획 반영 여부 결정 |','',
        '위 표는 확인할 가설이며 실제 발생 원인으로 확정한 내용이 아니다. 사용자의 기준에 따라 이번 보고서의 검사 여부는 계속 검사기록 유무로 유지한다.','',
        '## 6. 담당자 검토 절차와 기록','',
        '1. 입력 특성이 유사한 설비부터 비교 설비의 실제 구조·서비스 적합성을 확인한다.',
        '2. 예비·구설비 표기 후보는 운영 상태부터 확인하고, OTHER 후보는 용도를 보완한다.',
        '3. 미검사 사유, 근거 문서, 현재 계획 여부, 적정 검사방법을 기록한다.',
        '4. 검사 필요·불필요·추가 확인을 담당자가 결정한다. 불필요 판단에는 적용 근거와 재검토 조건을 남긴다.',
        '5. 확인 결과를 별도 정답으로 축적한다. 현재 검사 이력 분류 결과를 그대로 검사 필요성 정답으로 복사하지 않는다.','',
        '| 기록 항목 | 입력 내용 |','|---|---|',
        '| 식별 | 라인·공정·열교환기 코드 |',
        '| 미검사 사유 | 확인된 사실을 기재, 미확정이면 확인 필요 표시 |',
        '| 근거 | 도면·관리기준·운전/교체 기록·계획 문서 번호 등 |',
        '| 검토 결과 | 검사 필요 / 검사 불필요 / 추가 확인 |',
        '| 후속 조치 | 검사방법·예정 시점 또는 추가 자료 요청 |',
        '| 검토 이력 | 검토자·검토일·재검토 조건 |','',
        '## 7. 모델 결과의 해석 범위','',
        f"주 모델의 교차검증 정확도는 {m['accuracy']*100:.1f}%, 재현율은 {m['recall']*100:.1f}%, ROC AUC는 {m['roc_auc']:.3f}다. 실제 미검사 104대 중 29대가 검사 그룹으로 예측됐고, 검사 108대 중 42대가 미검사 그룹으로 예측됐다. 이 불일치는 검토를 시작할 단서이며 누락이나 안전 문제의 증거가 아니다.",'',
        '설비 용도는 이름의 제한된 키워드로 추출했다. 같은 용도라도 유체·재질·열교환기 구조·공정 중요도는 다를 수 있다. 이 값들은 현재 Excel 마스터에 없어 모델 입력에서 제외했다. 212대의 내부 자료를 사용한 검증이며 외부 설비나 미래 검사 필요성에 대한 검증은 아니다.','',
        '## 부록 A. 미검사 검토 후보 29대','',
        '비교 설비는 같은 라인·공정·용도의 검사 설비 중 같은 코드 계열을 제외하고 설치연도 차이가 가장 작은 설비다. OTHER는 비교를 표시하지 않는다. 점수순 목록은 검사 시급성 순위가 아니다.','',
        '| 라인·공정 | 미검사 코드 | 설치연도 | 점수 | 검사 비교설비·설치연도 | 연도 차이 | 검토 유형 |',
        '|---|---|---:|---:|---|---:|---|']
    for e in evidence:
        r=e['candidate'];peer=e['peer'] if r['service_role']!='OTHER' else None
        comparison=f"{peer['item_code']} · {peer['installation_year']}" if peer else '직접 비교 근거 없음'
        gap=e['year_gap'] if peer else '-'
        lines.append(f"| {escape(r['unit_code'])} / {escape(r['process_code'])} | {escape(r['item_code'])} | {r['installation_year']} | {float(r['historical_selection_score_oof']):.3f} | {escape(comparison)} | {gap} | {e['bucket']} |")
    lines+=['','## 부록 B. 추적 정보','',
        f"- 실행: `{run.name}` · 모델 버전: `{manifest['version']}`",
        '- 원본 Excel 모델 입력 출처: feature_lineage.csv. 원본 행은 dataset.csv의 source_row로 확인한다.',
        '- 데이터 정리·제외 기준: feature_audit.csv 및 source_column_audit.csv.',
        '- 전체 104대 검토 목록: uninspected_review_candidates.csv. OOF 점수 및 그룹 평가 기록은 해당 실행 폴더에 보관한다.',
        '- 보고서 작성 과정에서 DB·검사계획·원본 Excel·모델을 변경하지 않았다.','']
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text('\n'.join(lines),encoding='utf-8')
    evidence_path=output.with_suffix('.evidence.json')
    evidence_path.write_text(json.dumps({'run':run.name,'threshold':.5,'counts':dict(counts),'candidates':evidence},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'report':str(output),'candidate_count':len(selected),'review_groups':dict(counts)}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();print(json.dumps(build(args.run,args.output),ensure_ascii=False))
