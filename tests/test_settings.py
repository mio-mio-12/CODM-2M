import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from codm_compiler.imgui_ui import BrowserState
class SettingsTests(unittest.TestCase):
 def test_first_run_and_saved_directory(self):
  with tempfile.TemporaryDirectory() as d:
   s=BrowserState(d);self.assertEqual(s.source,'')
   with patch.object(s,'scan') as scan:s.set_source(d);scan.assert_called_once()
   self.assertEqual(BrowserState(d).source,str(Path(d).resolve()))
 def test_cache_cannot_override_setting(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'settings.ini').write_text('[paths]\ncodm_directory='+d+'\n');(p/'catalog.json').write_text(json.dumps({'root':d+'/other','maps':[]}))
   s=BrowserState(d);self.assertEqual(s.source,d);self.assertIsNone(s.catalog)
 def test_bad_settings_reprompt(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'settings.ini'
   for text in ['invalid','[paths]\ncodm_directory='+d+'/missing']:
    p.write_text(text);self.assertEqual(BrowserState(d).source,'')
 def test_failed_save_keeps_selection(self):
  with tempfile.TemporaryDirectory() as d:
   s=BrowserState(d);s.settings=Path(d)/'missing/settings.ini'
   with self.assertRaises(OSError):s.set_source(d)
   self.assertEqual(s.source,'')
