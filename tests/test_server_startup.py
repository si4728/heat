import importlib.util,json,sys,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
spec=importlib.util.spec_from_file_location('iris2_launcher',ROOT/'server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class ServerStartupTests(unittest.TestCase):
 def response(self,payload):
  opener=MagicMock()
  opener.open.return_value.__enter__.return_value.read.return_value=json.dumps(payload).encode()
  return opener
 def test_healthy_duplicate_success(self):
  opener=self.response({'application':'iris2','backend':'mariadb','status':'ok'})
  with patch.object(server,'build_opener',return_value=opener):
   self.assertEqual(server.existing_iris2_url('0.0.0.0',4824),'http://127.0.0.1:4824')
  with patch.object(server,'create_app'),patch.object(server,'create_listener',side_effect=OSError()),patch.object(server,'existing_iris2_url',return_value='http://127.0.0.1:4824'),patch.object(sys,'argv',['server.py']):
   self.assertEqual(server.main(),0)
 def test_other_service_and_unhealthy_are_not_accepted(self):
  for payload in [{'status':'ok','backend':'mariadb'},{'application':'iris2','backend':'mariadb','status':'error'},[]]:
   with self.subTest(payload=payload),patch.object(server,'build_opener',return_value=self.response(payload)):
    self.assertIsNone(server.existing_iris2_url('127.0.0.1',4824))
 def test_unavailable_listener_keeps_error_exit(self):
  with patch.object(server,'create_app'),patch.object(server,'create_listener',side_effect=OSError()),patch.object(server,'existing_iris2_url',return_value=None),patch.object(sys,'argv',['server.py']):
   with self.assertRaises(SystemExit) as caught: server.main()
   self.assertEqual(caught.exception.code,2)
 def test_probe_failure_is_safe(self):
  opener=MagicMock();opener.open.side_effect=TimeoutError()
  with patch.object(server,'build_opener',return_value=opener):
   self.assertIsNone(server.existing_iris2_url('::',4824))
if __name__=='__main__':unittest.main()
