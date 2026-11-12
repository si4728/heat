"""Copy configured iris2 GGUF files into a separate, config-safe transfer bundle."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '이관' / '로컬모델_20261111'
CONFIG = ROOT / 'llm_integration/models.local.json'
CHUNK = 8 * 1024 * 1024


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            result.update(chunk)
    return result.hexdigest()


def main():
    # Only iris2's local environment and existing offline model config are used.
    sys.path.insert(0, str(ROOT.parent))
    from iris2.llm_integration.model_config import load_local_runtime_config
    runtime = load_local_runtime_config(CONFIG)
    sources = {}
    for spec in runtime.models.values():
        source = spec.model_path
        if not source.is_relative_to(ROOT / 'data/llm/models') or source.suffix.lower() != '.gguf' or source.is_symlink():
            raise ValueError('Only iris2-local GGUF models may be copied')
        with source.open('rb') as stream:
            if stream.read(4) != b'GGUF':
                raise ValueError('Invalid GGUF signature: ' + source.name)
        sources[source] = spec
    if DEST.exists():
        raise RuntimeError('Destination already exists; preserve the existing transfer copy')
    required = sum(path.stat().st_size for path in sources)
    free = shutil.disk_usage(ROOT).free
    if free < required + 128 * 1024 * 1024:
        raise RuntimeError(f'Insufficient free space: need {required} bytes plus overhead, free {free}')
    DEST.mkdir(parents=True)
    entries = []
    for source, spec in sources.items():
        relative = source.relative_to(ROOT)
        destination = DEST / '복사대상' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        before = source.stat()
        print('Copying ' + source.name + f' ({before.st_size} bytes)', flush=True)
        source_hash = hashlib.sha256()
        with source.open('rb') as stream, destination.open('xb') as target:
            for block in iter(lambda: stream.read(CHUNK), b''):
                source_hash.update(block)
                target.write(block)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError('Source model changed during copy')
        print('Verifying ' + source.name, flush=True)
        expected = source_hash.hexdigest()
        if destination.stat().st_size != before.st_size or digest(destination) != expected:
            raise RuntimeError('Copied model hash mismatch')
        entries.append(dict(package_path=destination.relative_to(DEST).as_posix(),
            operational_path=relative.as_posix(), kind='model', model_key=spec.key,
            bytes=before.st_size, sha256=expected))
        print('Verified ' + source.name, flush=True)
    # Recreate only validated non-secret model settings, not arbitrary private keys.
    raw = json.loads(CONFIG.read_text(encoding='utf-8'))
    settings = dict(default_model_key=runtime.default_model_key, models=[],
                    local_llm_cache=dict(mode='keep_loaded' if runtime.keep_loaded else 'unload',
                        max_loaded_models=runtime.max_loaded_models, serialize_requests=runtime.serialize_requests))
    for spec in runtime.models.values():
        settings['models'].append(dict(key=spec.key, label=spec.label, provider=spec.provider,
            model_name=spec.model_name, model_path='../' + spec.model_path.relative_to(ROOT).as_posix(),
            llama_n_ctx=spec.llama_n_ctx))
    settings_path = DEST / '설정_검토용/llm_integration/models.local.json'
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    requirements_path = DEST / '의존성_검토용/llm_integration/requirements.txt'
    requirements_path.parent.mkdir(parents=True)
    shutil.copy2(ROOT / 'llm_integration/requirements.txt', requirements_path)
    for path, kind, operational in [(settings_path, 'config_review', 'llm_integration/models.local.json'),
                                    (requirements_path, 'dependency_review', 'llm_integration/requirements.txt')]:
        entries.append(dict(package_path=path.relative_to(DEST).as_posix(), operational_path=operational,
            kind=kind, bytes=path.stat().st_size, sha256=digest(path)))
    versions = {'python': sys.version.split()[0]}
    for package in ('llama-cpp-python', 'sqlglot'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    manifest = dict(format='iris2-local-model-transfer-v1', date='2026-11-11',
        default_model_key=runtime.default_model_key, model_bytes=required, files=entries,
        development_versions=versions, model_inference_tested=False, production_applied=False,
        database_or_database_config_included=False)
    (DEST / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    guide = ['# 로컬 모델 별도 이관 안내', '',
        '소스 통합 이관본과 별도로 사용하는 모델 묶음입니다. 운영서버 적용은 하지 않았습니다.', '',
        f'- 모델 {len(sources)}개, 합계 {required:,}바이트 (약 {required / 10**9:.2f}GB / {required / 1024**3:.2f}GiB).',
        f'- 기본 모델 키: {runtime.default_model_key}.',
        '- Gemma가 기본 모델이며 Qwen은 설정된 대체 모델입니다. 기존 웹 기능에는 두 모델이 모두 필수인 것은 아니지만 이 설정의 모든 모델을 사용할 수 있도록 둘 다 복사했습니다.', '',
        '## 복사 위치', '', '| 이관 폴더의 파일 | 운영 iris2 기준 위치 | 처리 |', '|---|---|---|']
    for entry in entries:
        action = '모델 파일 복사' if entry['kind'] == 'model' else '자동 덮어쓰기 금지 · 비교 후 반영'
        guide.append(f"| `{entry['package_path']}` | `<운영 iris2>/{entry['operational_path']}` | {action} |")
    guide += ['', '## 적용 순서', '',
        '1. 이 폴더 전체를 운영서버로 전달한 뒤 검증.ps1을 실행해 전달본 해시를 확인합니다.',
        '2. 운영 iris2/data/llm/models/ 폴더를 준비하고 복사대상/data/llm/models/ 아래 GGUF 파일을 같은 위치로 복사합니다. 기존 파일이 있으면 해시를 비교하고 같으면 복사를 생략합니다. 다른 파일은 운영 사용 여부와 복원본을 확인한 뒤 교체합니다.',
        '3. 설정_검토용/llm_integration/models.local.json을 기존 운영 설정과 비교합니다. 기존 설정은 백업하고 필요한 모델 항목과 default_model_key만 반영합니다. 파일 전체를 자동 덮어쓰지 않습니다. 신규 설치라면 검토본을 운영 llm_integration/models.local.json으로 복사합니다.',
        '4. model_path는 models.local.json이 있는 llm_integration/ 폴더를 기준으로 해석합니다. ../data/llm/models/... 경로이므로 운영 설치 드라이브가 달라도 iris2 내부 구조를 유지하면 됩니다.',
        '5. 운영의 iris2/.venv 환경과 llama-cpp-python 의존성을 확인합니다. 의존성 검토 파일은 무조건 설치하지 않습니다. 같은 OS/Python/CPU·GPU 환경에 맞는 승인된 wheel이 필요할 수 있으며 이 묶음에 wheel은 없습니다.',
        '6. 소스 통합본의 모델 로더/설정 파서 및 Text-to-SQL 코드가 반영돼 있어야 합니다. Text-to-SQL의 전용 SELECT 계정 설정은 별도 운영 사전 조건이며 이 모델 묶음에 DB 계정·설정을 포함하지 않았습니다.',
        '7. 설정 반영 후 기존 방식으로 웹 앱을 재시작하고 Text-to-SQL 생성 및 조회를 확인합니다. 모델은 최초 요청 때 지연 로딩됩니다. 시작 health 응답만으로 모델 추론이 검증된 것은 아닙니다.', '',
        '## 기본 모델 변경', '',
        '- Gemma: default_model_key = iris2_text_to_sql_gemma',
        '- Qwen: default_model_key = iris2_text_to_sql',
        '- 운영의 기존 다른 모델 항목을 임의 삭제하지 않습니다. 변경 전 설정을 별도로 백업합니다.', '',
        '## 검증', '',
        '- 원본 GGUF 시그니처, 복사 도중 원본 크기/수정 시각, 원본·사본 SHA-256 일치를 확인했습니다.',
        '- 모델 설정은 현재 설정의 검증된 모델·캐시 필드만 재작성했습니다. DB 설정·비밀값·세션 키는 포함하지 않습니다.',
        '- 검증.ps1은 이 전달 폴더의 파일 해시만 읽어 확인하며 운영 파일을 복사·삭제·변경하지 않습니다.',
        '- 모델 실제 추론, 대상 운영서버 CPU/GPU·메모리 적합성은 이번 복사에서 시험하지 않았습니다.',
        '- Gemma 단일 파일이 4GB보다 커 FAT32 저장매체에는 복사할 수 없습니다. exFAT/NTFS 등 해당 파일 크기를 지원하는 저장매체를 사용합니다.', '',
        '개발 환경 버전: ' + json.dumps(versions, ensure_ascii=False), '']
    (DEST / '모델_이관안내.md').write_text('\n'.join(guide), encoding='utf-8-sig')
    verify = '''$ErrorActionPreference = "Stop"
$Manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$BundleRoot = [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\\') + '\\'
foreach ($Entry in $Manifest.files) {
    $Target = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot $Entry.package_path))
    if (-not $Target.StartsWith($BundleRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Path outside bundle' }
    $Actual = Get-FileHash -LiteralPath $Target -Algorithm SHA256
    if ($Actual.Hash.ToLowerInvariant() -ne $Entry.sha256) { throw ('Hash mismatch: ' + $Entry.package_path) }
    Write-Output ('OK: ' + $Entry.package_path)
}
Write-Output 'All model transfer files verified. No operational files were modified.'
'''
    (DEST / '검증.ps1').write_text(verify, encoding='utf-8-sig')
    (DEST / 'checksums.json').write_text(json.dumps({p.relative_to(DEST).as_posix(): digest(p)
        for p in DEST.rglob('*') if p.is_file() and p.suffix != '.gguf'}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(destination=str(DEST), models=len(sources), bytes=required,
        default_model_key=runtime.default_model_key, hashes_verified=True), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
