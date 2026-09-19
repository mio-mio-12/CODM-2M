import copy
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from PIL import Image
from codm_compiler.bake_session import BakeSession
from codm_compiler.blending import bake_mesh
from codm_compiler.gpu_baking import GPUBaker, GPUUnavailable, SLOTS


def fixture(root):
    rng=np.random.default_rng(781)
    (root/'images').mkdir(exist_ok=True)
    textures={}
    for slot in SLOTS:
        pixels=rng.integers(30,225,(17,23,4),dtype=np.uint8)
        path='images/'+slot+'.png';Image.fromarray(pixels).save(root/path)
        textures[slot]={'path':path,'srgb':slot not in ('_BaseNormal','_Normal1'),
                        'transform':[-1.3,2.1,.2,-.6]}
    uv=rng.uniform(-2,2,(60,2));uv[3:6]=.375
    colors=rng.uniform(0,1,(60,4))
    positions=rng.uniform(-1,1,(60,3))
    mesh={'name':'test','extras':{},'vertices':positions,'normals':np.tile([0.,1,0],(60,1)),
          'faces':np.arange(60).reshape(-1,3),'uv':uv,'uv1':uv.copy(),'colors':colors,'material':0}
    recipe={'textures':textures,'keywords':['_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G','_use_g_control_wet_ON'],
            'floats':{'_MaskLayer2':.45,'_SmoothnessScale2':.7,'_Smoothness2':.23,'_BumpScale':.72,
                      '_waterSmoothMult':.3,'_waterHeight':-.3,'_waterTrans':.8,'_albedoMult':.32,
                      '_smoothMult':2.5,'_metallicMult':1.2,'_BaseMetallic':.3,'_Metallic1':.7,'_Metallic2':.2}}
    return mesh,{'name':'test','textures':{},'vertexBlend':recipe}


def bake(root,mesh,mat,mode):
    session=BakeSession(mode,lambda _:None)
    materials=SimpleNamespace(items=[copy.deepcopy(mat)],output=root,max_texture=512,bake_session=session)
    try:
        parts=bake_mesh(mesh,materials,0)
        pixels=[[np.asarray(Image.open(root/materials.items[p['material']]['textures'][r])).copy()
                 for r in ('color','normal','metallic')] for p in parts]
        return parts,pixels,dict(session.stats)
    finally:session.close()


class GPUTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            gpu=GPUBaker();cls.renderer=gpu.renderer;gpu.close()
        except GPUUnavailable as e:
            if os.environ.get('CODM_REQUIRE_GPU'):raise
            raise unittest.SkipTest(str(e))

    def test_matches_cpu_all_pixels_gutters_layers_wetness_and_degenerate_uv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mesh,mat=fixture(root)
            for keys in [[],['_ALBEDO_VERTEX_R'],['_ALBEDO_VERTEX_G'],
                         ['_ALBEDO_VERTEX_R','_use_g_control_wet_ON'],
                         ['_ALBEDO_VERTEX_R','_ALBEDO_VERTEX_G','_use_g_control_wet_ON']]:
                with self.subTest(keywords=keys):
                    mat['vertexBlend']['keywords']=keys
                    cpu,expected,_=bake(root,mesh,mat,'cpu')
                    gpu,actual,stats=bake(root,mesh,mat,'auto')
                    self.assertGreater(stats['gpuPages'],0,stats)
                    self.assertEqual(stats['cpuPages'],0,stats)
                    self.assertIsNone(stats['fallbackReason'])
                    self.assertEqual(len(cpu),len(gpu))
                    for a,b in zip(cpu,gpu):
                        for field in ('vertices','normals','faces','uv','uv1'):
                            np.testing.assert_array_equal(a[field],b[field])
                    for page,want in zip(actual,expected):
                        for a,b in zip(page,want):
                            difference=np.abs(a.astype(int)-b.astype(int))
                            self.assertLessEqual(difference.max(),2)
                            self.assertLess(difference.mean(),.02)

    def test_missing_layers_use_reference_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mesh,mat=fixture(root);mat['vertexBlend']['textures']={}
            _,expected,_=bake(root,mesh,mat,'cpu');_,actual,stats=bake(root,mesh,mat,'auto')
            self.assertGreater(stats['gpuPages'],0,stats)
            for page,want in zip(actual,expected):
                for a,b in zip(page,want):self.assertLessEqual(np.abs(a.astype(int)-b.astype(int)).max(),1)


class FallbackTests(unittest.TestCase):
    def test_lost_context_still_destroys_window(self):
        from unittest.mock import Mock
        gpu=GPUBaker.__new__(GPUBaker)
        gpu.window=object();window=gpu.window;gpu.glfw=Mock();gpu.gl=Mock();gpu.program=1
        gpu.release_surface=Mock(side_effect=RuntimeError('context lost'))
        gpu.close()
        gpu.glfw.destroy_window.assert_called_once_with(window)
        gpu.glfw.terminate.assert_called_once()
        self.assertIsNone(gpu.window)

    def test_initialization_failure_falls_back_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mesh,mat=fixture(root)
            with patch('codm_compiler.gpu_baking.GPUBaker',side_effect=GPUUnavailable('test unavailable')) as init:
                _,actual,stats=bake(root,mesh,mat,'auto')
            self.assertEqual(init.call_count,1);self.assertGreater(stats['cpuPages'],0)
            self.assertEqual(stats['gpuPages'],0);self.assertIn('test unavailable',stats['fallbackReason'])
            _,expected,_=bake(root,mesh,mat,'cpu')
            for page,want in zip(actual,expected):
                for a,b in zip(page,want):np.testing.assert_array_equal(a,b)

    def test_page_failure_rebakes_whole_page_and_releases_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);mesh,mat=fixture(root)
            with patch('codm_compiler.gpu_baking.GPUBaker') as init:
                init.return_value.renderer='test';init.return_value.page.side_effect=RuntimeError('test allocation failure')
                _,actual,stats=bake(root,mesh,mat,'auto')
                init.return_value.close.assert_called_once()
                init.return_value.page.assert_called_once()
            self.assertGreater(stats['cpuPages'],0);self.assertEqual(stats['gpuPages'],0)
            _,expected,_=bake(root,mesh,mat,'cpu')
            for page,want in zip(actual,expected):
                for a,b in zip(page,want):np.testing.assert_array_equal(a,b)


class ExportSpeedTests(unittest.TestCase):
    def test_glb_omits_unused_materials_without_changing_source_indices(self):
        from codm_compiler.formats import write_glb
        from test_compiler import fixture as visual_fixture
        mesh,mat=visual_fixture();mesh['material']=1
        unused={**mat,'textures':{'color':'does-not-exist.png'}}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'test.glb';write_glb(out,[mesh],[unused,mat],tmp)
            data=out.read_bytes();length=struct.unpack_from('<I',data,12)[0]
            doc=json.loads(data[20:20+length])
            self.assertEqual(len(doc['materials']),1)
            self.assertEqual(doc['meshes'][0]['primitives'][0]['material'],0)
            self.assertEqual(mesh['material'],1)
