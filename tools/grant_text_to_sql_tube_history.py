"""Add SELECT on tube identity tables to the configured local Text-to-SQL account."""
import argparse
import re
import sys
from pathlib import Path

import pymysql

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))
from iris2.db_config import load_database_config


def apply():
    target = load_database_config()
    reader = load_database_config(path=APP_DIR / 'config/database-text-to-sql.conf')
    admin = load_database_config(admin=True)
    address = (target['host'], target['port'])
    if address[0] not in ('localhost', '127.0.0.1') or address[1] != 3307:
        raise ValueError('Only isolated iris2 loopback:3307 is supported')
    if any((c['host'], c['port']) != address for c in (reader, admin)):
        raise ValueError('Database addresses differ')
    if not re.fullmatch(r'iris2[a-zA-Z0-9_]*', target['name']):
        raise ValueError('Invalid schema')
    if reader['name'] != target['name'] or not reader['user'].startswith('iris2') or reader['user'] == admin['user']:
        raise ValueError('Invalid read-only account')
    connection = pymysql.connect(**{k: admin[k] for k in
        ('host', 'port', 'user', 'password', 'charset')}, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT Host FROM mysql.user WHERE User=%s AND Host IN (%s,%s)',
                           (reader['user'], 'localhost', '127.0.0.1'))
            hosts = [row[0] for row in cursor.fetchall()]
            if not hosts:
                raise ValueError('Configured account does not exist')
            for host in hosts:
                for table in ('heat_exchanger_tube', 'tube_bundle'):
                    cursor.execute(f"GRANT SELECT ON `{target['name']}`.`{table}` TO %s@%s",
                                   (reader['user'], host))
    finally:
        connection.close()
    print('Tube identity SELECT grants applied; credentials unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    try:
        apply()
    except Exception as exc:
        print(f'Tube history grant update failed ({type(exc).__name__}).')
        raise SystemExit(1)
