"""Provision an independent SELECT-only account; never alter existing accounts."""
from __future__ import annotations

import argparse
import configparser
import re
import secrets
import sys
from pathlib import Path

import pymysql

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))
from iris2.db_config import load_database_config


def provision():
    destination = APP_DIR / "config/database-text-to-sql.conf"
    if destination.exists():
        print("Text-to-SQL private configuration already exists; left unchanged.")
        return
    target = load_database_config()
    admin = load_database_config(admin=True)
    if target['host'] not in ('127.0.0.1', 'localhost') or target['port'] != 3307:
        raise ValueError("Only isolated iris2 MariaDB on loopback:3307 is supported")
    if (admin['host'], admin['port']) != (target['host'], target['port']):
        raise ValueError("Admin and application database addresses differ")
    schema = target['name']
    if not re.fullmatch(r'iris2[a-zA-Z0-9_]*', schema):
        raise ValueError("Invalid iris2 schema")
    user, password = 'iris2_textsql', secrets.token_urlsafe(36)
    connection = pymysql.connect(**{key: admin[key] for key in ('host','port','user','password','charset')}, autocommit=True)
    created = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE User=%s", (user,))
            if cursor.fetchone()[0]:
                raise ValueError("Account exists without matching local configuration; left unchanged")
            for host in ('localhost', '127.0.0.1'):
                cursor.execute("CREATE USER %s@%s IDENTIFIED BY %s", (user, host, password))
                created.append(host)
                for table in ('heat_exchanger', 'equipment', 'process_unit', 'iris_inspection', 'iris_tube_result'):
                    cursor.execute(f"GRANT SELECT ON `{schema}`.`{table}` TO %s@%s", (user, host))
            settings = dict(target, user=user, password=password)
            parser = configparser.ConfigParser(interpolation=None)
            parser['database'] = {key: str(value) for key, value in settings.items()}
            with destination.open('x', encoding='utf-8') as stream:
                parser.write(stream)
    except Exception:
        with connection.cursor() as cursor:
            for host in created:
                cursor.execute("DROP USER %s@%s", (user, host))
        raise
    finally:
        connection.close()
    print("Created iris2 Text-to-SQL SELECT-only account and private local configuration.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    try:
        provision()
    except Exception as exc:
        print(f"Provisioning failed ({type(exc).__name__}); existing accounts were not modified.")
        raise SystemExit(1)
