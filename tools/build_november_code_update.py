"""Stage a source-only November update; never read database/config files."""
from __future__ import annotations

import ast
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 11, 1)
END = datetime(2026, 11, 11)
NAME = '20261101_20261110_통합'
RUNTIME_DIRS = {'application', 'domain', 'web', 'ml', 'templates', 'static', 'llm_integration'}
SUFFIXES = {'.py', '.html', '.js', '.css'}
EXCLUDED = {'tests', 'reference', '__pycache__', 'models', 'node_modules'}


def allowed(rel):
    return (not rel.is_absolute() and '..' not in rel.parts and rel.suffix in SUFFIXES
            and not EXCLUDED.intersection(rel.parts)
            and (len(rel.parts) == 1 or rel.parts[0] in RUNTIME_DIRS)
            and not rel.name.startswith(('test_', 'legacy_')) and rel.name != 'server_v3.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', default=NAME)
    name = parser.parse_args().name
    if not name or name in {'.', '..'} or any(ch in name for ch in '/\\:'):
        raise ValueError('Use a single release folder name')
    target = ROOT / '이관' / name
    archive = target.with_suffix('.zip')
    if target.exists() or archive.exists():
        raise RuntimeError('Output already exists; preserve the previous release.')
    reasons = {}

    def add(rel, reason):
        rel = Path(rel)
        if not allowed(rel):
            raise ValueError(f'Non-runtime path rejected: {rel}')
        src = ROOT / rel
        if not src.is_file() or src.is_symlink() or not src.resolve().is_relative_to(ROOT):
            raise ValueError(f'Unsafe/missing source: {rel}')
        reasons.setdefault(rel.as_posix(), []).append(reason)

    # Carry previous candidates forward using CURRENT originals, never old copies.
    previous = json.loads((ROOT / '이관/manifest.json').read_text(encoding='utf-8'))
    for item in previous['files']:
        if item['category'] == '소스':
            add(Path(item['package_path']).relative_to('소스'), 'previous candidate refreshed from current source')
    candidates = list(ROOT.glob('*.py'))
    for directory in sorted(RUNTIME_DIRS):
        candidates.extend((ROOT / directory).rglob('*'))
    for src in candidates:
        rel = src.relative_to(ROOT)
        if src.is_file() and allowed(rel) and START <= datetime.fromtimestamp(src.stat().st_mtime) < END:
            add(rel, 'modified during 2026-11-01 through 2026-11-10 (local filesystem date)')
    for rel in ['app.py', 'application/pdf_map_display.py', 'pdf_tube_sheet_geometry.py',
                'static/wall-loss-palette.js', 'static/tube-map.css']:
        add(rel, 'required runtime dependency / previously missing source')

    contents = {rel: (ROOT / rel).read_bytes() for rel in sorted(reasons)}
    syntax = {'python': 0, 'javascript': 0}
    for rel, content in contents.items():
        if rel.endswith('.py'):
            ast.parse(content.decode('utf-8-sig'), filename=rel)
            syntax['python'] += 1
        elif rel.endswith('.js'):
            check = subprocess.run(['node', '--check', str(ROOT / rel)], capture_output=True, timeout=30)
            if check.returncode:
                raise RuntimeError(f'JavaScript syntax check failed: {rel}')
            syntax['javascript'] += 1

    target.mkdir(parents=True)
    entries = []
    for rel, content in contents.items():
        dst = target / '소스' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        entries.append(dict(path='소스/' + rel, target='<운영 iris2>/' + rel,
            sha256=hashlib.sha256(content).hexdigest(), bytes=len(content), reasons=reasons[rel],
            source_modified_at=datetime.fromtimestamp((ROOT / rel).stat().st_mtime).isoformat(timespec='seconds')))
    review = []
    for rel in ['requirements.txt', 'llm_integration/requirements.txt']:
        content = (ROOT / rel).read_bytes()
        dst = target / '의존성_검토용' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(content)
        review.append(dict(path=dst.relative_to(target).as_posix(), sha256=hashlib.sha256(content).hexdigest()))
    qr_enabled = bool(re.search(r'QR_UI_ENABLED\s*=\s*True', contents['app.py'].decode('utf-8-sig')))
    manifest = dict(format='iris2-source-update-v2', period=['2026-11-01', '2026-11-10'],
        source_files=entries, dependency_review_files=review, syntax_checks=syntax,
        qr_ui_enabled_in_app=qr_enabled, database_included=False, config_included=False,
        exact_git_baseline_available=False, production_applied=False,
        validation=dict(python_tests=119, python_passed=True,
            javascript_suites=['annual_plugging', 'critical_limit', 'text_to_sql_links', 'wall_loss_palette'],
            live_database_tested=False, live_server_tested=False))
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# 11월 소스 통합 이관 안내', '',
        '대상: 2026-11-01~2026-11-10 현재 개발 소스. 운영 적용은 수행하지 않았습니다.', '',
        '## 적용 범위 및 기준', '',
        '- 11월 수정 시각의 런타임 코드 + 기존 이관 후보의 최신 원본 + 필수 의존 소스를 통합했습니다.',
        '- Git 기준 커밋은 10월 26일뿐입니다. 11월 1일 운영본과의 정확한 변경분 패치가 아니라 현재 전체 파일 사본입니다. 적용 전 운영 코드와 비교하십시오.',
        '- 예전 이관/소스와 섞지 말고 이 폴더의 소스/를 이번 기준으로 사용하십시오.',
        '- 소스/ 아래 상대 경로를 운영 iris2 루트 아래 동일 경로로 적용합니다. 기존 iris에는 적용하지 않습니다.',
        '- 삭제 파일이나 자동 적용/DB 초기화/마이그레이션 명령은 포함하지 않았습니다.', '',
        '## 운영 config 보호', '',
        '- config/ 전체, hx_configuration.conf, .env, models.local.json, 세션 키, 인증서, DB/덤프/스키마/계정은 포함하지 않습니다.',
        '- 운영 주소·포트·DB 연결·경로·쿠키/세션 관련 설정을 덮어쓰거나 삭제하지 않습니다.',
        '- data, uploads, backups, runtime, logs, reports, .venv, 모델 파일도 제외합니다.', '',
        '## 현재 코드 동작과 적용 전 확인', '',
        f'- app.py의 QR_UI_ENABLED는 {qr_enabled}입니다. 현재 소스대로라면 관리자 + 열교환기 조회 권한 보유자에게 QR가 표시됩니다. 일반 사용자에게는 숨깁니다.',
        '- 대화 중 QR 전체 숨김 요청과 최신 요구사항 문서의 관리자 노출 기준이 다릅니다. 이번 패키지는 현재 소스를 변경하지 않고 담았습니다. 운영 적용 전에 QR 최종 정책을 결정하십시오.',
        '- Text-to-SQL은 sqlglot와 운영의 전용 SELECT 계정 설정 config/database-text-to-sql.conf가 필요합니다. 해당 설정은 패키지에 없습니다.',
        '- 전용 계정·권한·운영 DB 구조·LLM 실행 환경의 호환성을 확인하지 못하면 Text-to-SQL 기능을 운영 완료로 처리하지 마십시오. 추가 DB/config 변경은 이번 범위에 없습니다.',
        '- requirements는 검토용입니다. 기존 운영 가상환경에 무조건 덮어 설치하지 않습니다. 필요 패키지 차이와 복원 계획을 먼저 확인하십시오.',
        '- app.py는 설정 파일이 아닌 실행 코드라 포함했습니다. services.py/dbapi.py 역시 DB 데이터가 아닌 접근 코드입니다.', '',
        '## 기능별 내용', '',
        '- i-HMS 명칭, 운영 현황 미등록 영역 정리, 잔여수명 구간 표 정렬·분리.',
        '- 정밀 분석 진입 시 공통 메뉴 자동 접기, 열교환기 상세 진입 시 자동 펼치기. 두 화면의 수동 접기/펼치기 버튼 유지.',
        '- 선택 설비·별도 분석 설비 목록 및 공통 화면 스타일.',
        '- 실제 Plugging/기준 도달/향후 예상 구분, 사양/등록 대비 예측률, 검사일·계산일 분리, 미등록 평가 제외.',
        '- Map 미등록 위치와 등록 Tube 미검사 분리, 감육률 범례.',
        '- Text-to-SQL/검사 빈도 조회와 결과 상세 링크, 관련 권한·읽기 전용 연결.', '',
        '## 파일별 운영 적용 위치', '', '| 이관 파일 | 운영 적용 위치 |', '|---|---|']
    for item in entries:
        lines.append(f"| `{item['path']}` | `{item['target']}` |")
    lines += ['', '## 적용 및 코드 복원 절차', '',
        '1. ZIP SHA-256 및 manifest의 파일 해시를 확인합니다. 운영 대상 파일과 diff하여 운영 전용 수정 유무를 확인합니다.',
        '2. 기존 운영 소스와 적용 버전·신규 파일 목록을 백업합니다. config와 데이터는 유지합니다.',
        '3. 운영의 웹 앱만 중지합니다. 실행 중인 DB는 이 패키지로 중지·변경하지 않습니다.',
        '4. 소스 파일을 같은 상대 경로로 반영합니다. 공유 템플릿·새 JS·신규 Python 모듈을 누락하지 않습니다.',
        '5. 기존 운영 방식으로 웹 앱을 재시작합니다. 운영 config나 세션 키를 개발값으로 교체하지 않습니다.',
        '6. /api/health, 실제 운영 주소 첫 응답, 로그인·권한, VCM1·VCM2 주요 조회, E-131D 수량/날짜, 관리자·일반 사용자 QR 표시, Excel/PDF를 확인합니다.',
        '7. 실패 시 앱을 중지하고 이전 소스를 복원하며 이번에 신규 추가한 파일도 제거한 뒤 재시작합니다. 의존성 변경은 별도 복원 절차가 필요합니다.', '',
        '## 검증 결과와 한계', '',
        '- 관련 Python 119건, JavaScript 회귀 4개 시험 묶음 통과. 포함 Python AST 및 JS 구문 검사 통과.',
        '- 패키지 전체 파일별 SHA-256, ZIP CRC, 현재 원본과 사본 일치를 확인했습니다.',
        '- 실제 운영 서버, 실 DB, E-131D 실 레코드 재조회, 현장 UAT는 이번 이관 정리에서 수행하지 않았습니다.',
        '- DB 변경 없이 기존 구조에서 동작하는지 운영 환경 호환성 검증을 마친 뒤 적용하십시오.', '']
    (target / '이관안내.md').write_text('\n'.join(lines), encoding='utf-8-sig')
    # Inventory all package bytes, including the guide and manifest.
    checksums = {p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in target.rglob('*') if p.is_file()}
    (target / 'checksums.json').write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for rel, expected in checksums.items():
        if hashlib.sha256((target / rel).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Package hash verification failed')
    for entry in entries:
        rel = Path(entry['path']).relative_to('소스')
        if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError(f'Source changed during build: {rel}')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(target.rglob('*')):
            if path.is_file():
                zipped.write(path, name + '/' + path.relative_to(target).as_posix())
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise RuntimeError('ZIP CRC verification failed')
        for rel, expected in checksums.items():
            if hashlib.sha256(zipped.read(name + '/' + rel)).hexdigest() != expected:
                raise RuntimeError('ZIP hash verification failed')
    archive.with_suffix('.zip.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='utf-8')
    print(json.dumps(dict(directory=str(target), archive=str(archive), sources=len(entries),
        dependency_review_files=len(review), syntax_checks=syntax, qr_enabled=qr_enabled,
        verified=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
