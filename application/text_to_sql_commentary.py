"""Bounded local result narration, with signed server-owned evidence."""
import json
import os
import re
import subprocess
import sys

from iris2.hx_configuration import APP_DIR
from iris2.llm_integration.model_config import load_local_runtime_config
from iris2.llm_integration.text_to_sql import QueryRejected


def evidence(result):
    rows=result['rows']
    keys=['heat_exchanger_id','equipment_tag','remaining_display','recommendation_date','maximum_loss','life_source']
    return dict(total_rows=len(rows),matched_count=result.get('matched_count',len(rows)),
        missing_life=sum(r.get('remaining_life_years') is None for r in rows),
        missing_recommendation=sum(not r.get('recommendation_date') for r in rows),
        short_life=sum(r.get('remaining_life_years') is not None and r['remaining_life_years']<=5 for r in rows),
        examples=[{k:r.get(k) for k in keys} for r in rows[:10]])


def validate(payload, facts):
    text=payload.get('text') if isinstance(payload,dict) else None
    if not isinstance(text,str) or not 1<=len(text.strip())<=1800:
        raise QueryRejected('로컬 모델의 종합 의견 형식을 확인할 수 없습니다.')
    if re.search(r'안전하다|안전합니다|운전\s*가능|즉시\s*교체|확정\s*판정|절대',text):
        raise QueryRejected('조회 근거를 넘어선 판단이 포함되어 종합 의견을 표시하지 않습니다.')
    available=set(re.findall(r'\d+(?:\.\d+)?',json.dumps(facts,ensure_ascii=False)))
    if not set(re.findall(r'\d+(?:\.\d+)?',text))<=available:
        raise QueryRejected('조회 결과에 없는 수치가 포함되어 종합 의견을 표시하지 않습니다.')
    return text.strip()


def generate(facts):
    config=load_local_runtime_config(APP_DIR/'llm_integration/models.local.json')
    name=config.models[config.default_model_key].model_name
    if not facts['total_rows']:
        return dict(status='empty',text='조건에 맞는 열교환기가 없어 종합 의견을 생성하지 않았습니다.',model=name)
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','LLAMA_CPP_LIB_PATH','LLAMA_N_GPU_LAYERS','LLAMA_N_CTX'):
        env.pop(key,None)
    env.update(PYTHONIOENCODING='utf-8',LLAMA_N_THREADS='8',LLAMA_N_GPU_LAYERS='0')
    try:
        process=subprocess.run([sys.executable,str(APP_DIR/'tools/summarize_text_to_sql.py')],
            input=json.dumps(facts,ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',
            cwd=APP_DIR,env=env,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=json.loads(process.stdout)
    except (subprocess.TimeoutExpired,ValueError) as exc:
        raise QueryRejected('로컬 종합 의견을 생성하지 못했습니다. 조회 표는 그대로 확인할 수 있습니다.') from exc
    if process.returncode or output.get('error'):
        raise QueryRejected('로컬 모델 실행에 실패했습니다. 조회 표는 그대로 확인할 수 있습니다.')
    return dict(status='generated',text=validate(output,facts),model=name,
                scope='조회 표 전체의 집계와 앞 10대의 상세 근거',example_count=len(facts['examples']))
