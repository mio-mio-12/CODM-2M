import unittest
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
from codm_compiler.gameplay import extract_gameplay

class GameplayAdditionTests(unittest.TestCase):
    def run_scene(self,kind,extra,children=()):
        objects={}
        def obj(i,typ,t):
            o=SimpleNamespace(path_id=i,type=SimpleNamespace(name=typ),assets_file=SimpleNamespace(name='test'),tree=t)
            objects[i]=o;return o
        ptr=lambda i:{'m_FileID':0,'m_PathID':i}
        obj(1,'MonoBehaviour',dict(m_GameObject=ptr(2),m_Script=ptr(99),script=kind,**extra))
        obj(2,'GameObject',{'m_Component':[{'component':ptr(3)}]})
        obj(3,'Transform',{'m_GameObject':ptr(2),'m_LocalPosition':{'x':10,'y':20,'z':30},'m_LocalRotation':{'w':1},'m_LocalScale':{'x':1,'y':1,'z':1}})
        for i,typ,t in children:obj(i,typ,t)
        class FakeSource:
            loaded=[]
            def __init__(self,*a):pass
            def load(self,p):pass
            def file(self,p):return SimpleNamespace(objects=objects)
            def tree(self,o):return o.tree
            def ref(self,o,p):return objects.get((p or {}).get('m_PathID'))
            def script_name(self,o,t):return t.get('script','')
        with patch('codm_compiler.gameplay.Source',FakeSource),patch('codm_compiler.gameplay.matching_scenes',return_value=[('p','n','map','mode')]):
            return extract_gameplay({},['map'],lambda _:None)

    def test_modifier_uses_authored_box_without_collider(self):
        v,t=self.run_scene('NavMeshModifierVolume',{'m_Size':{'x':2,'y':4,'z':6},'m_Center':{'x':1,'y':2,'z':3},'m_Area':17,'m_AffectedAgents':[-1]})
        self.assertTrue(v['complete']);i=v['sets'][0]['items'][0]
        self.assertFalse(i['solidCollision']);self.assertEqual(i['areaId'],17)
        np.testing.assert_allclose(np.mean(i['shapes'][0]['glbWorldCornersMetres'],axis=0),[-11,22,33])

    def test_climb_world_endpoints_and_height(self):
        ptr=lambda i:{'m_PathID':i}
        child=[(4,'GameObject',{'m_Component':[{'component':ptr(5)}]}),(5,'Transform',{'m_GameObject':ptr(4),'m_Father':ptr(3),'m_LocalPosition':{'x':2},'m_LocalRotation':{'w':1},'m_LocalScale':{'x':1,'y':1,'z':1}})]
        v,t=self.run_scene('ClimbSpot',{'startPoint':ptr(3),'endPoint':ptr(5),'height':2,'climbType':1},child)
        self.assertTrue(t['complete']);i=t['sets'][0]['items'][0]
        self.assertEqual(i['endpoints']['endPoint']['glbPositionMetres'],[-12,20,30]);self.assertAlmostEqual(i['height'],2/.0254)

    def test_missing_endpoint_reports_partial(self):
        v,t=self.run_scene('ClimbSpot',{'height':2})
        self.assertFalse(t['complete']);self.assertEqual(t['status'],'partial')

    def test_objective_auxiliary_trigger_cycle_and_duplicate(self):
        ptr=lambda i:{'m_PathID':i}
        children=[(4,'MonoBehaviour',{'m_GameObject':ptr(5),'AdditionalTriggers':[ptr(1)],'colliders':[ptr(7)]}),(5,'GameObject',{'m_Component':[{'component':ptr(6)},{'component':ptr(7)}]}),(6,'Transform',{'m_GameObject':ptr(5),'m_LocalPosition':{'x':4},'m_LocalRotation':{'w':1},'m_LocalScale':{'x':1,'y':1,'z':1}}),(7,'BoxCollider',{'m_GameObject':ptr(5),'m_Size':{'x':2,'y':2,'z':2}})]
        v,t=self.run_scene('HPObjectiveVolume',{'ObjectiveID':2,'AdditionalTriggers':[ptr(4),ptr(4)]},children)
        self.assertTrue(v['complete']);i=v['sets'][0]['items'][0]
        self.assertEqual(len(i['shapes']),1);self.assertEqual(i['shapes'][0]['glbPositionMetres'],[-4,0,0])

if __name__=='__main__':unittest.main()
