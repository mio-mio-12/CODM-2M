import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch,Mock
from codm_compiler.catalog import scan,priority
from codm_compiler.imgui_ui import BrowserState
class ScanTests(unittest.TestCase):
 def test_parallel_patch_selection_and_corrupt_file(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);base=root/'Extract/base/a.pak';patchfile=root/'PersistentData/Extract/2/a.pak';bad=root/'bad.pak'
   for p in [base,patchfile,bad]:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'data')
   def read(p):
    if p.name=='bad.pak':raise ValueError('bad bundle')
    return {'engine':'test','nodes':[{'name':'BuildPlayer-Test'}]}
   with patch('codm_compiler.catalog.directory',side_effect=read):
    one=scan(root,root/'one.json',lambda _:None,workers=1);four=scan(root,root/'four.json',lambda _:None,workers=4)
   self.assertEqual(one,four);self.assertEqual(one['maps'][0]['path'],str(patchfile));self.assertEqual(len(one['errors']),1)
 def test_extract_before_persistent_is_valid(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'Extract/PersistentData/a.pak';p.parent.mkdir(parents=True);p.write_bytes(b'x')
   self.assertEqual(priority(p)[0],1)
 def test_scan_defers_previews(self):
  with tempfile.TemporaryDirectory() as d:
   s=BrowserState(d);s.source=d
   with patch.object(s,'start') as start:s.scan()
   self.assertTrue(start.call_args.args[0]['defer_previews'])
 def test_background_previews_do_not_block_export(self):
  with tempfile.TemporaryDirectory() as d:
   s=BrowserState(d);s.source=d;s.catalog={'root':d,'maps':[{'name':'MP_Test_Atlases','path':'a.pak'}]};s.refresh();s.selected={s.entries[0]['id']}
   worker=Mock();worker.poll.return_value=None
   def start(job):s.process=worker;s.job=Path(d)/'preview.json'
   with patch.object(s,'start',side_effect=start):s.start_previews()
   self.assertIsNone(s.process);self.assertIs(s.preview_process,worker);self.assertTrue(s.can_export())
   s.stop_previews();worker.terminate.assert_called_once()
