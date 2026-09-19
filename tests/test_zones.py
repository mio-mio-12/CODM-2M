import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from codm_compiler.zones import grid,plan,build_index,world_scenes
from codm_compiler.imgui_ui import BrowserState

def fixture():
    chunks=[{'id':'a','name':'Big','layer':'Obj_Big','layerName':'Large structures','bounds':[-100,0,250,150],
             'scene':'Big_0_0_0','status':'available'},
            {'id':'b','name':'Col','layer':'Physics','layerName':'Collision','bounds':[0,0,200,200],
             'scene':'Col_0_0_0','status':'available'}]
    return {'world':'BR_Test_Main','title':'Test','signature':'abc','layers':{'Obj_Big':'Large structures','Physics':'Collision'},
            'chunks':chunks,'cells':grid(chunks),'errors':[]}

class ZoneTests(unittest.TestCase):
    def test_grid_negative_coordinates_and_exact_boundary(self):
        data=fixture();self.assertEqual({c['id'] for c in data['cells']},{'-1:0','0:0','1:0'})
        self.assertEqual([c['name'] for c in data['cells']],['A1','B1','C1'])
        with self.assertRaises(ValueError):grid([{'bounds':[0,0,1e20,1e20]}])

    def test_intersection_whole_chunks_deduplicated_and_layers_filtered(self):
        data=fixture();data['chunks'].append(dict(data['chunks'][0],id='a-copy'))
        p=plan(data,['-1:0','0:0'],['Obj_Big'],'Town')
        self.assertEqual([c['scene'] for c in p['chunks']],['Big_0_0_0'])
        self.assertEqual(len(plan(data,['1:0'],['Physics'],'Edge')['chunks']),0)
        data['chunks'][0]['disabledInSource']=True;data['chunks'].pop()
        self.assertEqual(plan(data,['0:0'],['Obj_Big'],'Off')['chunks'],[])
        with self.assertRaises(ValueError):plan(data,['bad'],['Physics'],'Stale')

    def test_authored_bounds_lod_and_world_identity(self):
        maps=[{'name':'BR_Test_Main','path':'_s_br$br_test_runtime$main.pak','node':'main'},
              {'name':'Big_0_0_0','path':'_s_br$br_test_runtime$tiledscene$big$chunk.pak','node':'chunk'},
              {'name':'Big_0_0_0','path':'_s_br$br_other_runtime$tiledscene$big$chunk.pak','node':'other'}]
        c={'maps':maps,'bundles':[]};self.assertEqual(list(world_scenes(c)),['BR_Test_Main'])
        obj=SimpleNamespace(type=SimpleNamespace(name='MonoBehaviour'),path_id=1,assets_file=SimpleNamespace(name='main'))
        b={'m_Center':{'x':30,'z':-40},'m_Extent':{'x':10,'z':20}}
        tree={'streamingLayers':[{'baseScenePath':'Assets/Obj_Big','layerInfo':{},'streamingScenes':[
            {'sceneLODs':[{'sceneName':'Far','lodIndex':2},{'sceneName':'Big_0_0_0','lodIndex':0}],
             'compactBounds':b,'streamingBounds':b}]}]}
        s=Mock();s.file.return_value=SimpleNamespace(objects={1:obj});s.tree.return_value=tree;s.script_name.return_value='TiledSceneStreamer'
        with patch('codm_compiler.zones.Source',return_value=s):r=build_index(c,'BR_Test_Main',lambda _:None)
        self.assertEqual(r['chunks'][0]['bounds'],[20,-60,40,-20]);self.assertEqual(r['chunks'][0]['lod'],0)
        self.assertEqual(r['chunks'][0]['status'],'available');self.assertIn('chunk.pak',r['chunks'][0]['scene'])

    def state(self,d):
        s=BrowserState(d);s.catalog={'root':d};s.source=d;s.output=str(Path(d)/'out');s.zone_index=fixture()
        s.zone_cells={'0:0'};s.zone_layers={'Obj_Big','Physics'}
        def start(job):
            self.assertIsNone(s.process)
            s.job=Path(d)/('job'+str(len(list(Path(d).glob('job*'))))+'.json');s.job.write_text(json.dumps(job))
            s.process=Mock();s.process.poll.return_value=None;s.started=0;s.status='Exporting'
        s.start=Mock(side_effect=start)
        return s

    def test_queue_is_serial_presets_and_completed_chunks_survive_cancel(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.state(d);s.save_zone();self.assertTrue((Path(d)/'zones/presets.json').is_file())
            s.export_zone();self.assertEqual(s.start.call_count,1)
            self.assertTrue(all(c['status']=='available' for c in s.zone_index['chunks']))
            s.job.with_suffix('.result.json').write_text(json.dumps({'status':'Complete','counts':{'triangles':12}}))
            s.process.poll.return_value=0;s.poll();self.assertEqual(s.start.call_count,2)
            s.cancel();self.assertIsNone(s.process);self.assertEqual(s.zone_queue,[])
            result=json.loads((s.zone_out/'zone.json').read_text())
            self.assertEqual(result['status'],'Cancelled');self.assertEqual(result['chunks'][0]['status'],'Complete')
            self.assertEqual(result['chunks'][1]['status'],'Cancelled')

    def test_queue_records_failure_and_continues(self):
        with tempfile.TemporaryDirectory() as d:
            s=self.state(d);s.export_zone()
            s.job.with_suffix('.result.json').write_text(json.dumps({'status':'Error','error':'unsupported'}))
            s.process.poll.return_value=1;s.poll()
            s.job.with_suffix('.result.json').write_text(json.dumps({'status':'Complete','counts':{'colliders':3}}))
            s.process.poll.return_value=0;s.poll()
            self.assertEqual(s.status,'Partial');self.assertIsNone(s.zone_current)
            self.assertEqual(s.zone_manifest['chunks'][0]['error'],'unsupported')
