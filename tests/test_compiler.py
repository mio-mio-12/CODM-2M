import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np
from codm_compiler.geometry import bake,clip_projector
from codm_compiler.materials import atlas_rect
from codm_compiler.formats import write_c2m,read_extension,write_glb
from codm_compiler.catalog import scene_labels


def fixture():
    mesh={'name':'floor','vertices':np.array([[0,0,0],[0,0,1],[1,0,0]],dtype='<f4'),
          'normals':np.array([[0,1,0]]*3,dtype='<f4'),'faces':np.array([[0,1,2]],dtype='<u4'),
          'uv':np.array([[0,0],[0,1],[1,0]],dtype='<f4'),'colors':None,'uv1':None,'material':0}
    mat={'name':'floor','color':[1,1,1,1],'metallic':0.,'roughness':1.,'alpha':'OPAQUE','cutoff':.5,
         'doubleSided':False,'decal':False,'blend':'alpha','textures':{},'source':'test'}
    return mesh,mat


class GeometryTests(unittest.TestCase):
    def test_duplicate_tile_names_are_disambiguated(self):
        c={'maps':[{'name':'tile','path':'a.pak'},{'name':'tile','path':'b.pak'},{'name':'King','path':'c.pak'}]}
        self.assertEqual([label for label,_ in scene_labels(c)],['tile | a.pak','tile | b.pak','King'])
    def test_negative_scale_and_inverse_transpose(self):
        m=np.array([[-2,.4,0,5],[0,3,0,-7],[0,0,.5,11],[0,0,0,1.]])
        v,n,f=bake([[0,0,0],[0,0,1],[1,0,0]],[[0,1,0]]*3,[[0,1,2]],m)
        np.testing.assert_allclose(v[0],[-5,-7,11])
        face_n=np.cross(v[f[0,1]]-v[f[0,0]],v[f[0,2]]-v[f[0,0]])
        self.assertGreater(np.dot(face_n,n[0]),0)
        self.assertAlmostEqual(float(np.linalg.norm(n[0])),1.,places=6)

    def test_invalid_index_rejected(self):
        with self.assertRaises(ValueError):bake([[0,0,0]],None,[[0,1,2]],np.eye(4))

    def test_projector_clips_to_receivers(self):
        receiver={'vertices':np.array([[-2,-2,1],[2,-2,1],[0,2,1.]]),
                  'normals':np.array([[0,0,-1.]]*3),'faces':np.array([[0,1,2]])}
        out=clip_projector([receiver],np.eye(4),([-.5,-.5,0],[.5,.5,2]),offset=.001)
        self.assertGreater(len(out['faces']),0)
        self.assertTrue(np.all(np.abs(out['vertices'][:,:2])<=.500001))
        self.assertTrue(np.all((out['uv']>=0)&(out['uv']<=1)))
        np.testing.assert_allclose(out['vertices'][:,2],.999,atol=1e-6)

    def test_atlas_bitfields(self):
        self.assertEqual(atlas_rect(0x4c1),(.25,.75,.125,.125))
        code=(64<<15)|(32<<8)|(10<<4)|9
        self.assertEqual(atlas_rect(code,True),(.5,.25,.125,.0625))


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def create(self):
        m,mat=fixture();p=self.root/'test.c2m'
        coll=[{'id':'wall','kind':'BoxCollider','trigger':False,'center':[0,0,0],
               'size':[10,20,30],'matrix':np.eye(4).flatten(order='F').tolist()}]
        write_c2m(p,[m],[mat],coll,{'name':'test','collisionComplete':True},{'status':'settings_only','runtimeReady':False,'assets':[]})
        return p

    def test_collision_independent_of_visuals(self):
        p=self.create();d=read_extension(p)
        self.assertEqual(d['COLL']['colliders'][0]['size'],[10,20,30])
        self.assertEqual(d['META']['collisionPolicy'],'authored_only')
        self.assertFalse(d['NAVM']['runtimeReady'])
        b=p.read_bytes();self.assertEqual(b[:5],b'C2M\x03\xff')
        table=5+len(b'\x01test\0')+len(b'\x01\0')
        fields=struct.unpack_from('<IQIIQIQIQIQQ',b,table)
        self.assertEqual(fields[0],1);off=fields[1];off=b.index(b'\0',off+1)+1
        vertices,surfaces,faces,lods,distance=struct.unpack_from('<IIIIf',b,off)
        self.assertEqual((vertices,surfaces,faces,lods),(3,1,1,0))

    def test_corrupt_footer_rejected(self):
        p=self.create();b=bytearray(p.read_bytes());struct.pack_into('<Q',b,len(b)-24,2**63);p.write_bytes(b)
        with self.assertRaises(ValueError):read_extension(p)

    def test_overlapping_chunks_rejected(self):
        p=self.create();b=bytearray(p.read_bytes());directory=struct.unpack_from('<Q',b,len(b)-24)[0]
        start,length=struct.unpack_from('<QQ',b,directory+8)
        struct.pack_into('<QQ',b,directory+24+8,start,length)
        p.write_bytes(b)
        with self.assertRaises(ValueError):read_extension(p)

    def test_glb_has_no_collision_debug_geometry(self):
        m,mat=fixture();p=self.root/'test.glb';write_glb(p,[m],[mat],self.root)
        b=p.read_bytes();magic,version,total=struct.unpack_from('<4sII',b)
        self.assertEqual((magic,version,total),(b'glTF',2,len(b)))
        count=struct.unpack_from('<I',b,12)[0];j=json.loads(b[20:20+count])
        self.assertEqual(len(j['nodes']),1);self.assertEqual(len(j['meshes']),1)
        for view in j['bufferViews']:
            self.assertEqual(view['byteOffset']%4,0)
            self.assertLessEqual(view['byteOffset']+view['byteLength'],j['buffers'][0]['byteLength'])


if __name__=='__main__':unittest.main()
