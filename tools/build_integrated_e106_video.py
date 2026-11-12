"""Integrate the E-106 walkthrough with captured business-menu operations."""
import json
from pathlib import Path
import build_e106_video as editor

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'outputs/e106_precision_v4'
OLD=ROOT/'outputs/menu_demo_v2'
DEST=ROOT/'outputs/integrated_e106_v5'
DEST.mkdir(parents=True,exist_ok=True)
editor.NEW=DEST
editor.EDIT=DEST/'edited'
editor.EDIT.mkdir(exist_ok=True)

def card(title,caption,chapter,seconds=10):
    return dict(title=title,caption=caption,chapter=chapter,seconds=seconds,path=None)

old=json.loads((OLD/'steps.json').read_text(encoding='utf-8'))
new=json.loads((SOURCE/'steps.json').read_text(encoding='utf-8'))
motion=json.loads((SOURCE/'motion.json').read_text(encoding='utf-8'))
steps=[card('IRIS2 업무 안내 · E-106 정밀분석 통합판',
    '설비 조회에서 E-106 정밀분석으로 이어진 뒤 설비 관리, 예측·계산, 검사·정비와 내보내기 기능을 설명합니다.','영상 안내',12)]

def append_old(ids,chapter):
    for n in ids:
        s=old[n-1]
        steps.append(dict(title=s['section'],caption=s['caption'],chapter=chapter,
            seconds=2 if s['caption'].startswith('클릭:') else 10,
            path=OLD/s['file'],mark=s.get('pointer')))

append_old([1,2,3,4],'설비 조회와 업무 진입')
steps.append(card('E-106 정밀분석 시나리오',
    '지금부터 정밀분석 대상은 VCM2의 E-106입니다. 검색 키를 입력하고 조회한 뒤 Tube 12-16을 중심으로 분석 결과와 3D 기능을 확인합니다.','E-106 분석 진입',12))
for i,s in enumerate(new):
    if i==65:
        for j,m in enumerate(motion):
            dt=(motion[j+1]['time_ms']-m['time_ms'])/1000 if j+1<len(motion) else .1
            steps.append(dict(title='E-106 3D 실제 드래그 회전',caption='3D 배경을 실제로 드래그하여 E-106 배열을 회전합니다.',
                chapter=s['chapter'],seconds=max(.04,dt),path=SOURCE/m['file'],url='/exchangers/151/tube-map',motion=True))
    steps.append(dict(s,path=SOURCE/s['file']))
steps.append(card('분석 결과를 업무에 연결',
    'E-106 정밀분석 설명을 마쳤습니다. 이어지는 원 영상의 업무 메뉴에서는 각 화면에 표시된 설비와 입력값을 기준으로 관리 기능을 설명합니다.','업무 메뉴 연결',12))
groups=[([5,6,7,8,9,10,11,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32],'설비 입력과 Tube 관리'),
    (list(range(57,73))+list(range(136,146)),'예측과 API 510'),
    (list(range(91,123)),'검사이력과 검사계획'),
    (list(range(123,136)),'정비 업무'),
    (list(range(146,157)),'내보내기와 표시 설정')]
for ids,chapter in groups:
    append_old(ids,chapter)
steps.append(card('업무 안내 마무리',
    '설비를 조회하고 정밀분석에서 측정값과 계산 가정을 확인한 뒤 검사·정비 업무로 연결합니다. E-106 분석의 예측값은 가정에 따른 결과이며 실제 작업 완료 기록과 구분합니다.','마무리',14))

if __name__=='__main__':
    result=editor.build(steps,'IRIS2_업무안내_E-106_정밀분석_통합판')
    # A reviewable scenario with the precise timings and the actual click script.
    text=['# IRIS2 업무 안내 · E-106 정밀분석 통합 시나리오','',
        '정밀분석은 VCM2 E-106을 조회 키로 사용합니다. 데이터 점검 메뉴 소개는 제외합니다.',
        '한국어 자막 / 음성 없음 / 실제 조작 전후 화면 편집 및 3D 드래그 연속 캡처.','',
        '기존 정밀분석 구간을 E-106 영상으로 교체하고 업무 메뉴를 이어 붙였습니다. 이후 업무 메뉴는 원 영상에 표시된 설비를 사용하며 E-106의 결과로 설명하지 않습니다.','',
        '| 시작 | 종료 | 장면 | 설명 흐름 |','|---|---|---|---|']
    flow=['조회 조건과 대상 설비 확인','E-106 검색과 분석 대상 확정','Map·표 연동 및 위험·주의·정상 Tube 비교','표시 옵션과 화면 크기 조절','Tube 12-16의 속도 배율과 예측 비교','허용 개수·예측 대상·한도 미도달 해석','선택 Tube 이력 확인','선택 Tube를 3D로 전달','분리·회전·확대·초기화·배열 복귀','검사연도·색상 기준·라벨 전환','업무 관리 기능의 입력·저장·조회 확인']
    for ch in result['chapters']:
        text.append(f"| {editor.ts(ch['start'])} | {editor.ts(ch['end'])} | {ch['title']} | 해당 메뉴를 열고 실제 조작 결과를 설명 |")
    text+=['','## 핵심 설명 순서','']+['- '+x for x in flow]
    text+=['','## 장면별 클릭 및 자막 대본','']
    elapsed=0
    for i,s in enumerate(steps):
        if not s.get('motion') or not steps[i-1].get('motion'):
            text += [f"### {editor.ts(elapsed)} · {s['title']}",'',s['caption'],'']
        elapsed+=s['seconds']
    (DEST/'통합_시나리오.md').write_text('\n'.join(text),encoding='utf-8-sig')
    (DEST/'verification.json').write_text(json.dumps(dict(video=result,
        replaced='Previous precision-analysis section replaced by E-106 only',
        excluded=['DB 상태 점검','품질 이슈','PDF OCR 검토','ML 데이터 품질 점검'],
        source_screen_count=len(new),business_source_ids=[n for ids,_ in groups for n in ids]),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
