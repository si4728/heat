"""Explicitly authorized private transfer: never print credentials or SQL."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


def main():
    from iris2.db_config import load_database_config
    from iris2.mariadb_operations import create_backup
    import pymysql

    private_configs = {}
    settings = []
    for name in ['database.conf', 'database-readonly.conf', 'database-admin.conf']:
        path = ROOT / 'config' / name
        private_configs['config/' + name] = path.read_bytes()
        settings.append(load_database_config(path=path, admin=name == 'database-admin.conf'))
    admin = settings[-1]
    connection = pymysql.connect(**{('database' if key == 'name' else key): value for key, value in admin.items()})
    sql = ['-- PRIVATE: restore ONLY into a NEW isolated MariaDB instance.',
           '-- CREATE OR REPLACE replaces matching DB accounts and their grants.',
           '-- Includes authentication hashes; keep private.']
    count = 0
    try:
        with connection.cursor() as cursor:
            for user in sorted({item['user'] for item in settings}):
                cursor.execute('SELECT User, Host FROM mysql.user WHERE User=%s ORDER BY Host', (user,))
                accounts = cursor.fetchall()
                if not accounts:
                    raise RuntimeError('Configured database account not found; export stopped')
                for account_user, host in accounts:
                    account = connection.escape(account_user) + '@' + connection.escape(host)
                    cursor.execute('SHOW CREATE USER ' + account)
                    definition = cursor.fetchone()[-1]
                    sql.append(definition.replace('CREATE USER ', 'CREATE OR REPLACE USER ', 1) + ';')
                    cursor.execute('SHOW GRANTS FOR ' + account)
                    sql.extend(row[0] + ';' for row in cursor.fetchall())
                    count += 1
    finally:
        connection.close()
    backup = ROOT / 'backups' / 'production-transfer-20261103.zip'
    backup_manifest = create_backup(backup)
    if not backup_manifest['source_stable_during_capture']:
        raise RuntimeError('Database changed during capture; retry during a quiet period')
    public = ROOT / 'dist' / 'iris2-production-20261103.zip'
    target = ROOT / 'dist' / 'iris2-production-private-20261103.zip'
    guide = '''# 비밀번호 및 웹 권한 포함 비공개 배포본

이 ZIP은 DB 접속 비밀번호 원문, DB 계정 인증 해시 및 권한,
웹 계정 비밀번호 해시와 웹 권한을 포함합니다. 기존 웹 비밀번호로 로그인할 수 있도록
현재 네 스키마의 데이터를 변조 없이 백업했습니다. 비밀번호는 화면/로그에 출력하지 않았습니다.
PDF와 별도 iris 파일 데이터는 포함하지 않았습니다.

1. 새 서버에서 iris2 폴더 이름을 유지하고 DEPLOYMENT_BASE_KO.md의 Python 설치 절차를 따릅니다.
2. 새 독립 MariaDB 11.4 인스턴스만 준비하십시오. 기존 운영 DB에 복원하지 마십시오.
3. private_transfer/database-backup.zip을 풀어 database.sql을 MariaDB 관리자 클라이언트에서 SOURCE로 복원합니다.
4. private_transfer/database-accounts.sql을 같은 관리자 클라이언트에서 SOURCE로 실행합니다.
   구성된 앱/읽기전용/관리 계정의 모든 기존 Host 항목을 포함하며,
   CREATE OR REPLACE USER는 같은 이름의 계정을 대체하므로 반드시 새 독립 인스턴스에서만 실행합니다.
   현재 관리자와 같은 계정이 대체되면 새 접속부터 이전 DB 암호가 적용됩니다.
   서버를 바꾸면 계정 Host와 인증 플러그인 가용성도 확인해야 합니다.
5. config/database.conf, database-readonly.conf, database-admin.conf는 기존 암호를 포함해 준비되어 있습니다.
   새 서버에서도 기본 연결은 127.0.0.1:3307을 사용합니다. 주소가 달라지면 세 설정을 일치시킵니다.
6. 웹 계정/권한은 DB 백업에 포함되어 있으므로 비밀번호를 재설정하거나 계정을 새로 만들지 않습니다.
7. PDF/JSON/첨부와 필요한 파일 데이터는 별도로 iris2 내부로 이전하고 절대 경로 참조를 조정합니다.
8. .venv/Scripts/python.exe server.py --health-check 후 server.py로 실행하고 기존 계정 로그인과 권한을 확인합니다.

이 비공개 배포본에서는 기본 안내의 '현재 DB 없음', '비밀번호 없음', '설정 템플릿만 있음',
'새 계정/비밀번호 생성' 부분 대신 위 절차를 적용하십시오.
세션 비밀키는 새로 생성되므로 기존 브라우저 세션은 다시 로그인해야 합니다.
DB 백업은 단일 트랜잭션 덤프이며 백업 전후 테이블/뷰/트리거/루틴 지문 일치를 확인했습니다.
독립 서버 복원/로그인/파일 연결 및 UAT는 아직 수행하지 않았습니다.
private_transfer/backup-manifest.json에 백업 시각과 검증 지문이 있습니다.
이 ZIP을 공개 저장소에 올리지 말고 접근이 제한된 경로로 전달하십시오.
'''
    with zipfile.ZipFile(public) as source:
        files = {name.removeprefix('iris2/'): source.read(name) for name in source.namelist() if not name.endswith('/')}
    files.pop('manifest.json')
    files['DEPLOYMENT_BASE_KO.md'] = files.pop('DEPLOYMENT_KO.md')
    files['DEPLOYMENT_KO.md'] = guide.encode('utf-8')
    files.update(private_configs)
    files['private_transfer/database-accounts.sql'] = ('\n'.join(sql) + '\n').encode('utf-8')
    files['private_transfer/database-backup.zip'] = backup.read_bytes()
    files['private_transfer/backup-manifest.json'] = json.dumps(backup_manifest, indent=2).encode('utf-8')
    manifest = {'format': 'iris2-private-production-v1', 'contains_secrets': True,
                'database_included': True, 'database_accounts': count,
                'restoration_tested': False,
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    files['manifest.json'] = json.dumps(manifest, indent=2).encode('utf-8')
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr('iris2/' + name, data)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, expected in manifest['files'].items():
            assert hashlib.sha256(archive.read('iris2/' + name)).hexdigest() == expected
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest() + '  ' + target.name + '\n', encoding='ascii')
    (ROOT / 'dist' / 'PRIVATE_DEPLOYMENT_KO.md').write_text(guide, encoding='utf-8')
    print(json.dumps({'archive': str(target), 'bytes': target.stat().st_size, 'files': len(files),
                      'database_accounts': count, 'stable_snapshot': True, 'verified': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Library connection errors can contain credentials. Suppress all details.
        print('Private bundle failed safely; error type: ' + type(error).__name__)
        raise SystemExit(1)
