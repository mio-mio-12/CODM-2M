import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
from codm_compiler.blending import evaluate,sample,bake_mesh,linear,srgb


class BlendTests(unittest.TestCase):
    def test_green_wetness_is_independent_of_albedo_layer_mask(self):
        s={k:np.tile(v,(4,1)) for k,v in {'_BaseTexture':[1,1,1,1],'_Albedo1':[1,1,1,1],
           '_Albedo2':[1,1,1,1],'_BaseNormal':[.5,.5,.2,1],'_Normal1':[.5,.5,.2,1]}.items()}
        c=np.array([[1,0,0,1],[1,1,0,1],[1,.25,.5,1],[1,.25,.5,1]])
        f={'_waterHeight':0,'_waterTrans':1,'_albedoMult':.2,'_smoothMult':3,
           '_BaseMetallic':.1,'_Metallic1':.1,'_metallicMult':2}
        # Below the water height: blue wetness=.5, union with green=.625.
        # Above the transition: blue contributes zero, green still contributes .25.
        h=np.array([2,2,-1,2])
        a,n,mr=evaluate(s,c,h,f,['_ALBEDO_VERTEX_R','_use_g_control_wet_ON'])
        wet=np.array([0,1,.625,.25])
        np.testing.assert_allclose(a[:,0],1-.8*wet)
        np.testing.assert_allclose(mr[:,1],1-.2*(1+2*wet))
        np.testing.assert_allclose(mr[:,2],.1*(1+wet))
        # Enabling green albedo with red=1 masks its layer, not its wetness.
        b,_,_=evaluate(s,c,h,f,['_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G','_use_g_control_wet_ON'])
        np.testing.assert_allclose(a,b)

    def test_shader_layer_order_and_mask(self):
        s={k:np.tile(v,(4,1)) for k,v in {'_BaseTexture':[1,0,0,1],'_Albedo1':[0,1,0,1],
           '_Albedo2':[0,0,1,1],'_BaseNormal':[.5,.5,.2,1],'_Normal1':[.5,.5,.8,1]}.items()}
        c=np.array([[0,0,0,1],[1,0,0,1],[0,1,0,1],[.5,.8,0,1]])
        a,n,mr=evaluate(s,c,np.ones(4),{},['_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G'])
        np.testing.assert_allclose(a,[[1,0,0],[0,1,0],[0,0,1],[.25,.25,.5]])
        np.testing.assert_allclose(np.linalg.norm(n,axis=1),1)
        np.testing.assert_allclose(mr[:2,1],[.8,.2])
        b,_,_=evaluate(s,c,np.ones(4),{'_MaskLayer2':1},['_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G'])
        np.testing.assert_allclose(b[-1],[.1,.1,.8])

    def test_repeat_and_color_space(self):
        im=np.array([[[1.,0,0],[0,1.,0]],[[0,0,1.],[1,1,1.]]])
        uv=np.array([[.25,.25],[1.25,-.75]])
        np.testing.assert_allclose(sample(im,uv,[1,1,0,0]),[[0,0,1],[0,0,1]])
        np.testing.assert_allclose(srgb(linear(np.array([0.,.03,.3,1.]))),[0,.03,.3,1],atol=1e-6)

    def test_bake_uses_interpolated_weights_and_separate_charts(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'images').mkdir()
            textures={}
            for slot,color in [('_BaseTexture',(255,0,0)),('_Albedo1',(0,255,0))]:
                path='images/'+slot+'.png';Image.new('RGB',(2,2),color).save(root/path)
                textures[slot]={'path':path,'srgb':True,'transform':[1,1,0,0]}
            mat={'name':'test','textures':{},'vertexBlend':{'floats':{},'keywords':['_ALBEDO_VERTEX_R'],'textures':textures}}
            mats=SimpleNamespace(items=[mat],output=root,max_texture=512)
            mesh={'name':'two','material':0,'extras':{},'vertices':np.array([[0,0,0],[1,0,0],[0,0,1.],[2,0,0],[3,0,0],[2,0,1.]]),
                  'normals':np.tile([0,1,0.],(6,1)),'faces':np.array([[0,1,2],[3,4,5]]),
                  'uv':np.tile([[0,0],[1,0],[0,1.]],(2,1)),'uv1':None,
                  'colors':np.array([[0,0,0,1],[1,0,0,1],[0,0,0,1],[1,0,0,1],[1,0,0,1],[1,0,0,1.]])}
            parts=bake_mesh(mesh,mats,0);self.assertEqual(sum(len(p['faces']) for p in parts),2)
            p=parts[0];self.assertIsNone(p['colors'])
            im=np.asarray(Image.open(root/mats.items[p['material']]['textures']['color']),dtype=float)/255
            for fi,expect in [(0,[2/3,1/3,0]),(1,[0,1,0])]:
                uv=p['uv'][p['faces'][fi]].mean(0);xy=np.rint(uv*[im.shape[1],im.shape[0]]-.5).astype(int)
                np.testing.assert_allclose(linear(im[xy[1],xy[0]]),expect,atol=.025)
            mesh['uv'][3:]=0
            fallback=bake_mesh(mesh,mats,0)
            self.assertEqual(sum(len(p['faces']) for p in fallback),2)
            self.assertEqual(sum(p['extras']['vertexBlendBake']['flatNormalCharts'] for p in fallback),1)
            json.dumps(mats.items,allow_nan=False)
            mat['vertexBlend']['keywords'].append('_use_g_control_wet_ON')
            mat['vertexBlend']['floats']['_use_g_control_wet_ON']=1
            wet_parts=bake_mesh(mesh,mats,0)
            self.assertEqual(sum(len(p['faces']) for p in wet_parts),2)


if __name__=='__main__':unittest.main()
