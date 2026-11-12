"""Synthesize Korean narration and retime still scenes to avoid rushed speech."""
import asyncio
import hashlib
import json
import re
import subprocess
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/dashboard_v8'
OUT = ROOT / 'outputs/narrated_v9'
FF = imageio_ffmpeg.get_ffmpeg_exe()
RATE = 24000


def ts(value):
    n = round(value * 1000)
    return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'


def sec(value):
    h, m, s, ms = map(int, re.split('[:,]', value))
    return h*3600 + m*60 + s + ms/1000


def spoken(text):
    for a, b in [('(주)', '주식회사 '), ('VCM1', '브이 씨 엠 일'), ('VCM2', '브이 씨 엠 이'),
                 ('IRIS2', '아이리스 투'), ('IRIS', '아이리스'), ('Tube', '튜브'),
                 ('Shell', '셸'), ('3D', '쓰리 디'), ('QR-code', '큐알 코드'),
                 ('QR', '큐알'), ('DB', '디비'), ('Map', '맵'), ('API 510', '에이피아이 오백십'),
                 ('E-106', '이 백육'), ('E-121A', '이 백이십일 에이'),
                 ('·', ', '), ('\n', ' '), ('클릭:', '')]:
        text = text.replace(a, b)
    return text


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    audio_dir = OUT / 'audio'
    audio_dir.mkdir(exist_ok=True)
    frames = OUT / 'frames'
    frames.mkdir(exist_ok=True)
    srt = next(SOURCE.glob('*.srt'))
    entries = []
    for block in srt.read_text(encoding='utf-8-sig').strip().split('\n\n'):
        lines = block.splitlines()
        start, end = map(sec, lines[1].split(' --> '))
        entries.append(dict(start=start, end=end, text='\n'.join(lines[2:])))
    timeline = (SOURCE / 'timeline.concat.txt').read_text(encoding='utf-8').splitlines()
    paths = [Path(line[6:-1]) for line in timeline if line.startswith('file ')]
    assert len(paths) == len(entries) + 1
    groups = []
    for i, e in enumerate(entries):
        if groups and groups[-1]['text'] == e['text']:
            groups[-1]['indices'].append(i)
        else:
            groups.append(dict(text=e['text'], indices=[i]))
    limiter = asyncio.Semaphore(3)
    completed = 0

    async def synthesize(group):
        nonlocal completed
        speech = spoken(group['text'])
        key = hashlib.sha256(('SunHi+5%' + speech).encode()).hexdigest()[:20]
        mp3 = audio_dir / (key + '.mp3')
        async with limiter:
            if not mp3.exists() or mp3.stat().st_size == 0:
                for attempt in range(3):
                    try:
                        await edge_tts.Communicate(speech, 'ko-KR-SunHiNeural', rate='+5%').save(str(mp3))
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(1)
            raw = subprocess.run([FF, '-v', 'error', '-i', str(mp3), '-f', 's16le',
                                  '-ac', '1', '-ar', str(RATE), '-'], capture_output=True, check=True).stdout
        group['pcm'] = raw
        group['speech_seconds'] = len(raw) / (RATE*2)
        group['spoken_text'] = speech
        completed += 1
        if completed % 10 == 0 or completed == len(groups):
            print(f'Speech {completed}/{len(groups)}', flush=True)

    await asyncio.gather(*(synthesize(g) for g in groups))
    elapsed = 0
    mapping = {0: 0}
    concat = []
    rendered = {}
    captions = []
    manifest = []
    wave_path = OUT / 'narration.wav'
    font = ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', 18)
    with wave.open(str(wave_path), 'wb') as output_audio:
        output_audio.setnchannels(1)
        output_audio.setsampwidth(2)
        output_audio.setframerate(RATE)
        for group in groups:
            indices = group['indices']
            original_duration = sum(entries[i]['end'] - entries[i]['start'] for i in indices)
            duration = max(original_duration, group['speech_seconds'] + .65)
            duration = round(duration * RATE) / RATE
            extra = duration - original_duration
            group_start = elapsed
            output_audio.writeframes(b'\0' * (round(.2*RATE)*2))
            output_audio.writeframes(group['pcm'])
            padding = round(duration*RATE) - round(.2*RATE) - len(group['pcm'])//2
            assert padding >= 0
            output_audio.writeframes(b'\0' * (padding*2))
            for i in indices:
                entry = entries[i]
                mapping[round(entry['start']*1000)] = elapsed
                length = entry['end'] - entry['start'] + (extra if i == indices[-1] else 0)
                path = paths[i]
                if i != 0:
                    if path not in rendered:
                        edited = frames / (hashlib.sha256(str(path).encode()).hexdigest()[:20] + '.png')
                        with Image.open(path) as source:
                            image = source.convert('RGB')
                        d = ImageDraw.Draw(image)
                        d.rectangle((0, 1036, 1920, 1080), fill='#10263c')
                        d.text((45, 1047), '화면 편집 · 한국어 자막 · AI 합성 음성 안내', font=font, fill='#cadcec')
                        image.save(edited)
                        rendered[path] = edited
                    path = rendered[path]
                concat += [f"file '{path.as_posix()}'", f'duration {length:.6f}']
                captions.append((elapsed, elapsed + length, entry['text']))
                elapsed += length
                mapping[round(entry['end']*1000)] = elapsed
            manifest.append(dict(start=group_start, end=elapsed, original_seconds=original_duration,
                                 speech_seconds=group['speech_seconds'], text=group['text'],
                                 spoken_text=group['spoken_text']))
    concat.append(concat[-2])
    (OUT / 'timeline.concat.txt').write_text('\n'.join(concat), encoding='utf-8')
    (OUT / srt.name).write_text('\n\n'.join(
        f'{i+1}\n{ts(start)} --> {ts(end)}\n{text}' for i, (start, end, text) in enumerate(captions))+'\n', encoding='utf-8-sig')
    v = json.loads((SOURCE / 'verification.json').read_text(encoding='utf-8'))
    for chapter in v['video']['chapters']:
        chapter['start'] = mapping[round(chapter['start']*1000)]
        chapter['end'] = mapping[round(chapter['end']*1000)]
    meta = [';FFMETADATA1', 'title='+v['video']['title'], 'artist='+v['video']['provider'],
            'comment=Korean AI-synthesized narration; still scenes extended to fit speech.']
    for ch in v['video']['chapters']:
        meta += ['[CHAPTER]', 'TIMEBASE=1/1000', f"START={round(ch['start']*1000)}",
                 f"END={round(ch['end']*1000)}", 'title='+ch['title']]
    (OUT / 'chapters.ffmeta').write_text('\n'.join(meta), encoding='utf-8')
    (OUT / 'narration_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    script = ['# 한국어 음성 내레이션 대본', '', 'AI 합성 음성: ko-KR-SunHiNeural.',
              '대본을 읽는 데 필요한 만큼 정지 화면 길이를 늘렸습니다. 중복되는 연속 3D 자막은 한 번 읽습니다.', '']
    for item in manifest:
        script += [f"## {ts(item['start'])}–{ts(item['end'])}", '', item['spoken_text'], '']
    (OUT / '음성_대본.md').write_text('\n'.join(script), encoding='utf-8-sig')
    video = OUT / v['video']['file']
    print(f'Encoding narrated video: {elapsed:.3f} seconds', flush=True)
    subprocess.run([FF, '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                    '-i', str(OUT/'timeline.concat.txt'), '-i', str(wave_path), '-i', str(OUT/'chapters.ffmeta'),
                    '-map', '0:v:0', '-map', '1:a:0', '-map_metadata', '2', '-map_chapters', '2',
                    '-vf', 'fps=15,format=yuv420p', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11',
                    '-t', str(elapsed), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                    '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', str(video)], check=True)
    subprocess.run([FF, '-v', 'error', '-i', str(video), '-f', 'null', '-'], check=True)
    v['video'].update(seconds=round(elapsed, 3), bytes=video.stat().st_size, audio=True, decode='passed')
    v['narration'] = dict(voice='ko-KR-SunHiNeural', type='AI synthesized', groups=len(groups),
                          alignment='Each utterance fits its scene; still scenes extended as needed',
                          speech_seconds=sum(g['speech_seconds'] for g in groups))
    v['dashboard']['start'] = mapping[12000]
    v['dashboard']['end'] = mapping[60000]
    v['transition_frames_checked_seconds'] = []
    v['opening'] = 'docs/main_image.png; full image retained for the opening narration'
    for i, t in enumerate([0, v['dashboard']['start']+1, v['dashboard']['end']+1]):
        subprocess.run([FF, '-y', '-v', 'error', '-ss', str(t), '-i', str(video), '-frames:v', '1',
                        str(OUT/f'qa_{i}.png')], check=True)
        v['transition_frames_checked_seconds'].append(t)
    (OUT / 'verification.json').write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding='utf-8')
    print(video, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
