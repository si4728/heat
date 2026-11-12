"""Remove MariaDB default PUBLIC test-schema grants on isolated iris2 only."""
import argparse
import sys
from pathlib import Path

import pymysql

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    target = load_database_config()
    admin = load_database_config(admin=True)
    address = (target['host'], target['port'])
    if address[0] not in ('localhost', '127.0.0.1') or address[1] != 3307:
        raise ValueError('Only isolated iris2 loopback:3307 is supported')
    if address != (admin['host'], admin['port']):
        raise ValueError('Admin and application database addresses differ')
    connection = pymysql.connect(**{k: admin[k] for k in
        ('host', 'port', 'user', 'password', 'charset')}, autocommit=True)
    try:
        with connection.cursor() as cursor:
            for schema in ('test', r'test\_%'):
                cursor.execute('SELECT COUNT(*) FROM mysql.db WHERE User=%s AND Db=%s',
                               ('PUBLIC', schema))
                if cursor.fetchone()[0]:
                    cursor.execute(f'REVOKE ALL PRIVILEGES ON `{schema}`.* FROM PUBLIC')
        print('Default PUBLIC test-schema privileges cleared; business grants unchanged.')
    finally:
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'PUBLIC grant repair failed ({type(exc).__name__}); inspect local DB settings.')
        raise SystemExit(1)
