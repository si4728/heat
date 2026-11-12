"""Edit captured real UI operations into precision-focused and full guides."""
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / 'outputs/precision_guide_v3'
OLD = ROOT / 'outputs/menu_demo_v2'
EDIT = NEW / 'edited'
EDIT.mkdir(parents=True, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
REG = 'C:/Windows/Fonts/malgun.ttf'
BOLD = 'C:/Windows/Fonts/malgunbd.ttf'
new = json.loads((NEW / 'steps.json').read_text(encoding='utf-8'))
old = json.loads((OLD / 'steps.json').read_text(encoding='utf-8'))

def new_step(s):
    return dict(s, path=NEW / s['file'], chapter='정밀 분석과 3D 활용')

def old_step(index, chapter):
    s = old[index - 1]
    return dict(title=s['section'], caption=s['caption'], path=OLD / s['file'],
                seconds=2 if s['caption'].startswith('클릭:') else 10,
                mark=s.get('pointer'), chapter=chapter)

def card(title, caption, seconds, chapter):
    return dict(title=title, caption=caption, seconds=seconds, path=None, chapter=chapter)

entry = [new_step(s) for s in new[-2:]]
precision = entry + [new_step(s) for s in new[:-2]]
# Insert continuously captured, real 3D drag frames after the 2D comparison section.
motion = json.loads((NEW / 'motion.json').read_text(encoding='utf-8'))
motion_steps = []
for i, frame in enumerate(motion):
    dt = (motion[i+1]['time_ms'] - frame['time_ms']) / 1000 if i+1 < len(motion) else .1
    motion_steps.append(dict(title='3D 배경을 실제로 드래그',
        caption='3D 배경을 드래그하며 배열을 회전하는 연속 캡처 장면입니다.',
        seconds=max(.04, dt), path=NEW / frame['file'], chapter='정밀 분석과 3D 활용', motion=True))
insertion = next(i+1 for i,s in enumerate(precision) if s['title']=='번호 표시와 감육률')
precision[insertion:insertion] = motion_steps
intro = card('IRIS2 정밀 분석 중심 사용 안내',
    '실제 업무 화면을 열고 기능을 조작한 전후 장면을 편집했습니다. 정밀 분석과 3D 기능을 중심으로 설명합니다.', 12, '영상 안내')
scope = card('시연 범위와 보는 방법',
    'VCM1·VCM2의 격리 시연 DB를 사용합니다. 화면의 표시값은 시연 자료이며, 데이터 점검 메뉴는 소개하지 않습니다.', 12, '영상 안내')
ending = card('정밀 분석 활용 순서',
    '공정·설비 선택 → Map과 표 비교 → 전체 이력 확인 → 속도 가정 비교 → 잔여수명 해석 → 3D 확인 순서로 활용합니다.', 14, '마무리')
focus = [intro, scope] + [old_step(i,'설비 조회와 분석 진입') for i in [1,2,3,4]] + precision + [ending]

# Only include menus with successful, captured real interactions. Omit inspection
# administration / data-quality tools and failed print/reset dialogs.
master_ids = [5,6,7,8,9,10,11,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32]
prediction_ids = list(range(57,73)) + list(range(136,146))
inspection_ids = list(range(91,123))
maintenance_ids = list(range(123,136))
settings_ids = [146,147,148,149,150,151,152,153,154,155,156]
full = focus[:-1] + [card('설비와 검사 업무로 연결',
    '이어서 실제 조작한 설비 입력·수정, 예측·계산, 검사계획과 정비 업무를 확인합니다. 변경은 격리 DB에만 적용됩니다.',12,'업무 연결')]
for ids, chapter in [(master_ids,'설비 입력과 Tube 관리'),(prediction_ids,'예측과 API 510'),
                      (inspection_ids,'검사이력과 검사계획'),(maintenance_ids,'정비 업무'),
                      (settings_ids,'내보내기와 표시 설정')]:
    full += [old_step(i,chapter) for i in ids]
full += [ending]

def wrap(draw, text, font, width):
    lines=[]; line=''
    for ch in text:
        if draw.textlength(line+ch,font=font)>width and line:
            lines.append(line); line=ch
        else: line+=ch
    if line: lines.append(line)
    return lines

cache={}
def render(step):
    source_digest=hashlib.sha256(step['path'].read_bytes()).hexdigest() if step['path'] else ''
    key=hashlib.sha256((source_digest+json.dumps({k:str(v) for k,v in step.items() if k!='seconds'},ensure_ascii=False,sort_keys=True)).encode()).hexdigest()[:18]
    dest=EDIT / (key+'.png')
    if dest.exists():return dest
    image=Image.new('RGB',(1920,1080),'#10263c');draw=ImageDraw.Draw(image)
    titlefont=ImageFont.truetype(BOLD,30); bodyfont=ImageFont.truetype(REG,30)
    draw.text((28,16),step['title'],font=titlefont,fill='white')
    draw.text((1430,24),'IRIS2 · 격리 시연 DB',font=ImageFont.truetype(REG,20),fill='#c5d5e5')
    draw.rectangle((0,65,1920,70),fill='#ed8a2f')
    if step['path']:
        source=Image.open(step['path']).convert('RGB')
        original=source.size
        source=ImageOps.contain(source,(1920,846),Image.Resampling.LANCZOS)
        x=(1920-source.width)//2; y=76+(846-source.height)//2
        image.paste(source,(x,y))
        mark=step.get('mark')
        if mark and 0<=mark['x']<original[0] and 0<=mark['y']<original[1]:
            px=x+mark['x']*source.width/original[0];py=y+mark['y']*source.height/original[1]
            draw.ellipse((px-24,py-24,px+24,py+24),outline='#ff7e00',width=5)
            draw.line((px-31,py,px+31,py),fill='#ff7e00',width=2)
            draw.line((px,py-31,px,py+31),fill='#ff7e00',width=2)
    else:
        big=ImageFont.truetype(BOLD,62)
        for i,line in enumerate(wrap(draw,step['title'],big,1680)):
            draw.text((110,300+i*85),line,font=big,fill='white')
        draw.text((114,590),'메뉴를 열고 직접 조작하며 결과를 확인합니다',font=ImageFont.truetype(REG,32),fill='#d4e1ee')
    draw.rectangle((0,934,1920,1080),fill='#10263c')
    lines=wrap(draw,step['caption'].replace('表','표'),bodyfont,1820)
    assert len(lines)<=3,step['caption']
    offset=951 if len(lines)>1 else 973
    for i,line in enumerate(lines):draw.text((45,offset+i*38),line,font=bodyfont,fill='white')
    draw.text((45,1054),'실제 조작 전후 화면 편집 · 한국어 자막 · 음성 없음',font=ImageFont.truetype(REG,15),fill='#b9cadd')
    image.save(dest)
    return dest

def ts(seconds):
    n=round(seconds*1000);return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'

def build(steps,stem):
    concat=[]; elapsed=0; captions=[]; chapters=[]; script=[]
    for i,step in enumerate(steps):
        frame=render(step)
        concat += [f"file '{frame.as_posix()}'",f"duration {step['seconds']:.3f}"]
        if not chapters or chapters[-1]['title']!=step['chapter']:
            chapters.append({'title':step['chapter'],'start':elapsed,'end':elapsed})
        if not step.get('motion') or not steps[i-1].get('motion'):
            script += [f"## {ts(elapsed)} {step['title']}",'',step['caption'],'']
        captions += [str(i+1),f"{ts(elapsed)} --> {ts(elapsed+step['seconds'])}",step['caption'],'']
        elapsed+=step['seconds'];chapters[-1]['end']=elapsed
    concat.append(f"file '{frame.as_posix()}'")
    (NEW/f'{stem}.concat.txt').write_text('\n'.join(concat),encoding='utf-8')
    (NEW/f'{stem}.srt').write_text('\n'.join(captions),encoding='utf-8-sig')
    (NEW/f'{stem}_설명대본.md').write_text('# IRIS2 실제 조작 설명 대본\n\n'+'\n'.join(script),encoding='utf-8-sig')
    meta=[';FFMETADATA1',f'title={stem}','comment=Actual UI interaction before-and-after captures with a continuous 3D drag segment. Korean captions. No audio.']
    for ch in chapters:meta+=['[CHAPTER]','TIMEBASE=1/1000',f"START={round(ch['start']*1000)}",f"END={round(ch['end']*1000)}",f"title={ch['title']}"]
    (NEW/f'{stem}.ffmeta').write_text('\n'.join(meta),encoding='utf-8')
    output=NEW/f'{stem}.mp4'
    print(json.dumps({'building':stem,'seconds':round(elapsed,2),'segments':len(steps)},ensure_ascii=True),flush=True)
    subprocess.run([FF,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(NEW/f'{stem}.concat.txt'),'-i',str(NEW/f'{stem}.ffmeta'),'-map_metadata','1','-map_chapters','1','-vf','fps=15,format=yuv420p','-t',str(elapsed),'-c:v','libx264','-preset','veryfast','-crf','20','-movflags','+faststart',str(output)],check=True)
    result=subprocess.run([FF,'-v','error','-i',str(output),'-f','null','-'],capture_output=True)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    return {'file':output.name,'seconds':round(elapsed,3),'bytes':output.stat().st_size,'segments':len(steps),'chapters':chapters,'decode':'passed','audio':False,'size':'1920x1080'}

results=[build(focus,'IRIS2_정밀분석_집중안내_개정판'),build(full,'IRIS2_업무메뉴_정밀분석중심_개정판')]
motion_unique=len({hashlib.sha256((NEW/x['file']).read_bytes()).hexdigest() for x in motion})
(NEW/'verification.json').write_text(json.dumps({'videos':results,'continuous_motion_unique_frames':motion_unique,'excluded':['DB 상태 점검','품질 이슈','PDF OCR 검토','ML 데이터 품질 점검'],'demo_schema':'iris2_test_transition and three auxiliary _test_transition stores'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'completed':results,'motion_unique':motion_unique},ensure_ascii=True),flush=True)
