import unittest
import numpy as np
from codm_compiler.gameplay import shape_data,pose,BASIS
from codm_compiler.geometry import trs


class GameplayTests(unittest.TestCase):
    def test_box_preserves_rotated_mirrored_shape_and_units(self):
        m=trs({'m_LocalRotation':{'y':.7071067811865475,'w':.7071067811865475},
               'm_LocalPosition':{'x':10,'y':20,'z':30},'m_LocalScale':{'x':-2,'y':3,'z':4}})
        t={'m_Center':{'x':1,'y':2,'z':3},'m_Size':{'x':2,'y':4,'z':6},'m_IsTrigger':True}
        shape=shape_data('BoxCollider',t,m)
        corners=np.array(shape['worldCorners']);glb=np.array(shape['glbWorldCornersMetres'])
        np.testing.assert_allclose(corners,glb[:,[0,2,1]]*[1,-1,1]/.0254)
        cm=np.array(shape['matrix']).reshape(4,4,order='F')
        center=np.array(shape['center'])
        np.testing.assert_allclose(corners.mean(0),cm[:3,:3]@center+cm[:3,3])
        self.assertTrue(shape['trigger'])
        self.assertLess(np.linalg.det(cm[:3,:3]),0)

    def test_pose_does_not_mutate_scale(self):
        m=np.diag([2.,3,4,1]);before=m.copy();p=pose(m)
        np.testing.assert_array_equal(m,before)
        self.assertAlmostEqual(np.linalg.norm(p['forward']),1)

    def test_capsule_axis_and_scale_policy(self):
        s=shape_data('CapsuleCollider',{'m_Radius':.5,'m_Height':2,'m_Direction':1},np.eye(4))
        self.assertEqual(s['axis'],2);self.assertEqual(s['glbAxis'],1)
        self.assertAlmostEqual(s['radius'],.5/.0254)
        self.assertEqual(s['scalePolicy'],'unity_axis_height_max_perpendicular_radius')

    def test_unknown_shapes_and_nonfinite_transforms_are_rejected(self):
        with self.assertRaises(ValueError):shape_data('MeshCollider',{},np.eye(4))
        m=np.eye(4);m[0,3]=float('nan')
        with self.assertRaises(ValueError):pose(m)


if __name__=='__main__':unittest.main()
