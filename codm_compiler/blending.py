import copy
import hashlib
import math
import time
from pathlib import Path
import numpy as np
from PIL import Image

SHADER = 'CODM/Terrain/3Tex_VertexBlend_NormSpecRealtime'


def linear(c):
    return np.where(c <= .04045, c / 12.92, ((c + .055) / 1.055) ** 2.4)


def srgb(c):
    c = np.maximum(c, 0)
    return np.where(c <= .0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - .055)


def sample(image, uv, transform):
    q = uv * transform[:2] + transform[2:]
    q = np.stack((q[:, 0], 1 - q[:, 1]), axis=1)
    h, w = image.shape[:2]
    p = q * [w, h] - .5
    ij = np.floor(p).astype(np.int64); f = p - ij
    x, y = ij[:, 0] % w, ij[:, 1] % h
    nx, ny = (x + 1) % w, (y + 1) % h
    a = image[y, x] * (1-f[:, :1]) + image[y, nx] * f[:, :1]
    b = image[ny, x] * (1-f[:, :1]) + image[ny, nx] * f[:, :1]
    return a * (1-f[:, 1:]) + b * f[:, 1:]


def evaluate(samples, colors, height, floats, keywords):
    r = colors[:, 0:1] if '_ALBEDO_VERTEX_R' in keywords else np.zeros_like(colors[:, :1])
    g = colors[:, 1:2] if '_ALBEDO_VERTEX_G' in keywords else np.zeros_like(r)
    r = np.clip(r, 0, 1)
    g = np.minimum(np.clip(g, 0, 1), 1-r*(1-floats.get('_MaskLayer2', 0)))
    base, first, second = (samples[k] for k in ('_BaseTexture', '_Albedo1', '_Albedo2'))
    albedo = (base[:, :3]*(1-r) + first[:, :3]*r)*(1-g) + second[:, :3]*g
    packed = samples['_BaseNormal'][:, :3]*(1-r) + samples['_Normal1'][:, :3]*r
    smooth = packed[:, 2:3] + g*floats.get('_SmoothnessScale2', 0)*(floats.get('_Smoothness2', .1)-packed[:, 2:3])
    xy = packed[:, :2] + np.clip(g*floats.get('_waterSmoothMult', 1), 0, 1)*(.5-packed[:, :2])
    xy = (xy*2-1)*floats.get('_BumpScale', 1)
    normal = np.concatenate((xy, np.sqrt(np.maximum(0, 1-(xy*xy).sum(axis=1, keepdims=True)))), axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)

    metallic = floats.get('_BaseMetallic', 0)*(1-r) + floats.get('_Metallic1', .3)*r
    metallic = metallic*(1-g) + floats.get('_Metallic2', .3)*g
    h = np.clip((height[:, None]-floats.get('_waterHeight', -100))/max(floats.get('_waterTrans', 0), .01), 0, 1)
    wet = (1-h*h*(3-2*h))*colors[:, 2:3]
    if '_use_g_control_wet_ON' in keywords:


        green = np.clip(colors[:, 1:2], 0, 1)
        wet = wet + green*(1-wet)
    albedo *= 1+wet*(floats.get('_albedoMult', .2)-1)
    smooth *= 1+wet*(floats.get('_smoothMult', 3)-1)
    metallic *= 1+wet*(floats.get('_metallicMult', 1)-1)
    mr = np.concatenate((np.ones_like(smooth), 1-np.clip(smooth, 0, 1), np.clip(metallic, 0, 1)), axis=1)
    return albedo, normal, mr


def evaluate_mask_terrain(images, uv, world, recipe):
    control=recipe['textures']['_Control']
    world_uv=world[:,[0,2]]*recipe['controlWorldScale']
    mask=sample(images['_Control'],world_uv,control['transform'])[:,:3]
    leftover=np.maximum(1-mask.sum(axis=1,keepdims=True),0)
    weights=np.concatenate((mask,leftover),axis=1)
    weights/=np.maximum(weights.sum(axis=1,keepdims=True),1e-12)
    albedo=np.zeros((len(uv),3),dtype=np.float32)
    for i in range(4):
        packed=sample(images[f'_Splat{i}'],uv,recipe['textures'][f'_Splat{i}']['transform'])
        basis=recipe['basis'][str(i)]


        decoded=(np.asarray(basis['BasisX'])*(packed[:,2:3]*2-1)
                 +np.asarray(basis['BasisY'])*(packed[:,1:2]*2-1)
                 +np.asarray(basis['Offset']))**2
        albedo+=decoded*weights[:,i:i+1]
    return np.clip(albedo,0,1)


def bake_mesh(mesh, materials, index):
    session=getattr(materials,'bake_session',None)
    started=time.perf_counter()
    try:return _bake_mesh(mesh,materials,index)
    finally:
        if session:
            session.stats['seconds']+=time.perf_counter()-started
            if session.gpu:session.gpu.release_surface()


def _bake_mesh(mesh, materials, index):
    terrain='terrainMask' in materials.items[index]
    recipe = materials.items[index].get('terrainMask') or materials.items[index]['vertexBlend']
    uv, colors = mesh['uv'], mesh['colors']
    if uv is None or (colors is None and not terrain):
        raise ValueError('Vertex-blended surface requires source UV0 and vertex RGBA')
    if not terrain and recipe['floats'].get('_HeightBlend', 0):
        raise ValueError('Terrain height-blend variant is not yet decoded')
    root = materials.output
    images = {}
    for slot, entry in recipe['textures'].items():
        image = np.asarray(Image.open(root/entry['path']).convert('RGBA'), dtype=np.float32)/255
        if entry.get('srgb'):image[:, :, :3] = linear(image[:, :, :3])
        images[slot] = image
    session=getattr(materials,'bake_session',None)
    gpu=session.prepare(images,recipe) if session and not terrain else None
    chart_started=time.perf_counter()
    page_size = max(512, materials.max_texture or 4096)
    pad = 8; density = 64
    charts = []
    for face in mesh['faces']:
        u = uv[face].astype(np.float64); p = mesh['vertices'][face].astype(np.float64)
        delta = np.stack((u[1]-u[0], u[2]-u[0]))
        degenerate=abs(np.linalg.det(delta)) < 1e-12
        if degenerate:


            edge=p[1]-p[0];length=np.linalg.norm(edge)
            axis=edge/max(length,1e-12);ac=p[2]-p[0]
            along=np.dot(ac,axis);across=np.linalg.norm(ac-along*axis)
            u=np.array([[0.,0.],[max(length,.001),0.],[along,max(across,.001)]])
            delta=np.stack((u[1]-u[0],u[2]-u[0]))
        deriv = np.linalg.solve(delta, np.stack((p[1]-p[0], p[2]-p[0])))
        lo, hi = u.min(0), u.max(0)
        size = np.maximum(2, np.ceil((hi-lo)*np.linalg.norm(deriv, axis=1)*density).astype(int))
        scale = min(1., (page_size-2*pad-1)/max(size))
        size = np.maximum(2, np.floor(size*scale).astype(int))
        charts.append((face, lo, hi, size, scale, u, degenerate))


    cost=sum(np.prod(c[3]+2*pad+1) for c in charts)
    budget=8*page_size*page_size
    budget_scale=min(1.,math.sqrt(budget/max(cost,1)))
    if budget_scale<1:
        charts=[(f,lo,hi,np.maximum(2,np.floor(sz*budget_scale).astype(int)),sc*budget_scale,u,dg)
                for f,lo,hi,sz,sc,u,dg in charts]
    charts.sort(key=lambda x: -int(x[3][1]))
    pages=[]; current=[]; x=y=row=0
    for chart in charts:
        w,h = chart[3]+2*pad+1
        if x+w>page_size:x=0;y+=row;row=0
        if y+h>page_size:
            pages.append(current);current=[];x=y=row=0
        current.append((chart,x,y));x+=w;row=max(row,h)
    if current:pages.append(current)
    token=hashlib.sha256((mesh['name']+repr(mesh['extras'])+str(index)).encode()).hexdigest()[:12]

    source_dir=root/'source_layers';source_dir.mkdir(exist_ok=True)
    np.savez_compressed(source_dir/(token+'.npz'), uv0=uv,
                        vertexRGBA=colors if colors is not None else np.empty((0,4)), faces=mesh['faces'])
    if session:session.stats['chartSeconds']+=time.perf_counter()-chart_started
    parts=[]
    for page, entries in enumerate(pages):
        width=max(x+int(c[3][0])+2*pad+1 for c,x,y in entries)
        height=max(y+int(c[3][1])+2*pad+1 for c,x,y in entries)
        paths=[root/f'images/blend_{token}_{page}_{role}.png' for role in ('color','normal','metallic')]

        reuse=getattr(materials,'reuse_existing_bakes',False) and all(p.exists() for p in paths)
        if reuse:
            for path in paths:
                with Image.open(path) as im:
                    if im.size!=(width,height):reuse=False
        pixel_started=time.perf_counter()
        buffers=[];backend='reused' if reuse else 'cpu'
        if not reuse and gpu:
            try:
                buffers=gpu.page(mesh,entries,width,height,pad);backend='gpu'
            except Exception as e:
                session.fallback(e);gpu=None
        if not reuse and not buffers:buffers=[np.zeros((height,width,3),dtype=np.uint8) for _ in range(3)]
        vertex_indices=np.asarray([c[0] for c,x,y in entries]).reshape(-1)
        vertices=mesh['vertices'][vertex_indices];normals=mesh['normals'][vertex_indices]
        uv1=mesh['uv1'][vertex_indices] if mesh['uv1'] is not None else None
        out_uv=[]
        for (face,lo,hi,size,scale,u,degenerate),x,y in entries:
            w,h=size
            if not reuse and backend=='cpu':

                xx,yy=np.meshgrid(np.arange(w+2*pad+1),np.arange(h+2*pad+1))
                q=lo+np.stack(((xx-pad)/w,(yy-pad)/h),axis=-1).reshape(-1,2)*(hi-lo)
                bc12=(q-u[0])@np.linalg.inv(np.stack((u[1]-u[0],u[2]-u[0])))
                bc=np.column_stack((1-bc12.sum(1),bc12))
                bc=np.maximum(bc,0);bc/=bc.sum(1,keepdims=True)
                source_uv=bc@uv[face];pos=bc@mesh['vertices'][face]
                if terrain:
                    world=pos*[-1,1,1]
                    a=evaluate_mask_terrain(images,source_uv,world,recipe)
                    n=np.broadcast_to([0,0,1],(len(q),3))
                    mr=np.broadcast_to([1,.7,0],(len(q),3))
                else:
                    rgba=bc@colors[face];samples={}
                    for slot,entry in recipe['textures'].items():
                        samples[slot]=sample(images[slot],source_uv,entry['transform'])
                    for slot,default in (('_BaseTexture',[0,0,0,1]),('_Albedo1',[1,1,1,1]),('_Albedo2',[1,1,1,1]),('_BaseNormal',[.5,.5,1,1]),('_Normal1',[.5,.5,1,1])):
                        if slot not in samples:samples[slot]=np.broadcast_to(default,(len(q),4))
                    a,n,mr=evaluate(samples,rgba,pos[:,1],recipe['floats'],recipe['keywords'])
                    if degenerate:n[:]=[0,0,1]
                values=(srgb(a),n*.5+.5,mr)
                for target,value in zip(buffers,values):
                    target[y:y+h+2*pad+1,x:x+w+2*pad+1]=np.rint(np.clip(value,0,1)*255).astype(np.uint8).reshape(h+2*pad+1,w+2*pad+1,3)

            atlas_uv=((u-lo)/(hi-lo)*size+[x+pad+.5,y+pad+.5])/[width,height]
            out_uv.append(atlas_uv)
        if session:
            session.stats['pixelSeconds']+=time.perf_counter()-pixel_started
            if backend in ('cpu','gpu'):session.stats[backend+'Pages']+=1
        variant=copy.deepcopy(materials.items[index]);variant['name']+=f'_baked_{token}_{page}'
        variant.update(color=[1,1,1,1],metallic=1.,roughness=1.,uv_scale=[1,1],uv_offset=[0,0],textures={})
        bake_info={'method':'triangle_charts','backend':backend,'targetTexelsPerMetre':density,'gutterPixels':pad,
                   'sourceAttributes':f'source_layers/{token}.npz','limitedCharts':int(sum(c[4]<1 for c,x,y in entries)),
                   'flatNormalCharts':int(sum(c[6] for c,x,y in entries))}
        if terrain:
            bake_info={**bake_info,'method':'control_mask_pca_splats',
                       'controlProjection':'Unity world XZ; inferred control scale'}
        variant['terrainMaskBake' if terrain else 'vertexBlendBake']=bake_info
        png_started=time.perf_counter()
        for i,role in enumerate(('color','normal','metallic')):
            path=f'images/blend_{token}_{page}_{role}.png'
            if not reuse:Image.fromarray(buffers[i]).save(root/path,compress_level=1)
            variant['textures'][role]=path
        if session:session.stats['pngSeconds']+=time.perf_counter()-png_started
        mi=len(materials.items);materials.items.append(variant)
        parts.append({'name':mesh['name']+f'_blend_{page}','material':mi,'vertices':np.asarray(vertices,dtype='<f4'),
                      'normals':np.asarray(normals,dtype='<f4'),'faces':np.arange(len(vertices),dtype='<u4').reshape(-1,3),
                      'uv':np.concatenate(out_uv).astype('<f4'),'uv1':np.asarray(uv1,dtype='<f4') if uv1 is not None else None,'colors':None,
                      'extras':{**mesh['extras'],('terrainMaskBake' if terrain else 'vertexBlendBake'):bake_info}})
    return parts
