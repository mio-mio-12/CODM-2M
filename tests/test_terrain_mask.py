import tempfile,unittest,json,os
from pathlib import Path
from unittest.mock import patch
import numpy as np
from codm_compiler.blending import evaluate_mask_terrain
from codm_compiler.catalog import scene_labels
from codm_compiler.source import Source
from codm_compiler.materials import Materials
class TerrainMaskTests(unittest.TestCase):
 def test_control_weights_and_pca_channels(self):
  images={'_Control':np.array([[[1,0,0,1],[0,0,0,1]]],dtype=np.float32)}
  for i in range(4):images[f'_Splat{i}']=np.array([[[.5,.5,.5,1]]],dtype=np.float32)
  recipe={'textures':{'_Control':{'transform':[1,1,0,0]},**{f'_Splat{i}':{'transform':[1,1,0,0]} for i in range(4)}},
          'controlWorldScale':1,'basis':{str(i):{'BasisX':[0,0,0],'BasisY':[0,0,0],'Offset':[.2*(i+1)]*3} for i in range(4)}}
  a=evaluate_mask_terrain(images,np.zeros((2,2)),np.array([[.25,0,.5],[.75,0,.5]]),recipe)
  np.testing.assert_allclose(a[:,0],[.04,.64],atol=1e-6)
 def test_real_azur_slots_and_static_seabottom_tint(self):
  catalog_path=Path(os.environ.get('CODM_TEST_CATALOG','outputs/codm-map-compiler/catalog.json'))
  if not catalog_path.is_file():self.skipTest('local CODM catalog unavailable')
  catalog=json.loads(catalog_path.read_text());m=next(m for n,m in scene_labels(catalog) if n=='GW_Azur_Final_Atlases')
  s=Source(catalog,lambda _:None);s.load(m['path']);f=s.file(m['node'])
  with tempfile.TemporaryDirectory() as d:
   mats=Materials(s,d,512)
   for oid in (11591,12544):
    o=f.objects[oid];t=s.tree(o);material=s.ref(o,t['m_Materials'][0]);item=mats.items[mats.get(material)]
    self.assertEqual(set(item['terrainMask']['textures']),{'_Control','_Splat0','_Splat1','_Splat2','_Splat3'})
    self.assertEqual(item['color'],[1,1,1,1])
   o=f.objects[13409];material=s.ref(o,s.tree(o)['m_Materials'][0]);item=mats.items[mats.get(material)]
   self.assertEqual(item['staticColorSource'],'_TintColor');self.assertLess(item['color'][0],.2)
   self.assertFalse(mats.failures)
