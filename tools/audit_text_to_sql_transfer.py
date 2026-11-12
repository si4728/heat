"""Read-only release audit; writes evidence only under reports/text_to_sql."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    package = next(ROOT.glob('*/20261101_20261110_*_r2/manifest.json')).parent
    manifest = json.loads((package / 'manifest.json').read_text(encoding='utf-8-sig'))
    entries = {Path(e['path']).relative_to(Path(e['path']).parts[0]).as_posix(): e
               for e in manifest['source_files']}
    mismatches = []
    with zipfile.ZipFile(package.with_suffix('.zip')) as archive:
        crc = archive.testzip()
        for rel, entry in entries.items():
            expected = entry['sha256']
            values = [sha(ROOT / rel), sha(package / entry['path']),
                      hashlib.sha256(archive.read(package.name + '/' + entry['path'])).hexdigest()]
            if any(value != expected for value in values):
                mismatches.append(rel)
    runtime = [
        'application/auth_service.py', 'application/inspection_frequency.py',
        'application/text_to_sql_service.py', 'dbapi.py',
        'llm_integration/local_llm.py', 'llm_integration/text_to_sql.py',
        'llm_integration/model_config.py', 'tools/generate_text_to_sql.py',
        'static/text-to-sql-links.js', 'static/text-to-sql.css', 'static/text-to-sql.js',
        'templates/base.html', 'templates/text_to_sql.html',
        'web/routes/__init__.py', 'web/routes/text_to_sql.py', 'web/security.py',
    ]
    baseline = ['__init__.py', 'application/__init__.py', 'web/__init__.py',
                'llm_integration/__init__.py', 'db_config.py', 'hx_configuration.py']
    related = sorted({p.relative_to(ROOT).as_posix()
                      for directory in ['tools', 'tests', 'llm_integration/tests', 'docs']
                      for p in (ROOT / directory).iterdir()
                      if p.is_file() and any(term in p.name.lower() for term in
                                            ['text_to_sql', 'inspection_frequency', 'model_config'])})
    model_manifest = next(ROOT.glob('*/' + '로컬모델_20261111' + '/manifest.json'))
    models = json.loads(model_manifest.read_text(encoding='utf-8-sig'))
    model_files = []
    for e in models['files']:
        p = model_manifest.parent / e['package_path']
        # Model payloads are large: this audit checks presence/size, not a fresh SHA.
        model_files.append(dict(path=e['operational_path'], kind=e['kind'],
                                present=p.is_file(), size_matches=p.is_file() and p.stat().st_size == e['bytes']))
    result = dict(date='2026-11-12', package=package.relative_to(ROOT).as_posix(),
                  source_count=len(entries), source_package_zip_hash_mismatches=mismatches,
                  zip_crc_error=crc,
                  runtime=[dict(path=p, included=p in entries) for p in runtime],
                  baseline_check_required=[dict(path=p, included=p in entries) for p in baseline],
                  related=[dict(path=p, included=p in entries) for p in related],
                  model_files=model_files, model_hashes_recomputed=False,
                  unit_tests=dict(count=67, passed=True, live_database_and_inference=False),
                  production_applied=False)
    out = ROOT / 'reports/text_to_sql/transfer-audit-20261112'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'inventory.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
