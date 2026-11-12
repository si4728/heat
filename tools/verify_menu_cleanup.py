"""Read-only role/navigation checks with authenticated MariaDB-backed pages."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from iris2 import dbapi, services
from iris2.hx_configuration import DB_PATH
from iris2.app import create_app


def main():
    connection=dbapi.connect(DB_PATH,readonly=True)
    try:
        uid=connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
        client=app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid,last_activity_at=time.time(),csrf_token='menu-local-preview')
        output=ROOT/'reports/menu-cleanup-20261112'
        output.mkdir(parents=True,exist_ok=True)
        for name,url in [('dashboard','/'),('exchangers','/exchangers?search=E-111'),('analysis','/analysis?unit=VCM1')]:
            response=client.get(url)
            assert response.status_code==200
            html=response.get_data(as_text=True)
            assert 'id="administrator-settings"' in html and 'id="general-navigation"' in html
            if name=='exchangers':
                import re
                from html import unescape
                linked=re.search(r'class="strong-link" href="(/analysis\?[^\"]+)"',html)
                assert linked
                assert client.get(unescape(linked[1])).status_code==200
                assert 'Excel Export' in html
            (output/f'{name}.html').write_text(html.replace('"/static/','"'+(ROOT/'static').as_uri()+'/'),encoding='utf-8')
        ordinary=dict(user_id=uid,username='navigation-reader',is_admin=False,is_active=True,
            permissions={key:dict(can_view=True,can_edit=False) for key in
                         ['DASHBOARD','EXCHANGERS','REMAINING_LIFE','INSPECTIONS','MAINTENANCE']})
        with patch('iris2.services.user_access_profile',return_value=ordinary):
            response=client.get('/exchangers?search=E-111')
            assert response.status_code==200
            html=response.get_data(as_text=True)
            assert 'id="administrator-settings"' not in html
            assert '열교환기 등록' not in html and 'Excel Export' not in html
            (output/'ordinary.html').write_text(html.replace('"/static/','"'+(ROOT/'static').as_uri()+'/'),encoding='utf-8')
            for url in ['/imports','/settings/users','/settings/backups','/settings/database-monitor']:
                assert client.get(url).status_code==403,url
        result=dict(authenticated_pages=3,general_menu_entries=5,
                    ordinary_admin_routes_denied=True,exchanger_links_to_analysis=True,database_mutated=False)
        (output/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally:
        connection.rollback();connection.close()


if __name__=='__main__':
    main()
