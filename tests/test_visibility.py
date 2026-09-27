import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from codm_compiler.compiler import Compiler


class VisibilityTests(unittest.TestCase):
    def compiler(self,mode,active=True,include_inactive=False):
        c=Compiler.__new__(Compiler)
        obj=SimpleNamespace(path_id=7,assets_file=SimpleNamespace(name='scene'),type=SimpleNamespace(name='MeshRenderer'))
        c.source=Mock();c.source.tree.return_value={'m_Enabled':True,'m_CastShadows':mode}
        c.go_info=Mock(return_value=(object(),{'m_Name':'arbitrary textured mesh'},object()))
        c.active=Mock(return_value=active);c.include_inactive=include_inactive;c.omitted_renderers=[]

        c.components=Mock(return_value=[])
        return c,obj

    def test_shadow_only_never_becomes_a_visual_surface(self):
        for include in (False,True):
            c,obj=self.compiler(3,include_inactive=include)
            c.renderer(obj,set())
            c.components.assert_not_called()
            self.assertEqual(c.omitted_renderers,[{'sourceRenderer':'scene:7','name':'arbitrary textured mesh',
                                                  'reason':'shadows_only','shadowCastingMode':3}])

    def test_nonshadowing_and_two_sided_renderers_remain_visible(self):
        for mode in (0,1,2):
            c,obj=self.compiler(mode)
            with self.assertRaisesRegex(ValueError,'MeshRenderer has no MeshFilter'):c.renderer(obj,set())
            self.assertEqual(c.omitted_renderers,[])

    def test_lod_and_inactive_filtering_still_precede_shadow_reporting(self):
        c,obj=self.compiler(3,active=False);c.renderer(obj,set());self.assertEqual(c.omitted_renderers,[])
        c,obj=self.compiler(3);c.renderer(obj,{'scene:7'});self.assertEqual(c.omitted_renderers,[])
