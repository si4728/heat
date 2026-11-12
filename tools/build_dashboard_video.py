"""Add a captioned dashboard overview after the supplied opening image."""
import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/main_image_v7'
OUT = ROOT / 'outputs/dashboard_v8'
SLIDES = [
    ('대시보드 · 업무 시작 화면', (0, 0, 1, 1),
     '운영 현황에서 설비·검사 현황을 먼저 확인합니다.\n왼쪽 메뉴는 열교환기 관리, 검사 관리, 정비 관리의 업무 진입점입니다.'),
    ('주요 현황 · 설비와 검사 이력', (.14, .46, 1, .59),
     '열교환기 900대는 등록 설비 수, 검사 이력 435건은 누적 검사 객체 수입니다.\n같은 열교환기도 검사일·보고서·검사범위가 다르면 별도 이력으로 계산합니다.'),
    ('숫자 읽기 · 사양 수량과 검사결과', (.48, .46, 1, .59),
     '전체 튜브 69,105개는 현재 사양 수량의 합계이며, 개별 등록 Tube는 2,253개입니다.\n튜브 결과 6,084건은 검사별·튜브별 측정결과 수로, 물리적인 튜브 수와 다릅니다.'),
    ('검사 계획과 현장 조회', (.31, .59, .66, .73),
     '검사 계획은 종료되지 않은 진행 계획 수이며, 지연은 예정일을 지난 미완료 계획입니다.\nQR-code 읽기는 현장에서 열교환기를 찾는 진입점입니다. 이후 설비 조회로 이어집니다.'),
]


def stamp(seconds):
    n = round(seconds * 1000)
    return f'{n // 3600000:02}:{n // 60000 % 60:02}:{n // 1000 % 60:02},{n % 1000:03}'


def seconds(value):
    h, m, s, ms = map(int, re.split('[:,]', value))
    return h * 3600 + m * 60 + s + ms / 1000


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    font = lambda size, bold=False: ImageFont.truetype(
        'C:/Windows/Fonts/malgun' + ('bd' if bold else '') + '.ttf', size)
    with Image.open(ROOT / 'docs/main_image.png') as original:
        source = original.convert('RGB')
    inserted = []
    for i, (title, region, caption) in enumerate(SLIDES):
        frame = Image.new('RGB', (1920, 1080), '#10263c')
        draw = ImageDraw.Draw(frame)
        draw.text((50, 24), title, font=font(44, True), fill='white')
        crop = source.crop(tuple(round(v * (source.width if j % 2 == 0 else source.height))
                                 for j, v in enumerate(region)))
        crop = ImageOps.contain(crop, (1820, 760), Image.Resampling.LANCZOS)
        frame.paste(crop, ((1920 - crop.width) // 2, 105 + (760 - crop.height) // 2))
        for j, line in enumerate(caption.splitlines()):
            assert draw.textlength(line, font=font(32)) <= 1820
            draw.text((50, 905 + j * 46), line, font=font(32), fill='white')
        draw.text((50, 1040), '제공 이미지 확대 편집 · 화면 수치는 캡처 시점 기준 · 한국어 자막 · 음성 없음',
                  font=font(20), fill='#cadcec')
        path = OUT / f'dashboard_{i + 1}.png'
        frame.save(path)
        inserted += [f"file '{path.as_posix()}'", 'duration 12.000']
    lines = (SOURCE / 'timeline.concat.txt').read_text(encoding='utf-8').splitlines()
    lines[2:2] = inserted
    (OUT / 'timeline.concat.txt').write_text('\n'.join(lines), encoding='utf-8')
    v = json.loads((SOURCE / 'verification.json').read_text(encoding='utf-8'))
    chapters = v['video']['chapters']
    for chapter in chapters[1:]:
        chapter['start'] += 48
        chapter['end'] += 48
    chapters.insert(1, dict(title='대시보드 화면 설명', start=12, end=60))
    meta = [';FFMETADATA1', 'title=' + v['video']['title'], 'artist=' + v['video']['provider']]
    for ch in chapters:
        meta += ['[CHAPTER]', 'TIMEBASE=1/1000', f"START={round(ch['start'] * 1000)}",
                 f"END={round(ch['end'] * 1000)}", 'title=' + ch['title']]
    (OUT / 'chapters.ffmeta').write_text('\n'.join(meta), encoding='utf-8')
    srt = next(SOURCE.glob('*.srt'))
    blocks = srt.read_text(encoding='utf-8-sig').strip().split('\n\n')
    entries = []
    for block in blocks:
        parts = block.splitlines()
        start, end = map(seconds, parts[1].split(' --> '))
        entries.append((start + (48 if start >= 12 else 0),
                        end + (48 if start >= 12 else 0), '\n'.join(parts[2:])))
    entries += [(12 + i * 12, 24 + i * 12, slide[2]) for i, slide in enumerate(SLIDES)]
    entries.sort()
    (OUT / srt.name).write_text('\n\n'.join(
        f'{i + 1}\n{stamp(start)} --> {stamp(end)}\n{text}'
        for i, (start, end, text) in enumerate(entries)) + '\n', encoding='utf-8-sig')
    script = ['# 대시보드 설명 추가본', '',
              '00:00–00:12: docs/main_image.png 첫 화면 유지.',
              '00:12–01:00: 제공 이미지 확대 편집으로 대시보드 항목을 설명합니다. 클릭 시연은 포함하지 않습니다.',
              '수치 의미는 templates/dashboard.html 기준이며, 수치는 제공 이미지 촬영 시점 기준입니다.',
              '데이터 점검·품질 검토 기능은 설명에서 제외합니다.', '', '## 전체 장 구성', '']
    for ch in chapters:
        script += [f"- {stamp(ch['start'])}–{stamp(ch['end'])}: {ch['title']}"]
    script += ['', '## 자막 대본', '']
    for start, end, text in entries:
        script += [f'### {stamp(start)}–{stamp(end)}', '', text, '']
    (OUT / '소개영상_시나리오.md').write_text('\n'.join(script), encoding='utf-8-sig')
    output = OUT / v['video']['file']
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    duration = v['video']['seconds'] + 48
    print('Encoding dashboard overview', flush=True)
    subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat',
                    '-safe', '0', '-i', str(OUT / 'timeline.concat.txt'), '-i', str(OUT / 'chapters.ffmeta'),
                    '-map_metadata', '1', '-map_chapters', '1', '-vf', 'fps=15,format=yuv420p',
                    '-t', str(duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-movflags', '+faststart', str(output)], check=True)
    subprocess.run([ff, '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    for t in (0, 15, 27, 39, 51, 61):
        subprocess.run([ff, '-y', '-v', 'error', '-ss', str(t), '-i', str(output),
                        '-frames:v', '1', str(OUT / f'qa_{t}.png')], check=True)
    v['video'].update(seconds=duration, bytes=output.stat().st_size,
                      segments=v['video']['segments'] + 4, decode='passed')
    v['dashboard'] = dict(start=12, end=60, captioned_slides=4,
                          source='docs/main_image.png', definitions='templates/dashboard.html',
                          presentation='Still-image overview; no click simulation')
    v['transition_frames_checked_seconds'] = [0, 15, 27, 39, 51, 61]
    (OUT / 'verification.json').write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output, flush=True)


if __name__ == '__main__':
    main()
