"""Offline historical inspection-selection classifier. Never writes operational DB."""
from __future__ import annotations
import csv
import hashlib
import json
import platform
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

VERSION = 'historical-inspection-selection-v2-excel-only'
FEATURES = ('installation_year', 'unit_code', 'process_code', 'service_role')
FEATURE_LINEAGE = {
    'installation_year':('I','설치일','연도 추출'),
    'unit_code':('F','설비Tag','US-VC → VCM1, US-EV → VCM2'),
    'process_code':('E','공정','공백·문자 정규화'),
    'service_role':('H','설비내역','용도 키워드 추출'),
}
SEEDS = (42, 137, 2026)
EXCLUDED = {
    'tube_nominal_thickness_mm': '검사 시 입력 정보: 사용자 확인에 따라 제외',
    'wall_loss_percent': 'POST_INSPECTION',
    'minimum_wall_thickness_mm': 'POST_INSPECTION',
    'corrosion_rate': 'POST_INSPECTION',
    'remaining_life': 'POST_INSPECTION',
    'inspection_status': 'TARGET_PROXY',
    'inspection_count': 'LABEL_ONLY',
    'iris_applicability': 'TARGET_PROXY',
    'tube_material': 'NOT_PRESENT_IN_CURRENT_EXCEL_MASTER; NO_DB_JSON_FALLBACK',
    'tube_fluid': 'NOT_PRESENT_IN_CURRENT_EXCEL_MASTER; NO_DB_JSON_FALLBACK',
    'tube_count': 'NOT_PRESENT_IN_CURRENT_EXCEL_MASTER; NO_DB_JSON_FALLBACK',
    'tube_length_mm': 'NOT_PRESENT_IN_CURRENT_EXCEL_MASTER; NO_DB_JSON_FALLBACK',
    'equipment_code': 'JOIN_ONLY_IDENTIFIER',
    'item_code': 'GROUP_ONLY_IDENTIFIER',
    'equipment_name': 'CONTROLLED_SERVICE_ROLE_ONLY',
    'production_team': 'CONSTANT_IN_SCOPE',
    'operating_status': 'TIMING_UNVERIFIED',
}

def normalized(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or '')).strip()).upper()

def asset_key(value):
    return re.sub(r'\.0$', '', normalized(value))

def parse_install_date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    if isinstance(value, (int, float)):
        from openpyxl.utils.datetime import from_excel
        parsed = from_excel(value)
        return parsed.date() if isinstance(parsed, datetime) else parsed
    raw = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%Y%m%d', '%Y-%m-%d %H:%M:%S'):
        try: return datetime.strptime(raw, fmt).date()
        except ValueError: pass
    raise ValueError('Missing or invalid installation date')

def service_role(name):
    name = normalized(name)
    for keyword, role in [('REBOILER','REBOILER'), ('CHILLER','CHILLER'), ('CONDENSER','CONDENSER'),
                          ('ABSORBER','ABSORBER'), ('AIR COOLER','AIR_COOLER'),
                          ('AFTER COOLER','AFTER_COOLER'), ('COOLER','COOLER'),
                          ('HEATER','HEATER'), ('BOILER','BOILER'), ('ECONOMIZER','ECONOMIZER'),
                          ('EVAPORATOR','EVAPORATOR'), ('INTERCHANGER','INTERCHANGER')]:
        if keyword in name: return role
    return 'OTHER'

def family_group(unit, item):
    item = normalized(item)
    found = re.match(r'^([A-Z]+)[- ]?(\d+)', item)
    return normalized(unit) + ':' + ('-'.join(found.groups()) if found else item)

def unit_from_master_tag(tag):
    tag=normalized(tag)
    if tag.startswith('US-VC-'):return 'VCM1'
    if tag.startswith('US-EV-'):return 'VCM2'
    raise ValueError('Unknown master tag prefix; DB/JSON fallback is prohibited')

def write_csv(path, rows):
    rows = list(rows)
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['empty'])
        writer.writeheader(); writer.writerows(rows)

def collect(source, db_rows, as_of):
    import openpyxl
    wb = openpyxl.load_workbook(source, read_only=True, data_only=True)
    if len(wb.sheetnames) != 1: raise ValueError('Expected one source sheet')
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True)); wb.close()
    if [str(x or '') for x in all_rows[0][:3]] != ['No.', '상태', '설비코드']:
        raise ValueError('Unexpected master header; review source mapping')
    by_asset = defaultdict(list)
    for number, values in enumerate(all_rows[2:], 3):
        if values[2] is not None: by_asset[asset_key(values[2])].append((number, values))
    cleaned, rejected = [], []
    seen = set()
    for db in db_rows:
        ident = int(db['heat_exchanger_id'])
        if ident in seen: raise ValueError('Duplicate database exchanger')
        seen.add(ident)
        if db['unit_code'] not in ('VCM1', 'VCM2'): raise ValueError('Out-of-scope row')
        candidates = by_asset.get(asset_key(db['equipment_code']), [])
        reason = None
        if len(candidates) != 1: reason = 'SOURCE_KEY_MISSING_OR_DUPLICATED'
        if not reason:
            rowno, raw = candidates[0]
            try: installed = parse_install_date(raw[8])
            except (ValueError, TypeError, OverflowError): reason = 'INSTALL_DATE_INVALID'
            if not reason and (not isinstance(installed, date) or installed.year < 1900 or installed > as_of): reason = 'INSTALL_DATE_OUT_OF_RANGE'
            if not normalized(raw[4]): reason = 'PROCESS_MISSING'
            if not normalized(raw[6]): reason = 'ITEM_CODE_MISSING_FOR_GROUPING'
            try: source_unit=unit_from_master_tag(raw[5])
            except ValueError: reason='MASTER_TAG_UNIT_UNMAPPED'
        if reason:
            rejected.append({'heat_exchanger_id':ident, 'reason':reason}); continue
        target = int(int(db['inspection_count']) > 0)
        cleaned.append({'heat_exchanger_id':ident, 'asset_number':asset_key(raw[2]),
                        'item_code':str(raw[6]), 'equipment_name':str(raw[7] or ''),
                        'source_sheet':ws.title, 'source_row':rowno, 'source_install_date':installed.isoformat(),
                        'db_install_date':str(db.get('install_date') or '')[:10],
                        'installation_year':installed.year, 'unit_code':source_unit,
                        'source_tag':str(raw[5]), 'db_unit_code':db['unit_code'],
                        'process_code':normalized(raw[4]), 'service_role':service_role(raw[7]),
                        'needs_role_review':service_role(raw[7])=='OTHER',
                        'family_group':family_group(source_unit,raw[6]), 'inspected':target})
    inventory = []
    for index in range(ws.max_column):
        letter = openpyxl.utils.get_column_letter(index+1)
        counts = {flag:0 for flag in (0,1)}
        for r in cleaned:
            value = all_rows[r['source_row']-1][index]
            counts[r['inspected']] += int(value is not None and str(value).strip() != '')
        decision = {2:'JOIN_ONLY',3:'EXCLUDE_CONSTANT',4:'INCLUDE_PROCESS',5:'DERIVE_UNIT_ONLY',6:'GROUP_ONLY',7:'DERIVE_ROLE_ONLY',8:'INCLUDE_YEAR_ONLY'}.get(index,'EXCLUDE_EMPTY_OR_IDENTIFIER')
        inventory.append({'source_column':letter, 'header_row1':str(all_rows[0][index] or ''),
                          'header_row2':str(all_rows[1][index] or ''), 'decision':decision,
                          'nonempty_inspected':counts[1], 'nonempty_uninspected':counts[0]})
    return cleaned, rejected, inventory

def matrix(rows):
    import numpy as np
    return np.array([[r[key] for key in FEATURES] for r in rows], dtype=object)

def make_model(kind):
    from sklearn.compose import ColumnTransformer
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.linear_model import LogisticRegression
    from sklearn.tree import DecisionTreeClassifier
    from sklearn.dummy import DummyClassifier
    if kind == 'majority': return DummyClassifier(strategy='prior')
    if kind == 'year_line_baseline':
        transform = ColumnTransformer([('year',StandardScaler(),[0]), ('line',OneHotEncoder(handle_unknown='ignore'),[1])])
    else:
        transform = ColumnTransformer([('year',StandardScaler(),[0]), ('categories',OneHotEncoder(handle_unknown='infrequent_if_exist',min_frequency=3),[1,2,3])])
    estimator = DecisionTreeClassifier(max_depth=3,min_samples_leaf=8,random_state=42,class_weight='balanced') if kind=='shallow_tree' else LogisticRegression(C=1.0,max_iter=2000,class_weight='balanced',random_state=42)
    return Pipeline([('preprocess',transform),('classifier',estimator)])

def grouped_splits(rows, seed):
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold
    y=np.array([r['inspected'] for r in rows]); groups=np.array([r['family_group'] for r in rows])
    splits=list(StratifiedGroupKFold(n_splits=5,shuffle=True,random_state=seed).split(matrix(rows),y,groups))
    for train,test in splits:
        if set(groups[train]) & set(groups[test]): raise ValueError('Group leakage')
        if len(set(y[train]))!=2 or len(set(y[test]))!=2: raise ValueError('Fold missing target class')
    return splits

def metrics(y, scores):
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, precision_score, recall_score, f1_score, roc_auc_score, average_precision_score, brier_score_loss, confusion_matrix
    pred=(scores>=.5).astype(int)
    return {'accuracy':accuracy_score(y,pred),'balanced_accuracy':balanced_accuracy_score(y,pred),
            'precision':precision_score(y,pred,zero_division=0),'recall':recall_score(y,pred,zero_division=0),
            'f1':f1_score(y,pred,zero_division=0),'roc_auc':roc_auc_score(y,scores),
            'average_precision':average_precision_score(y,scores),'brier':brier_score_loss(y,scores),
            'confusion_matrix_labels_0_1':confusion_matrix(y,pred,labels=[0,1]).tolist()}

def predict_records(bundle, rows):
    if bundle.get('features') != list(FEATURES): raise ValueError('Model feature contract mismatch')
    return bundle['model'].predict_proba(matrix(rows))[:,1]

def train(source, db_rows, output, as_of):
    import numpy as np
    import joblib
    import sklearn
    output=Path(output)
    if output.exists(): raise ValueError('Output directory already exists; choose a new run name')
    output.mkdir(parents=True)
    rows,rejected,inventory=collect(source,db_rows,as_of)
    if len(rows)<30 or min(Counter(r['inspected'] for r in rows).values())<10: raise ValueError('Insufficient two-class dataset')
    if set(r['inspected'] for r in rows)!={0,1}: raise ValueError('Both target classes required')
    write_csv(output/'dataset.csv',rows); write_csv(output/'source_column_audit.csv',inventory)
    audit=[{'field':key,'decision':'INCLUDE','reason':f'EXCEL_ONLY:{FEATURE_LINEAGE[key][0]}:{FEATURE_LINEAGE[key][1]}'} for key in FEATURES]
    audit += [{'field':key,'decision':'EXCLUDE','reason':reason} for key,reason in EXCLUDED.items()]
    write_csv(output/'feature_audit.csv',audit)
    write_csv(output/'feature_lineage.csv',[{'feature':key,'source_kind':'EXCEL_MASTER','column':item[0],'header':item[1],'transform':item[2],'db_json_fallback':'PROHIBITED'} for key,item in FEATURE_LINEAGE.items()])
    X=matrix(rows); y=np.array([r['inspected'] for r in rows]); splits={seed:grouped_splits(rows,seed) for seed in SEEDS}
    fold_rows=[]; evaluation={}; predictions={}
    for seed,folds in splits.items():
        for fold,(_,test) in enumerate(folds,1):
            fold_rows.extend({'heat_exchanger_id':rows[i]['heat_exchanger_id'],'family_group':rows[i]['family_group'],'seed':seed,'test_fold':fold} for i in test)
    write_csv(output/'fold_assignments.csv',fold_rows)
    for name in ('majority','year_line_baseline','logistic','shallow_tree'):
        repeated=[]; repeat_metrics=[]
        for seed,folds in splits.items():
            scores=np.full(len(rows),np.nan)
            for train_idx,test_idx in folds:
                model=make_model(name); model.fit(X[train_idx],y[train_idx]); scores[test_idx]=model.predict_proba(X[test_idx])[:,1]
            if np.isnan(scores).any(): raise ValueError('Incomplete held-out predictions')
            repeated.append(scores);repeat_metrics.append({'seed':seed,**metrics(y,scores)})
        mean_scores=np.mean(repeated,axis=0);predictions[name]=mean_scores
        evaluation[name]={'repeats':repeat_metrics,'mean_oof_metrics':metrics(y,mean_scores),
                          'auc_repeat_range':[min(m['roc_auc'] for m in repeat_metrics),max(m['roc_auc'] for m in repeat_metrics)]}
    # Prespecified primary model; comparison results do not tune or select it.
    primary=make_model('logistic');primary.fit(X,y)
    bundle={'version':VERSION,'features':list(FEATURES),'model':primary,'target':'historical_inspection_record_present','as_of':as_of.isoformat()}
    joblib.dump(bundle,output/'model.joblib')
    sample=[]
    for i,r in enumerate(rows):
        sample.append({**r,'historical_selection_score_oof':round(float(predictions['logistic'][i]),6),
                       'predicted_history_class':int(predictions['logistic'][i]>=.5),
                       'review_status':'UNREVIEWED','review_label':'','review_reason':''})
    write_csv(output/'oof_predictions.csv',sample)
    subgroup=[]
    for field in ('unit_code','process_code','installation_decade'):
        for value in sorted({str((r['installation_year']//10)*10) if field=='installation_decade' else r[field] for r in rows}):
            indices=[i for i,r in enumerate(rows) if (str((r['installation_year']//10)*10) if field=='installation_decade' else r[field])==value]
            pred=(predictions['logistic'][indices]>=.5).astype(int);actual=y[indices]
            subgroup.append({'group_field':field,'group_value':value,'n':len(indices),'inspected':int(actual.sum()),
                             'accuracy':float(np.mean(pred==actual)),
                             'false_positive':int(np.sum((pred==1)&(actual==0))),
                             'false_negative':int(np.sum((pred==0)&(actual==1)))})
    write_csv(output/'subgroup_metrics.csv',subgroup)
    candidates=sorted((r for r in sample if not r['inspected']),key=lambda r:-r['historical_selection_score_oof'])
    write_csv(output/'uninspected_review_candidates.csv',candidates)
    names=primary.named_steps['preprocess'].get_feature_names_out();coef=primary.named_steps['classifier'].coef_[0]
    write_csv(output/'model_coefficients.csv',[{'encoded_feature':str(name),'log_odds_coefficient':float(value)} for name,value in sorted(zip(names,coef),key=lambda pair:-abs(pair[1]))])
    source_hash=hashlib.sha256(Path(source).read_bytes()).hexdigest()
    dataset_hash=hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    quality={'scope_db_rows':len(db_rows),'accepted_rows':len(rows),'rejected':rejected,'class_counts':dict(Counter(r['inspected'] for r in rows)),
             'family_groups':len(set(r['family_group'] for r in rows)),
             'date_mismatch_ids':[r['heat_exchanger_id'] for r in rows if r['source_install_date']!=r['db_install_date']],
             'unit_mismatch_ids':[r['heat_exchanger_id'] for r in rows if r['unit_code']!=r['db_unit_code']],
             'installation_date_clusters':Counter(r['source_install_date'] for r in rows).most_common(8),
             'unknown_role_count':sum(r['service_role']=='OTHER' for r in rows)}
    manifest={'version':VERSION,'as_of':as_of.isoformat(),'source_path':str(Path(source).resolve()),'source_sha256':source_hash,'dataset_sha256':dataset_hash,
              'source_code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'features':list(FEATURES),'excluded':EXCLUDED,
              'feature_lineage':FEATURE_LINEAGE,'input_policy':'EXCEL_MASTER_ONLY; JSON_ONLY_VALUES_PROHIBITED; DB_KEYS_LABEL_AUDIT_ONLY',
              'primary_model':'logistic_prespecified','validation':'5-fold stratified family-group CV, 3 seeds; preprocessing fit within folds',
              'seeds':list(SEEDS),'python':platform.python_version(),'sklearn':sklearn.__version__,
              'db_access':'READ ONLY consistent snapshot','score_meaning':'uncalibrated historical selection similarity; not inspection need, damage, safety or failure probability',
              'limitation':'Current master attributes matched to any historical inspection; not prospective validation. No external holdout. Ranking requires reviewer assessment.'}
    for name,value in [('manifest',manifest),('data_quality',quality),('evaluation',evaluation)]:
        (output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    write_report(output,rows,quality,evaluation,candidates)
    return {'output':str(output),'rows':len(rows),'classes':quality['class_counts'],'groups':quality['family_groups'],'primary':evaluation['logistic']['mean_oof_metrics']}

def write_report(output,rows,quality,evaluation,candidates):
    lines=['# 검사 이력 분류 모델 검토 결과','',
           '목적: 검사 전에 알 수 있는 설비 특성으로 과거 검사 대상 선정 패턴을 분석한다. 점수는 검사 필요성·손상·고장 확률이 아니다.','',
           f"대상 {len(rows)}대 · 검사 {sum(r['inspected'] for r in rows)}대 · 미검사 {sum(not r['inspected'] for r in rows)}대 · 코드 계열 그룹 {quality['family_groups']}개.",'',
           '## 데이터 수집·정리·제외','',
           '- 원본 마스터의 자산번호로 DB와 일대일 대조했다. 원본 행 번호·설치일·코드를 dataset.csv에 남겼다.',
           '- 모든 모델 입력은 Excel 셀에서만 얻는다. DB는 대상 키·검사 여부 정답·대조에만 사용하며 JSON 전용 값이나 DB 값으로 빈 입력을 보충하지 않는다.',
           '- 생산라인도 Excel F열 설비Tag의 US-VC/US-EV 접두어에서 얻는다. 매핑되지 않은 값은 제외하며 DB 생산라인으로 대체하지 않는다. 항목별 출처는 feature_lineage.csv에 기록한다.',
           '- 설치일 형식·범위·중복 키·공정 누락을 검사하고, 처리 불가능한 행은 제외 사유를 기록한다.',
           '- 입력은 설치연도·생산라인·공정·설비명에서 규칙으로 추출한 용도 4개다. 원본 119개 열의 실제 값 유무·포함/제외 결정은 source_column_audit.csv에 기록한다.',
           '- 공칭두께는 사용자 확인에 따라 검사 후 입력 정보로 제외했다. 감육률·측정두께·수명·검사 상태도 제외한다.',
           '- 현재 원본 마스터에는 재질·유체·공칭두께·튜브 수량·길이 열의 값이 없다. JSON/DB 전용 값은 제외한다. 자산번호와 설비 코드는 결합·그룹 구분용이며 학습하지 않는다.',
           '- 같은 생산라인의 E-201A/B 등 같은 코드 계열을 같은 평가 그룹에 둔다. 원본 자유 텍스트 대신 제한된 용도 분류만 사용한다.','',
           f"원본/DB 설치일 불일치 {len(quality['date_mismatch_ids'])}대 · 데이터 제외 {len(quality['rejected'])}대 · 용도 OTHER {quality['unknown_role_count']}대.",'',
           '## 검증 결과','',
           '5개 그룹 분할을 3개 고정 시드로 반복했다. 같은 설비 계열은 학습과 평가에 동시에 들어가지 않는다. 인코딩·표준화는 학습 폴드 안에서만 학습한다. 주 모델은 성능 비교 전에 로지스틱 회귀로 고정했다. 아래는 반복 평가의 행별 평균 OOF 점수 기준이며 독립 외부 시험 성능이 아니다.','',
           '| 모델 | 정확도 | 균형정확도 | 정밀도 | 재현율 | F1 | ROC AUC |','|---|---:|---:|---:|---:|---:|---:|']
    for name,item in evaluation.items():
        m=item['mean_oof_metrics'];lines.append(f"| {name} | {m['accuracy']:.3f} | {m['balanced_accuracy']:.3f} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['roc_auc']:.3f} |")
    lines+=['','## 미검사 검토 후보 상위 15대','',
            '해당 행을 학습에서 제외한 OOF 점수로 정렬했다. 과거 검사 설비와 특성이 비슷한 미검사 설비이며 자동 검사 지시가 아니다. 전체 104대는 uninspected_review_candidates.csv에서 확인·수정할 수 있다.','',
            '| 라인 | 공정 | 코드 | 설치연도 | 용도 | 이력 유사 점수 |','|---|---|---|---:|---|---:|']
    for r in candidates[:15]:lines.append(f"| {r['unit_code']} | {r['process_code']} | {r['item_code']} | {r['installation_year']} | {r['service_role']} | {r['historical_selection_score_oof']:.3f} |")
    lines+=['','## 해석과 다음 단계','',
            '- 공정·연대·용도와 과거 검사 여부의 연관성을 보여준다. 검사하지 않은 이유나 실제 위험을 입증하지 않는다.',
           '- 설치일이 특정 날짜에 집중되어 있고 현재 마스터와 과거 이력을 결합했으므로 교체 설비·운휴·예비 설비 여부를 추가 확인한다.',
           '- needs_role_review=True인 후보는 설비명에서 용도를 확정하지 못했다. 용도 확인을 먼저 하고 높은 점수를 위험 판단으로 해석하지 않는다.',
           '- 라인·공정·설치연대별 오분류는 subgroup_metrics.csv에서 따로 확인한다.',
            '- 212대의 작은 표본이며 같은 공정 밖으로 일반화하는 능력은 검증하지 않았다. 반복 AUC 범위는 evaluation.json에 기록하며 신뢰구간이 아니다.',
            '- 담당자의 검사 필요/불필요/추가확인 및 사유를 축적한 후 실제 검사 필요성 모델을 별도로 학습한다.',
            '- 운영 DB·검사계획·웹 UI를 수정하지 않는다. model.joblib은 이 실행에서 생성한 로컬 파일만 신뢰해 로드한다.','']
    (output/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
