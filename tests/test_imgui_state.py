import tempfile
import unittest
from codm_compiler.imgui_ui import BrowserState


class BrowserTests(unittest.TestCase):
    def test_export_options_root_guard_and_variant(self):
        with tempfile.TemporaryDirectory() as d:
            s=BrowserState(d);s.catalog={'root':d,'maps':[{'name':'MP_Test_Atlases','path':'test.pak'}]}
            s.source=d;s.refresh();s.selected={s.entries[0]['id']}
            self.assertEqual(s.scenes(),['MP_Test_Atlases']);self.assertTrue(s.can_export())
            s.source=d+'/other';self.assertFalse(s.can_export());s.source=d
            s.geometry=False;s.spawns=s.volumes=s.tactical=False
            self.assertFalse(s.can_export());s.tactical=True;self.assertTrue(s.can_export())
            s.process=object();self.assertFalse(s.can_export())


if __name__=='__main__':unittest.main()
