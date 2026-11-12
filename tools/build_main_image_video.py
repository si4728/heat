"""Rebuild the introduction using the supplied docs/main_image.png."""
import json
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/hanwha_intro_v6'
OUT = ROOT / 'outputs/main_image_v7'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    supplied = ROOT / 'docs/main_image.png'
    with Image.open(supplied) as source:
        opening = ImageOps.pad(source.convert('RGB'), (1920, 1080),
                               method=Image.Resampling.LANCZOS, color='#10263c')
    intro = OUT / 'intro.png'
    opening.save(intro)
    lines = (SOURCE / 'timeline.concat.txt').read_text(encoding='utf-8').splitlines()
    assert lines[1] == 'duration 12.000'
    lines[0] = f"file '{intro.as_posix()}'"
    timeline = OUT / 'timeline.concat.txt'
    timeline.write_text('\n'.join(lines), encoding='utf-8')
    for pattern in ('*.ffmeta', '*.srt', '*.md'):
        for path in SOURCE.glob(pattern):
            shutil.copy2(path, OUT / path.name)
    for path in OUT.glob('*.md'):
        text = path.read_text(encoding='utf-8-sig')
        text = text.replace('\n\n', '\n\n첫 화면(00:00–00:12): 사용자가 제공한 `docs/main_image.png` 전체를 비율 유지하여 표시합니다.\n\n', 1)
        path.write_text(text, encoding='utf-8-sig')
    verification = json.loads((SOURCE / 'verification.json').read_text(encoding='utf-8'))
    output = OUT / verification['video']['file']
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error',
                    '-f', 'concat', '-safe', '0', '-i', str(timeline),
                    '-i', str(OUT / 'chapters.ffmeta'), '-map_metadata', '1',
                    '-map_chapters', '1', '-vf', 'fps=15,format=yuv420p',
                    '-t', str(verification['video']['seconds']), '-c:v', 'libx264',
                    '-preset', 'veryfast', '-crf', '20', '-movflags', '+faststart',
                    str(output)], check=True)
    subprocess.run([ff, '-v', 'error', '-i', str(output), '-f', 'null', '-'], check=True)
    subprocess.run([ff, '-y', '-v', 'error', '-i', str(output), '-frames:v', '1',
                    str(OUT / 'qa_opening.png')], check=True)
    verification['video'].update(bytes=output.stat().st_size, decode='passed')
    verification['opening'] = 'docs/main_image.png; uncropped, aspect ratio preserved; 0–12 seconds'
    (OUT / 'verification.json').write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output, flush=True)


if __name__ == '__main__':
    main()
