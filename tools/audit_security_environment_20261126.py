"""Read security posture without printing credentials, keys or account names."""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2 import hx_configuration as config
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for


def main():
    target = load_database_config()['name']
    results = []
    for label, path in (('application', None), ('readonly', 'config/database-readonly.conf'),
                        ('text_to_sql', 'config/database-text-to-sql.conf')):
        settings = load_database_config(path=path) if path else load_database_config()
        engine = engine_for(settings, target)
        try:
            with engine.connect() as c:
                grants = [str(r[0]) for r in c.exec_driver_sql('SHOW GRANTS')]
            scopes = []
            for grant in grants:
                match = re.match(r'^GRANT (.*?) ON (.*?) TO ', grant, re.I)
                if not match:
                    scopes.append(dict(classification='role_or_other_grant'))
                    continue
                privileges, scope = match.groups()
                scope = scope.replace('\\_', '_')
                if scope == '*.*':
                    kind = 'global'
                elif scope.startswith('`' + target + '`.') or scope.startswith(target + '.'):
                    kind = 'business_schema'
                elif any(scope.startswith('`' + name + '`.') or scope.startswith(name + '.')
                         for name in ('iris2_ml', 'iris2_llm', 'iris2_pdf')):
                    kind = 'auxiliary_schema'
                elif re.search(r'iris2_test_', scope):
                    kind = 'test_schema'
                else:
                    kind = 'other_schema'
                scopes.append(dict(classification=kind, privileges=privileges.split(', ')))
            results.append(dict(profile=label, database_loopback=settings['host'] in ('localhost', '127.0.0.1', '::1'),
                grants=scopes, grant_option=any('WITH GRANT OPTION' in g.upper() for g in grants)))
        finally:
            engine.dispose()
    report = dict(authentication_required=config.AUTHENTICATION_REQUIRED,
        cookie_http_only=config.SESSION_COOKIE_HTTPONLY, cookie_same_site=config.SESSION_COOKIE_SAMESITE,
        cookie_secure=config.SESSION_COOKIE_SECURE, idle_seconds=config.SESSION_IDLE_TIMEOUT_SECONDS,
        session_secret_at_least_32=len(config.APP_SECRET_KEY) >= 32,
        write_api_enabled=bool(config.API_WRITE_TOKEN), require_https=config.SECURITY_REQUIRE_HTTPS,
        trusted_hosts_configured=bool(config.SECURITY_TRUSTED_HOSTS), trusted_proxy_configured=bool(config.SECURITY_TRUSTED_PROXY),
        database_profiles=results)
    out = Path('reports/security-review-20261126')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'environment.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
