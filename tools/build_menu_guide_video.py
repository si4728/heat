"""Build the local Korean menu guide MP4, captions and narration script."""
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/menu_guide_20261026'
FRAMES = OUT / 'frames'
FRAMES.mkdir(parents=True, exist_ok=True)
FONT = 'C:/Windows/Fonts/malgun.ttf'
BOLD = 'C:/Windows/Fonts/malgunbd.ttf'

# group, title, screenshot, three actions, three caption/script segments
SCENES = [
('시작','IRIS2 화면 메뉴 안내','dashboard', ['메뉴 구조 살펴보기','메뉴별 조작과 결과 이해하기','VCM1·VCM2 중심으로 활용하기'], ['지능형 열교환기 관리시스템 IRIS2의 화면 메뉴와 주요 기능을 소개합니다.','실제 화면 캡처와 조작 순서 안내를 함께 보면서 각 메뉴의 역할을 살펴보겠습니다.','이 영상은 한국어 자막 안내입니다. 데이터 저장이나 승인 작업을 실행한 녹화는 아닙니다.']),
('시작','메뉴 구조와 접근 권한','dashboard',['왼쪽 업무 메뉴 선택','상단 정밀 분석 진입','계정 권한에 따른 메뉴 확인'],['왼쪽에는 대시보드, 열교환기 관리, 검사 관리, 정비 관리, 기본 설정이 있습니다.','정밀 분석은 화면 상단의 업무 메뉴에서 엽니다. 설비 상세에서도 관련 기능으로 이동합니다.','계정의 조회·편집 권한에 따라 표시 메뉴가 달라집니다. PDF·OCR 검토는 지정 권한이 필요합니다.']),
('대시보드','운영 현황과 데이터 입력률','dashboard',['현황 카드 확인','수량 미등록 목록 펼치기','필요한 설비로 이동'],['대시보드는 등록 열교환기, 검사이력, Tube 결과, 검사계획과 품질 이슈를 요약합니다.','상단의 Tube 수량 미등록 목록을 펼쳐 공정이나 설비코드로 보완 대상을 찾습니다.','사양 수량 대비 Tube 등록률과 등록된 Tube의 정보 완성도는 분모가 서로 다릅니다.']),
('대시보드','QR 검색과 현장 간편조회','dashboard',['QR 검색 선택','카메라 사용 환경 확인','대상 설비 요약 조회'],['QR 검색은 현장에서 열교환기를 빠르게 식별하고 요약 정보를 확인하는 진입점입니다.','QR-code 읽기를 선택하고 카메라 권한과 브라우저 지원 환경을 확인합니다.','대상 설비를 확인한 뒤 상세 정보로 이동합니다. 실제 카메라 동작은 단말별 확인이 필요합니다.']),
('열교환기 관리','열교환기 목록','exchangers',['공정·설비 조건 선택','검색 결과 확인','대상 설비 상세 열기'],['열교환기 관리의 열교환기 목록에서 공정과 설비 조건을 이용해 대상을 찾습니다.','설비코드와 이름, 주요 사양 및 검사 정보를 확인하고 원하는 설비를 선택합니다.','설비 상세는 Tube 관리, Map, 계산과 보고서로 이어지는 기준 화면입니다.']),
('열교환기 관리','열교환기 입력과 정보 수정','exchangers',['기준 조직과 설비 식별 입력','사양·관리 기준 입력','검토 후 저장'],['열교환기 입력은 새로운 설비의 식별정보와 공정, 기술 사양을 등록하는 메뉴입니다.','기존 설비는 상세 화면의 정보 수정에서 변경합니다. 단위와 사양의 적용 기준을 확인합니다.','필수 항목과 중복 여부를 검토한 뒤 저장합니다. 이 영상에서는 실제 저장을 실행하지 않습니다.']),
('열교환기 관리','JSON 로드','exchangers',['JSON 파일과 대상 공정 확인','검증 결과·경고 확인','중복과 적재 결과 확인'],['JSON 로드는 구조화된 검사 자료를 검증하고 데이터베이스에 반영하는 메뉴입니다.','파일과 대상 공정을 확인한 뒤 처리 결과와 오류·경고 내용을 검토합니다.','중복 자료와 원본 근거를 확인합니다. 경고가 있는 자료를 곧바로 검증 완료로 해석하지 않습니다.']),
('열교환기 관리','PDF·OCR 검토','inspections',['지정 권한으로 메뉴 열기','원본 PDF와 추출 내용 대조','근거 확인 후 검토 처리'],['PDF·OCR 검토는 추출 자료를 원본 PDF와 대조하는 지정 권한 사용자용 메뉴입니다.','문서별 검토 상태와 원본 근거를 확인하고 추출 결과의 누락이나 불일치를 검토합니다.','승인은 검토 근거를 확인한 후 수행합니다. 이 영상은 승인 처리를 실행하지 않습니다.']),
('열교환기 관리','Excel Export','exchangers',['내보내기 메뉴 선택','Excel 파일 다운로드','기준 사양과 수량 확인'],['Excel Export는 열교환기와 Tube 관리 자료를 Excel 파일로 내려받는 기능입니다.','다운로드한 자료에서 설비 식별정보와 사양, Tube 관련 항목을 확인합니다.','현재 사양의 수량과 개별 등록 Tube 수를 구분해 보고서와 후속 검토에 활용합니다.']),
('설비 연결 기능','설비 상세와 인쇄 보고서','exchangers',['기술 사양과 관리 기준 확인','검사이력·Tube 현황 조회','인쇄 보고서 열기'],['설비 상세에서는 자산 상태, 번들, 현재 기술 사양과 관리 기준을 함께 확인합니다.','검사이력과 Tube 결과를 살펴보고 필요한 상세 기능으로 이동합니다.','인쇄 보고서는 해당 설비의 정보를 정리해 보여줍니다. 사양과 원본 검사값을 대조해 활용합니다.']),
('설비 연결 기능','튜브 관리와 상세 이력','exchangers',['설비 상세에서 튜브 관리','번호·위치·운전상태 확인','개별 Tube 이력 조회'],['튜브 관리는 설비에 속한 개별 Tube의 번호와 위치, 운전상태를 다루는 기능입니다.','Tube를 선택하면 상세 검사값과 다년 이력을 확인할 수 있습니다.','상태 변경은 편집 권한과 근거가 필요합니다. 설치 이전 자료는 과거 조회 이력으로 구분합니다.']),
('설비 연결 기능','2D 및 3D Tube Map','analysis',['설비 상세에서 Map 열기','검사 범위와 Tube 선택','위치·결과·상태 비교'],['2D·3D Tube Map은 Tube의 공간 위치와 상태를 시각적으로 비교하는 화면입니다.','설비와 검사 범위를 확인하고 Tube를 선택해 관련 결과를 살펴봅니다.','미연결 Layout 위치를 실제 등록 Tube와 혼동하지 않습니다. 3D 표시는 WebGL 환경의 영향을 받습니다.']),
('검사 관리','전체 검사 이력','inspections',['설비·검사 조건으로 조회','검사일과 보고서 확인','검사 상세와 PDF 열기'],['전체 검사 이력은 설비별 검사 보고서와 검사 시점을 찾는 메뉴입니다.','검색 조건으로 대상을 좁힌 뒤 검사일, 보고서와 검사 범위를 확인합니다.','검사 상세와 원본 PDF를 함께 보면서 측정값과 출처를 대조합니다.']),
('검사 관리','튜브 검사이력','inspections',['공정·설비·Tube 조건 선택','측정값과 검사 시점 비교','상세 이력으로 이동'],['튜브 검사이력은 개별 Tube의 검사 결과를 목록으로 조회하는 메뉴입니다.','공정과 설비, Tube 조건으로 대상을 찾고 검사 시점별 두께와 감육 정보를 비교합니다.','설치 이전 이력은 보존된 조회 자료이며 현재 설치분의 수명 계산과는 구분합니다.']),
('검사 관리','검사계획 관리','inspections',['검사 대상·예정일 설정','계획 상태와 승인 확인','진행·완료 조건 확인'],['검사계획 관리는 검사 대상과 예정일, 계획의 진행 상태를 관리하는 메뉴입니다.','설비와 Tube 범위를 정한 뒤 권한에 맞게 계획의 승인과 진행 상태를 관리합니다.','완료에는 업무 조건 충족이 필요합니다. 승인과 상태 변경은 이 안내 영상에서 실행하지 않습니다.']),
('정밀 분석','설비 선택과 분석 진입','analysis',['상단 정밀 분석 선택','VCM1·VCM2와 설비 선택','Map·표·분석 결과 확인'],['상단의 정밀 분석을 선택한 뒤 공정과 설비를 지정합니다.','같은 화면에서 Tube Sheet Map과 부식측정결과 표, 선택 Tube의 분석을 확인합니다.','설비와 검사 범위를 먼저 확인하면 다른 대상을 비교하는 혼동을 줄일 수 있습니다.']),
('정밀 분석','Map과 부식측정결과 표 연동','analysis',['Map의 Tube 선택','표의 해당 행 확인','표에서 다시 Tube 선택'],['Map에서 Tube를 선택하면 부식측정결과 표의 해당 행이 선택되고 강조됩니다.','반대로 표의 행을 선택하면 Map의 연결 위치와 Tube 분석을 확인할 수 있습니다.','위치가 연결되지 않은 Tube는 연결 여부를 확인합니다. 없는 좌표를 추정값으로 해석하지 않습니다.']),
('정밀 분석','격자 표시와 패널 크기 조절','analysis',['격자·축 표시 전환','좌우 너비와 세로 높이 조절','3D 보기로 이동'],['Tube Sheet Map 제목 옆 스위치로 격자와 행·열 번호 표시를 바꿀 수 있습니다.','패널 경계와 Map 아래 조절 영역을 사용해 화면 공간을 조정합니다.','3D 보기는 선택한 설비와 Tube를 기존 3D 화면으로 연결합니다. 별도 화면에서 확인합니다.']),
('정밀 분석','부식속도와 잔여수명 해석','analysis',['선택 Tube 이력 확인','계산 기준과 부식속도 확인','예상일과 한도 초과 구분'],['선택 Tube의 측정이력과 계산에 사용한 부식속도, 기준일을 함께 확인합니다.','허용 Plugging 개수와 기준일까지의 누적 대상, 최초 한도 초과 예상일을 구분합니다.','한도 미도달은 무한 수명이나 운전 승인이라는 의미가 아닙니다. 공학 검토와 별개입니다.']),
('분석 연결 기능','감육률 순위와 Plugging 대상','analysis',['설비별 최대 감육률 조회','예측 대상 Tube 확인','관련 검사와 상세 연결'],['분석 관련 경로에서는 설비별 최대 감육률과 Tube Plugging 예측 대상을 조회할 수 있습니다.','조회 조건과 계산 기준을 확인해 우선 검토 대상을 찾습니다.','목록의 순위와 예상은 검토 지원 정보입니다. 실제 조치 여부는 원본과 관리 기준을 확인합니다.']),
('분석 연결 기능','Plugging 예측과 API 510','analysis',['설비 상세의 계산 기능 선택','입력값·단위·근거 확인','시뮬레이션 결과 비교'],['설비 상세에서 Tube Plugging 예측과 API 510 계산 기능으로 이동할 수 있습니다.','시뮬레이션은 부식속도 조건을 바꿔 결과를 비교하고, API 510은 입력 근거와 단위를 확인합니다.','계산 저장이나 상태 전환 전에 기준을 검토합니다. 결과 자체가 공학적 승인을 대신하지 않습니다.']),
('분석 연결 기능','ML 검토대상','analysis',['공정과 설비 조건으로 조회','후보와 품질 Gate 확인','전문가 판단 근거 기록'],['ML 검토대상은 이상치와 품질 점검 후보를 전문가에게 제시하는 기능입니다.','후보의 검사값과 품질 Gate, 원본 근거를 확인하고 판단합니다.','전문가 라벨과 판단 근거를 관리하며, 모델 결과가 원천 데이터를 자동 수정하거나 승인하지 않습니다.']),
('분석 연결 기능','공간 Hotspot과 유사 패턴','analysis',['공간 분포와 후보 확인','승인 Layout·원본 대조','유사 열화 패턴 검토'],['공간 Hotspot은 측정 결과의 공간 분포를, 유사 열화 패턴은 후보 간 특징을 살펴보는 기능입니다.','승인된 Layout과 Tube 연결 상태, 원본 측정 근거를 함께 확인합니다.','유사성이나 밀집도만으로 결함 원인을 확정하지 않고 전문가 검토에 활용합니다.']),
('분석 연결 기능','AI 조회와 보고서 검토','analysis',['조회 질문과 조건 확인','결과 설비·근거 확인','보고서 내용 검토'],['AI 조회와 보고서 검토 기능은 자료 검색과 근거 정리를 지원합니다.','조회 결과의 설비와 검사 근거를 확인하고 보고서 내용과 출처를 대조합니다.','외부 또는 로컬 LLM 사용 가능 여부는 설정과 실행환경에 따라 달라집니다. 자동 확정 판정이 아닙니다.']),
('정비 관리','작업지시와 정비 기록','maintenance',['정비 목록과 작업지시 조회','대상·작업 내용 확인','실제 조치와 결과 기록'],['정비 관리에서는 작업지시와 정비 기록을 확인하고 업무의 진행 상태를 관리합니다.','대상 설비와 Tube, 작업 내용, 담당 근거를 확인한 뒤 실제 조치를 기록합니다.','계산상 예정 대상과 완료된 작업 기록은 서로 구분합니다. 영상에서는 업무 데이터를 변경하지 않습니다.']),
('기본 설정','내 기본 설정','settings',['기본 설정 메뉴 펼치기','내 기본 설정 열기','개인 조회 조건 확인'],['기본 설정의 내 기본 설정은 사용자 개인의 기본 조회 조건을 관리하는 메뉴입니다.','자주 사용하는 조회 조건을 확인해 반복 조회를 편하게 사용할 수 있습니다.','개인 설정과 공통 시스템 설정의 적용 범위를 구분하고 필요한 항목을 저장합니다.']),
('기본 설정','조직 코드 관리','settings',['공장·팀·공정 구조 확인','상하위 연결 검토','설비 등록에 사용할 코드 관리'],['조직 코드 관리는 공장과 팀, 공정 등 조직 기준정보를 다루는 메뉴입니다.','상하위 코드와 연결 관계를 확인한 뒤 설비 등록과 조회에 활용합니다.','미연결 항목은 사용 목적을 확인하고 선택합니다. 조직 변경이 기존 자료에 미치는 영향도 검토합니다.']),
('기본 설정','Wall Loss 색상','settings',['정상·주의·위험 색상 확인','미검사·Plugged 색상 구분','Map과 범례 적용 확인'],['Wall Loss 색상은 정상과 주의, 위험 및 미검사와 Plugged 표시 색상을 관리합니다.','Map과 범례가 같은 기준을 사용하도록 공통 색상을 확인합니다.','색상은 상태를 읽기 쉽게 하는 표시 설정입니다. 감육 기준값과 실제 Tube 상태를 함께 확인합니다.']),
('기본 설정','화면 테마 설정','settings',['테마 메뉴 선택','표시 스타일 확인','적용 화면 새로 확인'],['화면 테마 설정은 시스템 화면의 표시 스타일을 관리하는 메뉴입니다.','적용 가능한 테마와 표시 결과를 확인한 뒤 변경합니다.','테마 변경은 화면 표현에 관한 설정입니다. 업무 데이터와 계산 결과를 수정하는 기능은 아닙니다.']),
('기본 설정','사용자·권한 관리','settings',['관리자 계정으로 접근','조회·편집 권한 확인','업무에 필요한 권한만 부여'],['사용자·권한 관리는 관리자 전용으로 계정 상태와 화면별 권한을 관리합니다.','조회 권한과 편집 권한을 구분하고 담당 업무에 필요한 범위를 확인합니다.','권한 변경은 실제 접근 범위에 영향을 줍니다. 이 영상에서는 계정이나 권한을 변경하지 않습니다.']),
('기본 설정','DB 상태 점검','settings',['관리자 DB 점검 메뉴','연결·대상 DB 상태 확인','장애 정보와 운영 상태 검토'],['DB 상태 점검은 관리자가 MariaDB 연결과 운영 대상 정보를 확인하는 메뉴입니다.','접속 대상과 상태를 확인해 연결 장애와 업무 화면 문제를 구분합니다.','IRIS2는 MariaDB를 사용하며 DB 장애 때 SQLite로 자동 전환하지 않습니다.']),
('기본 설정','백업 관리','settings',['보관 백업과 상태 확인','백업·복원 대상 검토','승인된 절차로 복원'],['백업 관리는 백업 자료와 운영 상태를 확인하는 관리자 메뉴입니다.','복원은 기존 데이터에 영향을 주므로 대상과 시점, 사전 백업 및 검증 절차를 확인합니다.','이 안내에서는 백업 복원이나 데이터 덮어쓰기를 실행하지 않습니다.']),
('기본 설정','품질 이슈','settings',['심각도·처리 상태로 조회','원본 근거와 문제 확인','확인 근거에 따라 처리'],['품질 이슈 메뉴에서 데이터의 경고와 불일치, 검토 필요 항목을 조회합니다.','심각도와 처리 상태로 범위를 좁히고 해당 설비와 원본 근거를 확인합니다.','해결 처리는 확인 근거를 남긴 뒤 수행합니다. 경고를 없애기 위해 측정값을 임의 보정하지 않습니다.']),
('기본 설정','Tube Layout Revision','settings',['설비와 Layout 개정 조회','적용 기간·좌표·연결 확인','승인된 위치 기준 활용'],['Tube Layout Revision은 설비별 Tube 배치 개정과 적용 기준을 확인하는 메뉴입니다.','개정의 적용 기간과 좌표, Tube ID 연결 상태를 확인합니다.','승인된 Layout을 공간 분석에 활용하고, 배치 위치 개수와 등록된 물리 Tube 수를 구분합니다.']),
('마무리','업무 흐름과 활용 순서','dashboard',['현황 확인 → 대상 설비 조회','검사·Tube·분석 근거 확인','계획·정비 → 결과 기록'],['대시보드에서 현황을 확인하고 열교환기 목록에서 검토할 설비를 선택합니다.','검사이력과 Tube Map, 정밀 분석으로 근거를 살펴본 뒤 계획과 정비 업무로 연결합니다.','이상으로 메뉴 안내를 마칩니다. 메뉴 목록과 상세 설명 대본은 영상과 함께 제공됩니다.']),
]

def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)

def wrap(draw, text, f, width):
    lines=[]; line=''
    for char in text:
        if draw.textlength(line+char,font=f)>width and line:
            lines.append(line);line=char
        else:line+=char
    if line:lines.append(line)
    return lines

def text(draw,xy,value,size,color='#182537',bold=False,width=None,spacing=10):
    f=font(size,bold);lines=wrap(draw,value,f,width) if width else [value]
    for i,line in enumerate(lines):draw.text((xy[0],xy[1]+i*(size+spacing)),line,font=f,fill=color)

def timestamp(seconds,sep=','):
    h=int(seconds)//3600;m=int(seconds)%3600//60;s=int(seconds)%60
    return f'{h:02}:{m:02}:{s:02}{sep}000'

groups=['대시보드','열교환기 관리','설비 연결 기능','검사 관리','정밀 분석','분석 연결 기능','정비 관리','기본 설정']
captions=[];script=['# IRIS2 화면 메뉴별 설명 대본','','형식: 실제 화면 캡처 기반 한국어 자막 영상. 음성 없음.','계정 권한별로 메뉴 표시가 다르며, 연결 기능은 독립된 왼쪽 메뉴와 구분합니다.','캡처: 2026-10-26 / 업무 데이터 변경 없음.','']
menu=['# IRIS2 화면 메뉴 및 동작 안내','','왼쪽 메뉴와 상단 메뉴를 기준으로 구성했으며 설비·분석 연결 기능은 별도로 구분했습니다.','한국어 자막 영상이며 실제 저장·승인·복원 클릭 녹화가 아닙니다.','','| 구분 | 메뉴·기능 | 동작 순서 |','|---|---|---|']
concat=[];index=0;seconds=0;manifest=[]
for no,(group,title,screenshot,actions,segments) in enumerate(SCENES,1):
    duration=12
    script += [f'## {no:02} {title}',f'시간: {timestamp(seconds,".")} ~ {timestamp(seconds+duration,".")}',f'구분: {group}','조작: '+' → '.join(actions),'',*segments,'']
    menu.append(f'| {group} | {title} | '+ ' → '.join(actions)+' |')
    shot=Image.open(OUT/f'{screenshot}.png').convert('RGB')
    # Keep screenshot visible without stretching its aspect ratio.
    shot=ImageOps.contain(shot,(1400,610),Image.Resampling.LANCZOS)
    for part,segment in enumerate(segments):
        index+=1
        img=Image.new('RGB',(1920,1080),'#f3f5f8');d=ImageDraw.Draw(img)
        d.rectangle((0,0,1920,130),fill='#15283f');d.rectangle((0,130,1920,138),fill='#ef8b2c')
        text(d,(46,22),'IRIS2  화면 메뉴 안내',26,'#e6edf6',True)
        text(d,(46,65),title,40,'#ffffff',True)
        text(d,(1510,30),f'{no:02} / {len(SCENES):02}',28,'#ffffff',True)
        text(d,(1510,76),'한국어 자막 · 음성 없음',22,'#d5dfeb')
        d.rounded_rectangle((28,160,435,820),radius=18,fill='#ffffff')
        text(d,(52,185),'MENU',20,'#8794a5',True)
        y=237
        for g in groups:
            selected=(g==group)
            if selected:d.rounded_rectangle((43,y-7,418,y+48),radius=9,fill='#fff0df')
            text(d,(59,y),g,28,'#a85912' if selected else '#526275',selected)
            y+=67
        d.rounded_rectangle((462,160,1890,820),radius=18,fill='#ffffff')
        img.paste(shot,(476+(1390-shot.width)//2,180+(610-shot.height)//2))
        text(d,(483,790),'실제 조회 화면 캡처 · '+screenshot.upper(),17,'#66758a')
        # Show exactly which instruction is being explained in the current segment.
        for step,action in enumerate(actions):
            x=28+step*625
            d.rounded_rectangle((x,840,x+606,905),radius=10,fill='#ed8a2e' if step==part else '#e1e7ee')
            text(d,(x+17,857),f'{step+1}  {action}',25,'#ffffff' if step==part else '#405267',step==part)
        d.rectangle((0,928,1920,1050),fill='#142338')
        caption_lines=wrap(d,segment,font(32),1810)
        assert len(caption_lines)<=2,(title,segment)
        text(d,(52,948 if len(caption_lines)>1 else 968),segment,32,'#ffffff',width=1810,spacing=9)
        d.rectangle((0,1065,int(1920*(seconds+part*4+4)/(len(SCENES)*12)),1080),fill='#ed8a2e')
        text(d,(30,1022),'VCM1 · VCM2  |  메뉴별 사용 순서 안내',16,'#b7c6d8')
        file=FRAMES/f'{index:03}.png';img.save(file)
        concat += [f"file '{file.as_posix()}'",'duration 4']
        captions += [str(index),f'{timestamp(seconds+part*4)} --> {timestamp(seconds+part*4+4)}',segment,'']
    manifest.append({'chapter':no,'group':group,'title':title,'start_seconds':seconds,'duration_seconds':duration,'actions':actions,'script':segments,'screenshot':screenshot+'.png'})
    seconds+=duration
concat.append(f"file '{file.as_posix()}'")
(OUT/'video_frames.txt').write_text('\n'.join(concat),encoding='utf-8')
(OUT/'IRIS2_menu_guide.srt').write_text('\n'.join(captions),encoding='utf-8-sig')
(OUT/'IRIS2_메뉴별_설명대본.md').write_text('\n'.join(script),encoding='utf-8-sig')
(OUT/'IRIS2_화면메뉴_동작안내.md').write_text('\n'.join(menu)+'\n',encoding='utf-8-sig')
(OUT/'chapters.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
metadata=[';FFMETADATA1','title=IRIS2 화면 메뉴 안내','comment=Korean captions; no audio; local read-only screen snapshots']
for chapter in manifest:
    metadata += ['[CHAPTER]','TIMEBASE=1/1000',f"START={chapter['start_seconds']*1000}",f"END={(chapter['start_seconds']+12)*1000}",f"title={chapter['title']}"]
(OUT/'chapters.ffmeta').write_text('\n'.join(metadata),encoding='utf-8')
output=OUT/'IRIS2_화면메뉴_안내.mp4'
cmd=[imageio_ffmpeg.get_ffmpeg_exe(),'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(OUT/'video_frames.txt'),'-i',str(OUT/'chapters.ffmeta'),'-map_metadata','1','-map_chapters','1','-vf','fps=12,format=yuv420p','-t',str(seconds),'-c:v','libx264','-preset','veryfast','-crf','21','-movflags','+faststart',str(output)]
print(json.dumps({'chapters':len(SCENES),'seconds':seconds,'frames':index,'output':str(output)},ensure_ascii=True),flush=True)
subprocess.run(cmd,check=True)
print(json.dumps({'completed':True,'bytes':output.stat().st_size}),flush=True)
