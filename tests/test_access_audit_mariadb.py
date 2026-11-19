"""Writable audit checks use a disposable iris2-only MariaDB schema, never business rows."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash
from iris2 import database
from iris2.app import create_app
from iris2.application.access_audit import AccessAuditEvent, audit_rows, append_events
from iris2.db_config import load_database_config
from iris2.iris_v2_models import AppUser, UserScreenPermission, SchemaVersion
from iris2.migration.access_audit import apply_migration, VERSION
from iris2.migration.migrate_all import engine_for


class AccessAuditMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            admin=load_database_config(admin=True)
            settings=load_database_config()
        except ValueError:
            raise unittest.SkipTest('Private local MariaDB configuration is required')
        cls.schema='iris2_test_access_audit_'+uuid.uuid4().hex[:12]
        assert re.fullmatch('iris2_test_access_audit_[0-9a-f]{12}',cls.schema)
        cls.admin=engine_for(admin,'mysql')
        cls.runtime_user=settings['user']
        cls.granted_hosts=[]
        with cls.admin.begin() as c:
            c.exec_driver_sql(f'CREATE DATABASE `{cls.schema}` CHARACTER SET utf8mb4')
        cls.addClassCleanup(cls.drop_schema)
        cls.engine=engine_for(admin,cls.schema)
        for table in [AppUser.__table__,UserScreenPermission.__table__,SchemaVersion.__table__]:
            table.create(cls.engine)
        apply_migration(cls.engine)
        apply_migration(cls.engine)
        with cls.admin.begin() as c:
            for host in ('localhost','127.0.0.1'):
                if c.exec_driver_sql('SELECT COUNT(*) FROM mysql.user WHERE User=%s AND Host=%s',(settings['user'],host)).scalar():
                    c.exec_driver_sql(f'GRANT SELECT,INSERT,UPDATE,DELETE ON `{cls.schema}`.* TO %s@%s',(settings['user'],host))
                    cls.granted_hosts.append(host)
        with Session(cls.engine) as s:
            s.add_all([AppUser(user_id=i,username=f'audit{i}@example.com',display_name=f'Audit {i}',
                password_hash=generate_password_hash('Audit-test-only-924!'),is_admin=i==1,is_active=True) for i in (1,2)])
            s.add(UserScreenPermission(user_id=2,screen_key='DASHBOARD',can_view=True,can_edit=False))
            s.commit()
        settings['name']=cls.schema
        cls.patches=[patch('iris2.database.load_database_config',return_value=settings),
            patch('iris2.services.initialize'),
            patch('iris2.services.active_theme_data',return_value=dict(preset_key='DEFAULT',background_color='#f4f7f7',label_color='#52616a')),
            patch('iris2.web.security.organization_catalog',return_value=dict(entries=[],labels={}))]
        for p in cls.patches:
            p.start();cls.addClassCleanup(p.stop)
        database.get_engine.cache_clear()
        cls.app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True,ACCESS_AUDIT_ENABLED=True))
        cls.app.view_functions['dashboard']=lambda:'dashboard'

    @classmethod
    def drop_schema(cls):
        database.get_engine().dispose()
        database.get_engine.cache_clear()
        if hasattr(cls,'engine'):cls.engine.dispose()
        if not re.fullmatch('iris2_test_access_audit_[0-9a-f]{12}',cls.schema):
            raise RuntimeError('Refusing cleanup outside disposable audit schema')
        with cls.admin.begin() as c:
            for host in cls.granted_hosts:
                c.exec_driver_sql(f'REVOKE SELECT,INSERT,UPDATE,DELETE ON `{cls.schema}`.* FROM %s@%s',(cls.runtime_user,host))
            c.exec_driver_sql(f'DROP DATABASE `{cls.schema}`')
        cls.admin.dispose()

    def client(self,uid=None):
        client=self.app.test_client()
        if uid:
            with client.session_transaction() as s:
                s.update(user_id=uid,last_activity_at=time.time(),csrf_token='audit-test-csrf')
        return client

    def test_actual_login_and_every_access_persist_without_secrets(self):
        c=self.client()
        c.get('/login')
        with c.session_transaction() as s:token=s['csrf_token']
        bad=c.post('/login?token=do-not-store-query',data=dict(username='audit1@example.com',password='do-not-store-password',csrf_token=token))
        self.assertEqual(bad.status_code,200)
        ok=c.post('/login',data=dict(username='audit1@example.com',password='Audit-test-only-924!',csrf_token=token))
        self.assertEqual(ok.status_code,302)
        self.assertEqual(ok.headers['X-Audit-Recorded'],'1')
        self.assertEqual(c.get('/').status_code,200)
        with database.get_engine().connect() as conn:
            events=[dict(r) for r in conn.execute(select(AccessAuditEvent.__table__)).mappings()]
            last_login=conn.scalar(select(AppUser.last_login_at).where(AppUser.user_id==1))
        self.assertIsNotNone(last_login)
        success=next(r for r in events if r['event_type']=='LOGIN_SUCCESS')
        accesses=[r for r in events if r['audit_session_id']==success['audit_session_id'] and r['event_type']=='ACCESS']
        self.assertGreaterEqual(len(accesses),2)
        self.assertTrue(any(r['event_type']=='LOGIN_FAILURE' for r in events))
        for secret in ('do-not-store-query','do-not-store-password',token,'Audit-test-only-924!'):
            self.assertNotIn(secret,repr(events))

    def test_admin_filters_export_and_nonadmin_denial(self):
        c=self.client(1)
        self.assertEqual(c.get('/settings/access-logs').status_code,200)
        view=c.get('/settings/access-logs?event=ACCESS&path=/settings/access-logs')
        self.assertEqual(view.status_code,200)
        self.assertIn('로그온·화면 접근 이력',view.get_data(as_text=True))
        export=c.get('/settings/access-logs/export.csv?event=ACCESS')
        self.assertEqual(export.status_code,200)
        self.assertTrue(export.data.startswith(b'\xef\xbb\xbf'))
        self.assertIn('일시(KST)',export.get_data(as_text=True))
        for path in ['/settings/access-logs','/settings/access-logs/export.csv']:
            self.assertEqual(self.client(2).get(path).status_code,403)
        self.assertEqual(c.get('/settings/access-logs?start=wrong').status_code,400)
        with database.get_engine().connect() as conn:
            count=conn.scalar(select(text('COUNT(*)')).select_from(AccessAuditEvent).where(AccessAuditEvent.result=='DENIED'))
        self.assertGreaterEqual(count,2)

    def test_append_only_guards_and_idempotent_migration(self):
        self.client(1).get('/')
        with database.get_engine().connect() as conn:
            identifier=conn.scalar(select(AccessAuditEvent.audit_event_id).limit(1))
            self.assertEqual(conn.scalar(select(text('COUNT(*)')).select_from(SchemaVersion).where(SchemaVersion.version==VERSION)),1)
        for statement in ['UPDATE access_audit_event SET username=:value WHERE audit_event_id=:id',
                          'DELETE FROM access_audit_event WHERE audit_event_id=:id']:
            with self.assertRaises(DBAPIError):
                with database.get_engine().begin() as conn:conn.execute(text(statement),dict(id=identifier,value='tampered'))

    def test_kst_day_boundaries_literal_search_and_pagination(self):
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        base=dict(created_at=now,request_id=uuid.uuid4().hex,audit_session_id=None,user_id=None,
            username='literal%_user',event_type='ACCESS',result='ALLOWED',reason='',method='GET',
            path='/pagination-test',endpoint='test',screen_key='TEST',status_code=200,
            client_ip='127.0.0.1',user_agent='test',duration_ms=1)
        append_events([dict(base,request_id=uuid.uuid4().hex) for _ in range(53)])
        first=audit_rows(dict(user='%_user'),page=1)
        second=audit_rows(dict(user='%_user'),page=2)
        self.assertEqual(first['total'],53)
        self.assertEqual(len(first['rows']),50)
        self.assertEqual(len(second['rows']),3)
        self.assertTrue({r['audit_event_id'] for r in first['rows']}.isdisjoint(r['audit_event_id'] for r in second['rows']))

if __name__=='__main__':unittest.main()
