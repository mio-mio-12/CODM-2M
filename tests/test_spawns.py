import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from codm_compiler.spawns import matching_scenes,visual_family,write_spawns


class SpawnTests(unittest.TestCase):
    def test_visual_quality_suffixes_do_not_erase_variant(self):
        self.assertEqual(visual_family('MP_Crash_Final_HQ_New_Atlases'),'MP_Crash')
        self.assertEqual(visual_family('MP_Standoff_Halloween_Atlases'),'MP_Standoff_Halloween')
        self.assertEqual(visual_family('MP_Standoff_CW_Atlases'),'MP_Standoff_CW')

    def test_variant_and_mode_sets_stay_separate(self):
        names=['BuildPlayer-MP_Standoff_Main_TDM','BuildPlayer-MP_Standoff_Halloween_Main_TDM',
               'BuildPlayer-MP_Standoff_Halloween_Main_SD','BuildPlayer-MP_Standoff_LDBasic',
               'BuildPlayer-MP_Standoff_Halloween_Atlases','BuildPlayer-MP_Standoff_Halloween_Main_TDM.sharedAssets']
        c={'bundles':[{'path':'gameplay.pak','nodes':[{'name':n} for n in names]}]}
        found=matching_scenes(c,['MP_Standoff_Halloween_Atlases'])
        self.assertEqual({r[3] for r in found},{'Main_TDM','Main_SD'})
        self.assertEqual(len(found),2)
        self.assertEqual(matching_scenes(c,['MP_Standoff_CW_Atlases']),[])

    def test_sidecar_failure_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'spawns.json';write_spawns(p,{'sets':[]})
            before=p.read_bytes()
            with self.assertRaises(ValueError):write_spawns(p,{'position':[float('nan'),0,0]})
            self.assertEqual(p.read_bytes(),before)
            self.assertFalse(p.with_suffix('.json.partial').exists())

    def test_map_export_writes_sidecar_and_c2mx_reference(self):
        from codm_compiler.compiler import Compiler
        from codm_compiler.formats import read_extension
        from test_compiler import fixture
        catalog={'root':'fixture','bundles':[],'maps':[{'name':'MP_Test_Atlases','node':'scene','path':'test.pak'}]}
        with tempfile.TemporaryDirectory() as temp:
            c=Compiler(catalog,temp,log=lambda _:None)
            mesh,material=fixture()
            c.renderer=lambda *_:(c.meshes.append(mesh),c.materials.items.append(material))
            scene=SimpleNamespace(objects={1:SimpleNamespace(type=SimpleNamespace(name='MeshRenderer'))})
            data={'schema':'codm.spawns/1','status':'found','complete':True,'spawnCount':1,
                  'sets':[{'mode':'Main_TDM','spawns':[{'position':[1,2,3]}]}],'errors':[]}
            with patch.object(c.source,'load'),patch.object(c.source,'file',return_value=scene),patch('codm_compiler.spawns.extract_spawns',return_value=data):
                report=c.run(['MP_Test_Atlases'],sidecars=['spawns'])
            self.assertEqual(json.loads((Path(temp)/'spawns.json').read_text()),data)
            self.assertEqual(report['spawnCount'],1)
            self.assertEqual(read_extension(Path(temp)/'MP_Test_Atlases.c2m')['META']['spawnFile'],'spawns.json')
            self.assertTrue((Path(temp)/'MP_Test_Atlases.glb').is_file())

    def test_map_export_writes_gameplay_and_tactical_without_spawns(self):
        from codm_compiler.compiler import Compiler
        from codm_compiler.formats import read_extension
        from test_compiler import fixture
        catalog={'root':'fixture','bundles':[],'maps':[{'name':'MP_Test_Atlases','node':'scene','path':'test.pak'}]}
        with tempfile.TemporaryDirectory() as temp:
            c=Compiler(catalog,temp,log=lambda _:None);mesh,material=fixture()
            c.renderer=lambda *_:(c.meshes.append(mesh),c.materials.items.append(material))
            scene=SimpleNamespace(objects={1:SimpleNamespace(type=SimpleNamespace(name='MeshRenderer'))})
            volumes={'schema':'codm.gameplay-volumes/1','count':1,'status':'found','complete':True,'sets':[]}
            tactical={'schema':'codm.tactical-markers/1','count':2,'status':'partial','complete':False,'sets':[]}
            with patch.object(c.source,'load'),patch.object(c.source,'file',return_value=scene),patch('codm_compiler.gameplay.extract_gameplay',return_value=(volumes,tactical)):
                report=c.run(['MP_Test_Atlases'],sidecars=['volumes','tactical'])
            self.assertFalse((Path(temp)/'spawns.json').exists())
            self.assertEqual(json.loads((Path(temp)/'gameplay_volumes.json').read_text()),volumes)
            self.assertEqual(json.loads((Path(temp)/'tactical_markers.json').read_text()),tactical)
            self.assertFalse(report['gameplayComplete'])
            self.assertEqual(read_extension(Path(temp)/'MP_Test_Atlases.c2m')['META']['gameplaySidecars']['tactical']['count'],2)


if __name__=='__main__':unittest.main()
