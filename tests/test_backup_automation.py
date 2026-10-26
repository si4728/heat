import sys,tempfile,unittest,json
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2 import backup_manager as manager
KST=timezone(timedelta(hours=9))

class BackupScheduleAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        manager.save_backup_settings(self.root,dict(manager.DEFAULT_SETTINGS))
        self.now=datetime(2026,10,17,12,tzinfo=KST)
    def tearDown(self):self.temp.cleanup()
    def log(self,**overrides):
        row=manager._empty_log_record();row.update(operation='BACKUP',status='SUCCESS',started_at=self.now.isoformat(),completed_at=self.now.isoformat(),**overrides)
        manager._append_log(self.root,row)
    def test_restore_success_does_not_satisfy_backup_schedule(self):
        row=manager._empty_log_record();row.update(operation='RESTORE_VALIDATION',status='SUCCESS',started_at=self.now.isoformat(),completed_at=self.now.isoformat())
        manager._append_log(self.root,row)
        self.assertTrue(manager.backup_schedule_status(self.root,self.now)['due'])
    def test_missing_backup_does_not_satisfy_schedule(self):
        self.log(backup_file=str(self.root/'deleted.zip'))
        self.assertTrue(manager.backup_schedule_status(self.root,self.now)['due'])
    def test_false_string_does_not_enable_schedule(self):
        settings=manager._validate_settings({**manager.DEFAULT_SETTINGS,'enabled':'false'})
        self.assertFalse(settings['enabled'])
    def test_schedule_uses_korea_timezone_even_if_input_is_utc(self):
        status=manager.backup_schedule_status(self.root,datetime(2026,10,17,16,30,tzinfo=timezone.utc))
        self.assertEqual(datetime.fromisoformat(status['scheduled_for']),datetime(2026,10,17,2,tzinfo=KST))
    def test_failed_scheduled_attempt_delays_retry(self):
        slot=datetime(2026,10,17,2,tzinfo=KST)
        row=manager._empty_log_record();row.update(operation='BACKUP',trigger='scheduled',status='FAILED',scheduled_for=slot.isoformat(timespec='seconds'),started_at=self.now.isoformat(),completed_at=self.now.isoformat())
        manager._append_log(self.root,row)
        status=manager.backup_schedule_status(self.root,self.now)
        self.assertFalse(status['due'])
        self.assertEqual(datetime.fromisoformat(status['next_run']),self.now+timedelta(minutes=30))
    def test_disabled_schedule_has_no_next_run(self):
        manager.save_backup_settings(self.root,{**manager.DEFAULT_SETTINGS,'enabled':False})
        status=manager.backup_schedule_status(self.root,self.now)
        self.assertFalse(status['due']);self.assertIsNone(status['next_run'])

    def fake_backup(self,path):
        Path(path).write_bytes(b'fake-backup-for-scheduler-unit-test')
        return {'fingerprints':{'test':{}}}
    def test_manual_backup_satisfies_slot_and_file_corruption_reopens_it(self):
        with patch('iris2.mariadb_operations.create_backup',side_effect=self.fake_backup):
            record=manager.run_database_backup(self.root,'unused',requested_by='unit-test')
        now=datetime.fromisoformat(record['completed_at'])
        self.assertFalse(manager.backup_schedule_status(self.root,now)['due'])
        Path(record['backup_file']).write_bytes(b'corrupted')
        self.assertTrue(manager.backup_schedule_status(self.root,now)['due'])
    def test_retention_keeps_only_requested_count(self):
        manager.save_backup_settings(self.root,{**manager.DEFAULT_SETTINGS,'retention_count':1})
        with patch('iris2.mariadb_operations.create_backup',side_effect=self.fake_backup):
            for _ in range(3):self.assertEqual(manager.run_database_backup(self.root,'unused')['status'],'SUCCESS')
        self.assertEqual(len(list(manager.backup_paths(self.root)['files'].glob('*.zip'))),1)
    def test_two_scheduled_workers_do_not_duplicate_backup(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        import time
        barrier=Barrier(5)
        def fake(path):time.sleep(0.05);return self.fake_backup(path)
        def run(_):barrier.wait(timeout=5);return manager.run_due_backup(self.root,'unused')
        with patch('iris2.mariadb_operations.create_backup',side_effect=fake) as backup:
            with ThreadPoolExecutor(max_workers=5) as pool:list(pool.map(run,range(5)))
            self.assertEqual(backup.call_count,1)
    def test_another_process_cannot_take_backup_operation_lock(self):
        import subprocess
        script="import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from iris2.backup_manager import _operation_lock,BackupBusy\ntry:\n with _operation_lock(sys.argv[2]):raise SystemExit(2)\nexcept BackupBusy:raise SystemExit(0)"
        with manager._operation_lock(self.root):
            result=subprocess.run([sys.executable,'-c',script,str(Path(__file__).resolve().parents[2]),str(self.root)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
    def test_restore_mismatch_is_not_reported_as_success(self):
        paths=manager._ensure_directories(self.root);path=paths['files']/'test.zip';path.write_bytes(b'backup')
        with patch('iris2.mariadb_operations.restore_to_isolated_schemas',return_value={'iris2':'iris2_restore_test'}),patch('iris2.mariadb_operations.verify_restored_backup',side_effect=ValueError('private secret')):
            record=manager.run_database_restore(self.root,'unused',path.name,reason='Mismatch validation')
        self.assertEqual(record['status'],'FAILED')
        self.assertNotIn('private secret',json.dumps(record))
    def test_restore_path_traversal_rejected(self):
        with self.assertRaises(ValueError):manager.run_database_restore(self.root,'unused','../outside.zip',reason='Invalid path test')
    def test_successful_backup_is_not_reported_for_a_failed_operation(self):
        with patch('iris2.mariadb_operations.create_backup',side_effect=OSError('private password')):
            record=manager.run_database_backup(self.root,'unused')
        self.assertEqual(record['status'],'FAILED')
        self.assertNotIn('private password',json.dumps(record))
    def test_scheduler_heartbeat_is_visible(self):
        manager._write_scheduler_status(self.root,30,last_result='SUCCESS')
        status=manager.scheduler_status(self.root)
        self.assertTrue(status['running']);self.assertEqual(status['timezone'],'Asia/Seoul')

    def test_weekly_schedule_selects_correct_korean_weekday(self):
        manager.save_backup_settings(self.root,{**manager.DEFAULT_SETTINGS,'frequency':'weekly','weekday':0,'scheduled_time':'02:00'})
        status=manager.backup_schedule_status(self.root,datetime(2026,10,18,10,tzinfo=KST))
        self.assertEqual(datetime.fromisoformat(status['scheduled_for']),datetime(2026,10,12,2,tzinfo=KST))
    def test_retry_becomes_due_after_thirty_minutes(self):
        slot=datetime(2026,10,17,2,tzinfo=KST)
        row=manager._empty_log_record();row.update(operation='BACKUP',trigger='scheduled',status='FAILED',scheduled_for=slot.isoformat(timespec='seconds'),started_at=self.now.isoformat(),completed_at=self.now.isoformat())
        manager._append_log(self.root,row)
        self.assertTrue(manager.backup_schedule_status(self.root,self.now+timedelta(minutes=31))['due'])
    def test_damaged_archive_is_rejected_before_database_execution(self):
        from iris2.mariadb_operations import restore_to_isolated_schemas
        from zipfile import ZipFile
        import hashlib
        path=self.root/'damaged.zip'
        manifest={'format':'iris2-mariadb-backup-v2','schemas':['iris2','iris2_llm','iris2_ml','iris2_pdf'],'schema_roles':{name:name for name in ['iris2','iris2_llm','iris2_ml','iris2_pdf']},'sql_sha256':hashlib.sha256(b'original').hexdigest()}
        with ZipFile(path,'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest));archive.writestr('database.sql',b'changed')
        with patch('iris2.mariadb_operations.engine_for') as engine:
            with self.assertRaises(ValueError):restore_to_isolated_schemas(path,'_test_corrupt')
            engine.assert_not_called()

    def test_legacy_inventory_supports_quoted_and_unquoted_triggers(self):
        from iris2.mariadb_operations import _legacy_structure
        roles={name:name for name in ['iris2','iris2_llm','iris2_ml','iris2_pdf']}
        script=''
        for name in roles:
            script+=f"USE `{name}`;\nCREATE TABLE `record` (id int);\n"
        script+="USE `iris2`;\nCREATE TABLE `summary` (id int);\n/*!50001 VIEW `summary` AS SELECT 1 */;\n/*!50003 TRIGGER unquoted AFTER INSERT ON record FOR EACH ROW SET @v=1 */;\n/*!50003 TRIGGER `quoted` AFTER UPDATE ON record FOR EACH ROW SET @v=1 */;\n"
        result=_legacy_structure(script.encode(),roles)
        self.assertEqual(result['iris2']['tables'],['record'])
        self.assertEqual(result['iris2']['views'],['summary'])
        self.assertEqual(result['iris2']['triggers'],['quoted','unquoted'])
    def test_backup_tracks_configured_schema_mapping(self):
        from iris2.mariadb_operations import configured_schema_roles
        app={'name':'iris2_new','host':'127.0.0.1','port':3307}
        mapping={'heat_exchanger_db3.db':'iris2_new','llm_report_review.db':'iris2_llm_new','ml_review_feedback.db':'iris2_ml_new','pdf_ocr_review.db':'iris2_pdf_new'}
        with patch('iris2.dbapi.load_database_config_schemas',return_value=mapping),patch('iris2.mariadb_operations.load_database_config',return_value=app):
            roles=configured_schema_roles()
        self.assertEqual(roles['iris2'],'iris2_new')
        self.assertEqual(roles['iris2_pdf'],'iris2_pdf_new')
    def test_stale_scheduler_heartbeat_is_not_healthy(self):
        manager._write_scheduler_status(self.root,30)
        path=manager.backup_paths(self.root)['root']/'scheduler_status.json'
        status=json.loads(path.read_text());status['heartbeat_at']=(datetime.now(KST)-timedelta(minutes=10)).isoformat();path.write_text(json.dumps(status))
        self.assertFalse(manager.scheduler_status(self.root)['running'])

    def test_retention_failure_does_not_discard_a_valid_new_backup(self):
        manager.save_backup_settings(self.root,{**manager.DEFAULT_SETTINGS,'retention_count':1})
        with patch('iris2.mariadb_operations.create_backup',side_effect=self.fake_backup):
            old=manager.run_database_backup(self.root,'unused')
            original=Path.unlink
            def deny_old(path,*args,**kwargs):
                if str(path)==old['backup_file']:raise PermissionError('file is in use')
                return original(path,*args,**kwargs)
            with patch.object(Path,'unlink',deny_old):new=manager.run_database_backup(self.root,'unused')
        self.assertEqual(new['status'],'SUCCESS_WITH_NOTE')
        self.assertTrue(manager._valid_backup_record(self.root,new))
        self.assertIn('RETENTION_DELETE_FAILED',new['warnings'])
