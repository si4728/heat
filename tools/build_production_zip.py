"""Build a data-free Windows deployment from current working-tree sources."""
from __future__ import annotations

import ast
import configparser
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dist'
NAME = 'iris2-production-20261103.zip'

GUIDE = r'''# IRIS2 운영서버 설치 안내 (2026-11-03)

이 패키지는 현재 작업 폴더의 수정 사항을 포함한 Windows x64용 코드 배포본입니다.
기준 환경: Python 3.14.6 x64, MariaDB 11.4.12, 웹 포트 4824, DB 포트 3307.
최상위 폴더 이름은 반드시 iris2로 유지하십시오. 기존 iris와 독립된 경로를 사용합니다.

## 1. Python 설치 및 패키지 설치

Python 3.14 x64를 설치하고 ZIP을 풀어 iris2 폴더에서 실행합니다.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

requirements.txt는 현재 로컬 환경에서 사용한 웹/DB/PDF/ML 패키지 버전을 고정했습니다.
인터넷이 차단된 서버는 같은 OS/Python의 별도 PC에서 아래 명령으로 wheel을 준비해 옮깁니다.

```powershell
py -3.14 -m pip download -r requirements.txt -d wheelhouse
# 운영서버:
.\.venv\Scripts\python.exe -m pip install --no-index --find-links wheelhouse -r requirements.txt
```

Python 설치 프로그램과 wheel은 ZIP에 포함하지 않았습니다.

## 2. MariaDB 및 데이터 별도 이전

runtime에는 현재 프로젝트의 독립 MariaDB Windows 실행 파일이 포함되어 있습니다.
실행 중인 data/mariadb 폴더를 그대로 복사하지 마십시오. 쓰기와 작업을 중지한 시점의
일관된 mariadb-dump 논리 백업을 만들고, 새로운 독립 MariaDB 11.4 인스턴스에 복원합니다.
현재 DB 데이터와 과거 database_snapshot은 이 ZIP에 없습니다.
필요 스키마는 iris2, iris2_ml, iris2_llm, iris2_pdf 네 개입니다.
구조/트리거/루틴/데이터와 사용자 권한을 검증하고 운영 계정 로그인도 확인하십시오.
원본 iris나 운영 SQLite를 직접 마이그레이션 소스로 사용하지 마십시오.

Windows에서 번들 DB를 새로 초기화할 경우 (새 빈 data/mariadb에 한해서):

```powershell
New-Item -ItemType Directory -Force data,logs | Out-Null
.\runtime\mariadb-11.4.12-winx64\bin\mariadb-install-db.exe --datadir="$PWD\data\mariadb" --port=3307 --password="서버에서_정한_새_ROOT_암호"
```

위 암호는 실제 서버에서 정하고 명령 이력 취급에 유의하십시오. 생성된 data/mariadb/my.ini의
basedir/datadir/log 경로를 새 서버의 iris2 내부 경로로 확인하고 port=3307,
bind-address=127.0.0.1 및 utf8mb4를 설정하십시오. 기존 인스턴스에는 초기화 명령을 실행하지 마십시오.
별도 Windows 서비스로 이미 DB가 실행 중이면 서버를 직접 server.py로 시작합니다.

앱 계정 iris2_app: 네 스키마에 SELECT, INSERT, UPDATE, DELETE.
ML 계정 iris2_readonly: 네 스키마에 SELECT만 부여합니다.
백업용 관리 계정은 별도로 만들고 실제 백업/독립 복원으로 필요한 권한을 검증합니다.
config/*.example.conf를 해당 *.conf 이름으로 복사하고 새 DB 계정과 암호를 입력합니다.
기존 비공개 config 폴더는 접근이 제한되어 복사하지 않았습니다.
DB 환경변수나 .env 대신 config/database.conf를 읽습니다.
관리 기능은 로컬 DB 127.0.0.1:3307 및 번들 MariaDB 클라이언트를 사용합니다.

## 3. PDF / iris 데이터 / 파일 경로

PDF와 iris 데이터 폴더는 별도로 iris2 내부로 옮기십시오.
hx_configuration.conf의 paths 기본값은 data/pdf_reports, data/uploads, data/reports입니다.
data/source_json, data/asset_path_map.json, 관련 업로드/첨부/ML 산출물 등도 필요한 경우 별도 이전합니다.
예전 절대 경로가 남은 DB 파일 참조와 asset_path_map.json의 키/목적지는 새 서버 기준으로
검토하고 수정해야 합니다. 목적지 파일은 모두 iris2 내부에 있어야 합니다.
PDF 열기와 JSON 원본 연결을 실제 화면에서 확인하십시오.
data/.session_secret는 복사하지 않았으며 최초 실행 때 새로 생성됩니다.

## 4. 실행 및 확인

```powershell
.\.venv\Scripts\python.exe server.py --health-check
.\.venv\Scripts\python.exe server.py --host 127.0.0.1 --port 4824 --no-browser
```

http://127.0.0.1:4824/api/health에서 정상 상태를 확인합니다.
DB가 별도로 실행되고 있어야 합니다. 로컬 번들 DB를 사용하며 my.ini가 준비된 경우 run.ps1도 사용할 수 있습니다.
외부 접속은 서버 환경에 맞게 리버스 프록시/TLS와 방화벽을 설정하고,
HTTPS 구성 후 hx_configuration.conf의 session_cookie_secure=true를 적용합니다.
서버 자동 시작은 위 직접 실행 명령을 작업 스케줄러 또는 서비스 관리 도구에 등록하십시오.
로그인/권한, VCM1·VCM2 조회, 저장, Excel, PDF, 백업 및 독립 복원을 확인한 뒤 운영 전환합니다.
복원 후 데이터 대조와 현장 UAT/공학 승인 여부는 별도로 확인해야 합니다.
전환 중에는 쓰기를 중지하고 최종 백업을 복원하십시오. 쓰기 재개 후 과거 DB로 단순 회귀하지 마십시오.

## 5. 로컬 LLM (선택 기능)

기본 웹/ML requirements와 별도로 llm_integration/requirements.txt의 llama-cpp-python이 필요합니다.
서버 CPU/GPU와 Python에 맞는 승인된 wheel 및 GGUF 모델을 별도로 준비하십시오.
llm_integration/models.local.example.json을 참고해 로컬 설정을 만들고 경로를 바꿉니다.
모델 파일과 LLM 런타임은 포함하지 않았으며 새 서버에서의 추론은 검증하지 않았습니다.

## 패키지 검증 범위

ZIP CRC, 파일별 SHA-256, Python 구문, 주요 런타임 리소스 포함 여부를 검사했습니다.
새 서버의 pip 설치, DB 복원, 서비스 구동을 완료했다는 의미는 아닙니다.
manifest.json은 ZIP 내부 모든 배포 파일의 해시를 제공합니다.
제외: data 전체, PDF 전체, uploads, backups, reports, outputs, database_snapshot,
.venv, .git, 개인 비밀설정, 세션 키, 모델, 캐시, 개발 도구/테스트.
'''


def main():
    files: dict[str, bytes] = {}
    def add(path):
        if path.is_symlink():
            raise ValueError(f'Symlink rejected: {path}')
        rel = path.relative_to(ROOT)
        if '__pycache__' in rel.parts or path.suffix.lower() in {'.pyc', '.pdf', '.gguf'}:
            return
        if path.name == 'models.local.json':
            return
        files[rel.as_posix()] = path.read_bytes()

    for path in ROOT.glob('*.py'):
        if not path.name.startswith(('test_', 'legacy_')) and path.name not in {'server_v3.py'}:
            add(path)
    for directory in ['application', 'domain', 'web', 'ml', 'templates', 'static', 'migration', 'llm_integration', 'runtime/mariadb-11.4.12-winx64']:
        for path in (ROOT / directory).rglob('*'):
            if path.is_file() and not {'tests', 'reference'}.intersection(path.relative_to(ROOT / directory).parts):
                add(path)
    for name in ['APPLICATION_BOUNDARY.md', 'compose.yaml', 'run.ps1', 'run.cmd', 'start_mariadb.ps1', 'restart_iris2.ps1', 'requirements-ml-lock.txt']:
        add(ROOT / name)
    for path in (ROOT / 'docs').rglob('*.md'):
        add(path)
    requirements = (ROOT / 'requirements-lock.txt').read_bytes()
    files['requirements.txt'] = requirements
    files['requirements-lock.txt'] = requirements
    config = configparser.ConfigParser(interpolation=None)
    config.read(ROOT / 'hx_configuration.conf', encoding='utf-8')
    config['application']['secret_key'] = ''
    config['access']['api_write_token'] = ''
    config['access']['authentication_required'] = 'true'
    config['server']['host'] = '127.0.0.1'
    stream = io.StringIO()
    config.write(stream)
    files['hx_configuration.conf'] = stream.getvalue().encode('utf-8')
    for role, user in [('', 'iris2_app'), ('-readonly', 'iris2_readonly'), ('-admin', 'iris2_backup')]:
        files[f'config/database{role}.example.conf'] = (f'[database]\nhost = 127.0.0.1\nport = 3307\nname = iris2\nuser = {user}\npassword =\ncharset = utf8mb4\n\n[schemas]\nheat_exchanger_db3.db = iris2\nml_review_feedback.db = iris2_ml\nllm_report_review.db = iris2_llm\npdf_ocr_review.db = iris2_pdf\n').encode()
    files['setup.ps1'] = b'''$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
py -3.14 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed" }
'''
    files['DEPLOYMENT_KO.md'] = GUIDE.encode('utf-8')
    files['README.md'] = '# IRIS2 production bundle\n\n설치 및 별도 데이터 이전: [DEPLOYMENT_KO.md](DEPLOYMENT_KO.md)\n'.encode('utf-8')
    for name, content in files.items():
        if name.endswith('.py'):
            ast.parse(content.decode('utf-8-sig'), filename=name)
    manifest = {'format': 'iris2-production-v1', 'database_included': False,
                'python': '3.14.6', 'platform': 'Windows x64',
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}}
    files['manifest.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    DEST.mkdir(exist_ok=True)
    target = DEST / NAME
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, content in sorted(files.items()):
            archive.writestr('iris2/' + name, content)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, expected in manifest['files'].items():
            assert hashlib.sha256(archive.read('iris2/' + name)).hexdigest() == expected
        for required in ['server.py', 'app.py', 'requirements.txt', 'static/vendor/three/three.min.js', 'runtime/mariadb-11.4.12-winx64/bin/mariadb-dump.exe']:
            assert 'iris2/' + required in archive.namelist(), required
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + NAME + '\n', encoding='ascii')
    (DEST / 'DEPLOYMENT_KO.md').write_text(GUIDE, encoding='utf-8')
    print(json.dumps({'archive': str(target), 'files': len(files), 'bytes': target.stat().st_size, 'sha256': digest, 'verified': True}))


if __name__ == '__main__':
    main()
