import numpy as np


def vector(d, keys="xyz", default=0):
    return np.array([d.get(k, default) for k in keys], dtype=np.float64)


def trs(t):
    x, y, z, w = vector(t.get("m_LocalRotation", {"w":1}), "xyzw")
    qlen = np.linalg.norm([x,y,z,w])
    if qlen < 1e-10:
        raise ValueError("Zero rotation quaternion")
    x,y,z,w = np.array([x,y,z,w])/qlen
    m = np.eye(4)
    m[:3,:3] = [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                  [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                  [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
    m[:3,:3] *= vector(t.get("m_LocalScale", {}), default=1)
    m[:3,3] = vector(t.get("m_LocalPosition", {}))
    return m


def bake(vertices, normals, indices, matrix):
    m = np.diag([-1.,1.,1.,1.]) @ matrix
    v = np.asarray(vertices, dtype=np.float64) @ m[:3,:3].T + m[:3,3]
    faces = np.asarray(indices, dtype=np.uint32).reshape(-1,3).copy()
    if len(faces) and int(faces.max()) >= len(v):
        raise ValueError("Mesh index out of bounds")
    if np.linalg.det(m[:3,:3]) < 0:
        faces = faces[:, [0,2,1]]
    if normals is not None and len(normals) == len(v):
        n = np.asarray(normals, dtype=np.float64) @ np.linalg.inv(m[:3,:3])
    else:
        n = np.zeros_like(v)
        fn = np.cross(v[faces[:,1]]-v[faces[:,0]],v[faces[:,2]]-v[faces[:,0]])
        for k in range(3):
            np.add.at(n, faces[:,k], fn)
    length = np.linalg.norm(n,axis=1,keepdims=True)
    n = n / np.maximum(length,1e-20)
    if not np.isfinite(v).all() or not np.isfinite(n).all():
        raise ValueError("Non-finite geometry")
    return v.astype('<f4'), n.astype('<f4'), faces.astype('<u4')


def compact(v, n, faces, uv=None, colors=None, uv1=None):
    used, remapped = np.unique(faces, return_inverse=True)
    return {"vertices":v[used], "normals":n[used], "faces":remapped.reshape(-1,3).astype('<u4'),
            "uv":None if uv is None else np.asarray(uv,dtype='<f4')[used,:2],
            "uv1":None if uv1 is None else np.asarray(uv1,dtype='<f4')[used,:2],
            "colors":None if colors is None else np.asarray(colors,dtype='<f4')[used]}


def bake_compact(vertices, normals, indices, matrix, uv=None, colors=None, uv1=None):
    vertices=np.asarray(vertices,dtype=np.float64)
    indices=np.asarray(indices,dtype=np.int64).reshape(-1,3)
    if indices.size and (indices.min()<0 or indices.max()>=len(vertices)):
        raise ValueError('Mesh index out of bounds')
    used,remapped=np.unique(indices,return_inverse=True)
    selected_normals=(np.asarray(normals,dtype=np.float64)[used]
                      if normals is not None and len(normals)==len(vertices) else None)
    v,n,f=bake(vertices[used],selected_normals,remapped.reshape(-1,3),matrix)
    return {'vertices':v,'normals':n,'faces':f,
            'uv':None if uv is None else np.asarray(uv,dtype='<f4')[used,:2],
            'uv1':None if uv1 is None else np.asarray(uv1,dtype='<f4')[used,:2],
            'colors':None if colors is None else np.asarray(colors,dtype='<f4')[used]}


def clip_projector(receivers, projector_world, bounds, offset=0.001):
    inverse = np.linalg.inv(projector_world)
    out_v, out_n, out_uv, out_f = [], [], [], []
    lo, hi = np.asarray(bounds[0]), np.asarray(bounds[1])
    for mesh in receivers:

        v = mesh['vertices'].astype(np.float64) * [-1,1,1]
        local = v @ inverse[:3,:3].T + inverse[:3,3]
        n = mesh['normals'].astype(np.float64)
        for face in mesh['faces']:
            p = local[face]
            if (p.max(0)<lo).any() or (p.min(0)>hi).any():
                continue
            poly = [np.r_[p[k], mesh['vertices'][face[k]], n[face[k]]] for k in range(3)]
            for axis in range(3):
                for bound, sign in ((lo[axis],1),(hi[axis],-1)):
                    old, poly = poly, []
                    if not old: break
                    for a,b in zip(old,old[1:]+old[:1]):
                        da,db = (a[axis]-bound)*sign,(b[axis]-bound)*sign
                        if da>=0: poly.append(a)
                        if (da>=0)!=(db>=0): poly.append(a+(b-a)*(da/(da-db)))
            if len(poly)<3: continue
            start=len(out_v)
            for p in poly:
                normal=p[6:9]/max(np.linalg.norm(p[6:9]),1e-20)
                out_v.append(p[3:6]+normal*offset);out_n.append(normal)
                out_uv.append([(p[0]-lo[0])/(hi[0]-lo[0]),1-(p[1]-lo[1])/(hi[1]-lo[1])])
            out_f.extend([[start,start+k,start+k+1] for k in range(1,len(poly)-1)])
    return {"vertices":np.asarray(out_v,dtype='<f4').reshape(-1,3), "normals":np.asarray(out_n,dtype='<f4').reshape(-1,3),
            "faces":np.asarray(out_f,dtype='<u4').reshape(-1,3), "uv":np.asarray(out_uv,dtype='<f4').reshape(-1,2),"colors":None,"uv1":None}
