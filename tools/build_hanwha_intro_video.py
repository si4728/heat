"""Replace the integrated video's opening with the actual dashboard and credits."""
import json
import subprocess
from pathlib import Path
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
OLD=ROOT/'outputs/integrated_e106_v5'
OUT=ROOT/'outputs/hanwha_intro_v6'
TITLE='한화 열교환기 지능형 관리 시스템 소개'
STEM=TITLE.replace(' ','_')
FF=imageio_ffmpeg.get_ffmpeg_exe()
font=lambda size,bold=False:ImageFont.truetype('C:/Windows/Fonts/malgun'+('bd' if bold else '')+'.ttf',size)

im=Image.new('RGB',(1920,1080),'#10263c')
d=ImageDraw.Draw(im)
d.text((65,38),TITLE,font=font(64,True),fill='white')
d.text((70,137),'제공회사  |  (주)온브랜딩',font=font(35,True),fill='#ffad55')
d.line((65,206,1855,206),fill='#ee8b30',width=4)
source=Image.open(OUT/'main_page.png').convert('RGB')
# Keep the real main-page annual inspection panel, excluding data-review panels.
source=source.crop((237,42,1520,620))
source=ImageOps.contain(source,(1770,650),Image.Resampling.LANCZOS)
im.paste(source,((1920-source.width)//2,240))
d.text((76,925),'메인 페이지 · 생산라인별·연도별 검사 현황',font=font(29),fill='#cadcec')
caption='설비 조회부터 정밀분석, 검사·정비까지 주요 업무 기능을 소개합니다.'
d.text((76,984),caption,font=font(31),fill='white')
d.text((76,1042),'제공회사: (주)온브랜딩 · 한국어 자막 · 음성 없음',font=font(20),fill='#cadcec')
intro=OUT/'intro.png'
im.save(intro)

concat=next(OLD.glob('*.concat.txt')).read_text(encoding='utf-8').splitlines()
assert concat[0].startswith('file ') and concat[1]=='duration 12.000'
concat[0]=f"file '{intro.as_posix()}'"
(OUT/'timeline.concat.txt').write_text('\n'.join(concat),encoding='utf-8')
metadata=next(OLD.glob('*.ffmeta')).read_text(encoding='utf-8').splitlines()
metadata[1]='title='+TITLE
metadata.insert(2,'artist=(주)온브랜딩')
(OUT/'chapters.ffmeta').write_text('\n'.join(metadata),encoding='utf-8')
v=json.loads((OLD/'verification.json').read_text(encoding='utf-8'))
duration=v['video']['seconds']
output=OUT/(STEM+'.mp4')
print('Encoding updated opening and integrated video',flush=True)
subprocess.run([FF,'-y','-hide_banner','-loglevel','error','-f','concat','-safe','0','-i',str(OUT/'timeline.concat.txt'),
    '-i',str(OUT/'chapters.ffmeta'),'-map_metadata','1','-map_chapters','1','-vf','fps=15,format=yuv420p',
    '-t',str(duration),'-c:v','libx264','-preset','veryfast','-crf','20','-movflags','+faststart',str(output)],check=True)
subprocess.run([FF,'-v','error','-i',str(output),'-f','null','-'],check=True)
scenario=(OLD/'통합_시나리오.md').read_text(encoding='utf-8-sig')
scenario=scenario.replace('# IRIS2 업무 안내 · E-106 정밀분석 통합 시나리오','# '+TITLE+' · 시나리오',1)
scenario=scenario.replace('IRIS2 업무 안내 · E-106 정밀분석 통합판',TITLE)
scenario=scenario.replace('설비 조회에서 E-106 정밀분석으로 이어진 뒤 설비 관리, 예측·계산, 검사·정비와 내보내기 기능을 설명합니다.',
    '실제 메인 페이지의 생산라인별·연도별 검사 현황을 배경으로 시스템을 소개합니다. '+caption+' 제공회사는 (주)온브랜딩입니다.')
scenario=scenario.replace('\n\n','\n\n제공회사: **(주)온브랜딩**\n\n',1)
(OUT/'소개영상_시나리오.md').write_text(scenario,encoding='utf-8-sig')
srt=next(OLD.glob('*.srt')).read_text(encoding='utf-8-sig')
blocks=srt.split('\n\n')
first=blocks[0].splitlines()
blocks[0]='\n'.join(first[:2]+[TITLE+' · 제공회사: (주)온브랜딩. '+caption])
(OUT/(STEM+'.srt')).write_text('\n\n'.join(blocks),encoding='utf-8-sig')
v['video'].update(file=output.name,bytes=output.stat().st_size,title=TITLE,provider='(주)온브랜딩',decode='passed')
v['opening']='Actual main dashboard annual-inspection panel; no data-review panels'
(OUT/'verification.json').write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
subprocess.run([FF,'-y','-v','error','-ss','3','-i',str(output),'-frames:v','1',str(OUT/'qa_opening.png')],check=True)
print(json.dumps(v['video'],ensure_ascii=True),flush=True)
