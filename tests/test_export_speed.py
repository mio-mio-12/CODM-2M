import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from codm_compiler.geometry import bake,compact,bake_compact
from codm_compiler.compiler import CODMMesh
from codm_compiler.source import Source


class ExportSpeedTests(unittest.TestCase):
    def test_selected_vertex_transform_matches_reference(self):
        rng=np.random.default_rng(513)
        vertices=rng.normal(size=(1000,3));normals=rng.normal(size=(1000,3))
        uv=rng.random((1000,2));colors=rng.random((1000,4));uv1=uv*2
        faces=np.array([[905,22,77],[22,77,418],[905,418,22]])
        for authored in (normals,None,np.zeros((2,3))):
            for sx in (-2,2):
                matrix=np.array([[sx,.2,0,4],[0,.5,.1,-3],[0,0,3,7],[0,0,0,1.]])
                v,n,f=bake(vertices,authored,faces,matrix)
                expected=compact(v,n,f,uv,colors,uv1)
                with patch('codm_compiler.geometry.bake',wraps=bake) as transform:
                    actual=bake_compact(vertices,authored,faces,matrix,uv,colors,uv1)
                self.assertEqual(len(transform.call_args.args[0]),4)
                for field in expected:np.testing.assert_allclose(actual[field],expected[field],atol=1e-6,rtol=1e-6)

    def test_selected_vertex_bounds_and_nonfinite_checks(self):
        with self.assertRaises(ValueError):bake_compact([[0,0,0]],None,[[0,1,2]],np.eye(4))
        with self.assertRaises(ValueError):bake_compact([[0,0,0]],None,[[0,-1,0]],np.eye(4))
        with self.assertRaises(ValueError):bake_compact([[float('nan'),0,0]],None,[[0,0,0]],np.eye(4))

    def test_triangles_are_decoded_once_per_mesh(self):
        h=object.__new__(CODMMesh);triangles=[[(0,1,2)],[(3,4,5)]]
        with patch('UnityPy.helpers.MeshHelper.MeshHandler.get_triangles',return_value=triangles) as decode:
            self.assertIs(h.get_triangles(),triangles)
            self.assertIs(h.get_triangles(),triangles)
            decode.assert_called_once()

    def test_type_attachment_visits_file_once_and_handles_environment_reset(self):
        class File:
            unity_version='5.6.4p4';visits=0
            def __init__(self):self.record=SimpleNamespace(node=None,class_id=1)
            @property
            def types(self):self.visits+=1;return [self.record]
        class Env:
            def __init__(self):self.assets=[]
            def load_file(self,path):self.assets.append(File())
        s=Source.__new__(Source);s.env=Env();s._typed_env=s.env;s._typed_files=set()
        s.loaded=set();s.type_nodes={1:object()};s.log=lambda _:None
        s.load('first');first=s.env.assets[0];s.load('second');s.load('second')
        self.assertEqual(first.visits,1);self.assertIs(first.record.node,s.type_nodes[1])
        s.env=Env();s.loaded.clear();s.load('first')
        self.assertEqual(len(s._typed_files),1);self.assertEqual(s.env.assets[0].visits,1)
