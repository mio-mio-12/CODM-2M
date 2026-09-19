import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from codm_compiler.materials import Materials,visible_pass_state
from codm_compiler.formats import GLB
from codm_compiler.blending import linear


class MaterialTests(unittest.TestCase):
    def convert(self,root,shader,tags=(),keywords='',state=None,floats=(),colors=()):
        tree={'m_Name':'fixture','m_Shader':1,'m_ShaderKeywords':keywords,
              'm_CustomRenderQueue':2450,'stringTagMap':list(tags),
              'm_SavedProperties':{'m_Floats':[('_Mode',-1),('_SrcBlend',1),('_DstBlend',0),('_cull',0)],
                  'm_Colors':[('_EmissionColor',dict(r=1,g=1,b=1,a=1))],
                  'm_TexEnvs':[('_MainTex',{'m_Texture':{'m_PathID':1}})]}}
        tree['m_SavedProperties']['m_Floats']+=list(floats)
        tree['m_SavedProperties']['m_Colors']+=list(colors)
        sh={'m_Name':shader,'m_ParsedForm':{'m_SubShaders':[{'m_Passes':[{'m_State':state or {}}]}]}}
        texture=SimpleNamespace(type=SimpleNamespace(name='Texture2D'))
        source=SimpleNamespace(warnings=[],tree=lambda obj:tree if obj=='material' else sh,
                               ref=lambda obj,ptr:'shader' if obj=='material' and ptr==1 else texture)
        mats=Materials(source,root)
        Image.fromarray(np.array([[[0,0,0,255],[128,64,0,255],[255,255,255,0]]],dtype=np.uint8)).save(root/'images/source.png')
        with patch('codm_compiler.materials.key',return_value='test'),patch.object(mats,'texture',return_value='images/source.png'):
            idx=mats.get('material')
        return mats.items[idx]

    def test_cutout_tags_and_foliage_keywords(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for tags,keywords in [([('RenderType','TransparentCutout')],''),([], '_STATIC_FOLIAGE')]:
                m=self.convert(root,'CODStandard Foliage',tags,keywords)
                g=GLB();g.material(m,root)
                self.assertEqual(g.doc['materials'][0]['alphaMode'],'MASK')
                self.assertEqual(g.doc['materials'][0]['alphaCutoff'],.5)
                self.assertTrue(g.doc['materials'][0]['doubleSided'])

    def test_screen_artwork_does_not_add_white_emission(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);m=self.convert(root,'CODM/FX/CodmKGTVScreen')
            g=GLB();g.material(m,root);out=g.doc['materials'][0]
            self.assertEqual(out['alphaMode'],'OPAQUE')
            self.assertNotIn('emissiveFactor',out)
            self.assertIn('KHR_materials_unlit',out['extensions'])

    def test_shader_additive_state_overrides_stale_material_properties(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'rtBlend0':{'srcBlend':{'val':5},'destBlend':{'val':1}},'culling':{'val':0}}
            m=self.convert(root,'CODM/FX/TVScanLineAdd',state=state)
            self.assertEqual((m['srcBlend'],m['dstBlend'],m['blend']),(5,1,'additive'))
            self.assertEqual(m['textures']['color'],'images/source.png')
            self.assertNotEqual(m['glbColorTexture'],m['textures']['color'])
            rgba=np.asarray(Image.open(root/m['glbColorTexture']),dtype=float)/255
            self.assertEqual(rgba[0,0,3],0);self.assertEqual(rgba[0,2,3],0)
            np.testing.assert_allclose(linear(rgba[0,1,:3])*rgba[0,1,3],linear(np.array([128,64,0])/255),atol=.003)
            g=GLB();g.material(m,root)
            self.assertEqual(g.doc['materials'][0]['alphaMode'],'BLEND')
            self.assertTrue(g.doc['images'][0]['name'].startswith('additive_preview_'))

    def test_generic_additive_shader_without_name_heuristics(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for source_factor in (1,5):
                state={'rtBlend0':{'srcBlend':{'val':source_factor},'destBlend':{'val':1}},'culling':{'val':0}}
                m=self.convert(root,'Arbitrary/Effect/Shader',state=state)
                self.assertEqual(m['blend'],'additive');self.assertTrue(m['unlit'])
                rgba=np.asarray(Image.open(root/m['glbColorTexture']))
                self.assertEqual(rgba[0,0,3],0)
                self.assertEqual(rgba[0,2,3],255 if source_factor==1 else 0)
                self.assertTrue(0<rgba[0,1,3]<255)
                self.assertEqual(m['textures']['color'],'images/source.png')

    def test_particle_tint_and_brightness_are_included_once(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'rtBlend0':{'srcBlend':{'val':5},'destBlend':{'val':1}}}
            m=self.convert(root,'Arbitrary/Shader',state=state,floats=[('_Brightness',.3)],
                           colors=[('_TintColor',dict(r=.4,g=.6,b=.8,a=.25))])
            rgba=np.asarray(Image.open(root/m['glbColorTexture']),dtype=float)/255
            expected=linear(np.array([128,64,0])/255)*[.4,.6,.8]*.3*.25
            np.testing.assert_allclose(linear(rgba[0,1,:3])*rgba[0,1,3],expected,atol=.002)
            self.assertEqual(m['glbColorFactor'],[1,1,1,1]);self.assertEqual(m['emissive'],[0,0,0])

    def test_opaque_and_cutout_black_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'rtBlend0':{'srcBlend':{'val':1},'destBlend':{'val':0}}}
            for shader,keywords,alpha in [('Effects/AdditiveNamedButOpaque','','OPAQUE'),
                                           ('CODStandard Foliage','_STATIC_FOLIAGE','MASK')]:
                m=self.convert(root,shader,keywords=keywords,state=state)
                self.assertEqual(m['blend'],'alpha');self.assertEqual(m['alpha'],alpha)
                self.assertNotIn('glbColorTexture',m)
                self.assertEqual(np.asarray(Image.open(root/m['textures']['color']))[0,0,3],255)

    def test_pass_selection_and_named_shader_properties(self):
        def p(name,mode,src,dst,mask=15):
            return {'m_State':{'m_Name':name,'m_Tags':{'tags':[['LIGHTMODE',mode]]},
                    'rtBlend0':{'srcBlend':src,'destBlend':dst,'colMask':{'val':mask}},
                    'culling':{'name':'_CullMode','val':2}}}
        shader={'m_ParsedForm':{'m_PropInfo':{'m_Props':[{'m_Name':'_From','m_DefValue':[5,0,0,0]}]},
                'm_SubShaders':[{'m_Passes':[p('shadow','ShadowCaster',{'val':1},{'val':0}),
                 p('disabled','ForwardBase',{'val':1},{'val':0}),p('depth','',{'val':1},{'val':0},0),
                 p('visible','ForwardBase',{'name':'_From','val':0},{'name':'_To','val':0})]},
                 {'m_Passes':[p('fallback','',{'val':1},{'val':10})]}]}}
        st=visible_pass_state(shader,{'disabledShaderPasses':['disabled']},{'_To':1,'_CullMode':0})
        self.assertEqual((st['pass'],st['srcBlend'],st['dstBlend'],st['cull']),('visible',5,1,0))
        st=visible_pass_state(shader,{'disabledShaderPasses':['disabled']},{'_CullMode':0})
        self.assertNotIn('dstBlend',st)

    def test_additive_atlas_preview_uses_cropped_tile(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state={'rtBlend0':{'srcBlend':{'val':1},'destBlend':{'val':1}}}
            m=self.convert(root,'Arbitrary/Shader',state=state)
            atlas=np.zeros((64,64,4),dtype=np.uint8);atlas[:,:,3]=255;atlas[-4:,:4,:3]=[0,0,255]
            Image.fromarray(atlas).save(root/'images/atlas.png')
            m['textures']['color']='images/atlas.png'
            m['atlas']={'new':False,'transforms':{'_MainTex_AtlasTrans':[0]}}
            mats=Materials(SimpleNamespace(),root);mats.items=[m]
            variant=mats.items[mats.atlas_variant(0,0)]
            image=np.asarray(Image.open(root/variant['glbColorTexture']))
            self.assertEqual(image.shape,(4,4,4))
            np.testing.assert_array_equal(image,np.tile([0,0,255,255],(4,4,1)))
            self.assertEqual(variant['additivePreview']['sourceTexture'],variant['textures']['color'])


if __name__=='__main__':unittest.main()
