import hashlib, json, subprocess
from pathlib import Path
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps
ROOT=Path(__file__).resolve().parents[1]
NEW=ROOT/'outputs/e106_precision_v4'
EDIT=NEW/'edited'
EDIT.mkdir(exist_ok=True)
FF=imageio_ffmpeg.get_ffmpeg_exe()
REG='C:/Windows/Fonts/malgun.ttf'
BOLD='C:/Windows/Fonts/malgunbd.ttf'

def wrap(draw, text, font, width):
    lines=[]; line=''
    for ch in text:
        if draw.textlength(line+ch,font=font)>width and line:
            lines.append(line); line=ch
        else: line+=ch
    if line: lines.append(line)
    return lines

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
        crop_left=236 if step.get('url') and '/analysis' not in step['url'] else 0
        source=source.crop((crop_left,0,source.width,source.height))
        original=source.size
        source=ImageOps.contain(source,(1920,846),Image.Resampling.LANCZOS)
        x=(1920-source.width)//2; y=76+(846-source.height)//2
        image.paste(source,(x,y))
        mark=dict(step['mark']) if step.get('mark') else None
        if mark: mark['x']-=crop_left
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

if __name__ == '__main__':
    captured=json.loads((NEW/'steps.json').read_text(encoding='utf-8'))
    assert len(captured)==73
    for s in captured:
        assert 'E-121' not in json.dumps(s)
        assert any(p in s['url'] for p in ['/analysis','/tubes/1964','/exchangers/151/'])
    steps=[dict(title='E-106 정밀 분석 사용 안내',caption='VCM2에서 E-106을 조회하고 Tube 측정결과, 부식속도, 잔여수명과 3D 기능을 실제 화면으로 설명합니다.',seconds=10,path=None,chapter='영상 안내')]
    motion=json.loads((NEW/'motion.json').read_text(encoding='utf-8'))
    for i,s in enumerate(captured):
        if i==65:
            for j,m in enumerate(motion):
                dt=(motion[j+1]['time_ms']-m['time_ms'])/1000 if j+1<len(motion) else .1
                steps.append(dict(title='E-106 3D 실제 드래그 회전',caption='3D 배경을 실제로 드래그하여 E-106 배열을 회전합니다.',seconds=max(.04,dt),path=NEW/m['file'],url='/exchangers/151/tube-map',chapter=s['chapter'],motion=True))
        steps.append(dict(s,path=NEW/s['file']))
    result=build(steps,'IRIS2_E-106_정밀분석_안내')
    unique=len({hashlib.sha256((NEW/m['file']).read_bytes()).hexdigest() for m in motion})
    assert unique>1
    (NEW/'verification.json').write_text(json.dumps(dict(video=result,continuous_motion_unique_frames=unique,scope='E-106 / VCM2',source_screens=73),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
