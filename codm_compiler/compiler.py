import base64
import json
import time
from collections import Counter
from pathlib import Path
import numpy as np
from UnityPy.helpers.MeshHelper import MeshHandler
from .source import Source,key,jsonable
from .geometry import trs,vector,bake,compact,bake_compact,clip_projector
from .materials import Materials,safe_name
from .formats import write_glb,write_c2m,collision_chunk
from .catalog import scene_labels


class CODMMesh(MeshHandler):
    def get_triangles(self):
        # Static-batch renderers repeatedly reference the same decoded source.
        if not hasattr(self,'_codm_triangles'):
            self._codm_triangles=super().get_triangles()
        return self._codm_triangles

    def get_channel_dtype(self,channel):
        # CODM's channel 5 is one byte/component (confirmed against full stream bounds).
        # Packed tangents are not exported; normals/tangents are reconstructed as needed.
        if self.version[0]<2017 and channel.format==5:return 'b'
        return super().get_channel_dtype(channel)


class Compiler:
    def __init__(self,catalog,output,log=print,max_texture=2048,include_inactive=False,baking='auto'):
        self.source=Source(catalog,log);self.output=Path(output);self.log=log
        self.output.mkdir(parents=True,exist_ok=True)
        self.materials=Materials(self.source,self.output,max_texture)
        from .bake_session import BakeSession
        self.materials.bake_session=BakeSession(baking,log)
        self.include_inactive=include_inactive;self.transforms={};self.go_transform={};self.worlds={}
        self.mesh_cache={};self.meshes=[];self.colliders=[];self.errors=[];self.entities=[];self.nav=[]
        self.active_cache={};self.collision_errors=[];self.projectors=[];self.scene_files=[]
        self.lighting=[];self.omitted_renderers=[]

    def components(self,go):
        return [self.source.ref(go,c.get('component',c)) for c in self.source.tree(go).get('m_Component',[])]

    def world(self,obj,stack=None):
        if obj is None:return np.eye(4)
        k=key(obj)
        if k in self.worlds:return self.worlds[k]
        stack=set() if stack is None else set(stack)
        if k in stack:raise ValueError('Cycle in transform hierarchy')
        stack.add(k);t=self.source.tree(obj)
        parent=self.source.ref(obj,t.get('m_Father'))
        m=self.world(parent,stack)@trs(t);self.worlds[k]=m;return m

    def go_info(self,obj):
        t=self.source.tree(obj);go=self.source.ref(obj,t.get('m_GameObject'))
        if go is None:return None,{},None
        g=self.source.tree(go)
        transform=self.go_transform.get(key(go))
        if transform is None:
            transform=next((c for c in self.components(go) if c and c.type.name in ('Transform','RectTransform')),None)
            self.go_transform[key(go)]=transform
        return go,g,transform

    def active(self,transform):
        if transform is None:return True
        k=key(transform)
        if k in self.active_cache:return self.active_cache[k]
        t=self.source.tree(transform);go=self.source.ref(transform,t.get('m_GameObject'))
        active=not go or self.source.tree(go).get('m_IsActive',True)
        parent=self.source.ref(transform,t.get('m_Father'))
        active=active and self.active(parent)
        self.active_cache[k]=active;return active

    def mesh(self,obj):
        k=key(obj)
        if k not in self.mesh_cache:
            data=obj.read();h=CODMMesh(data);h.process()
            if h.m_Vertices is None:raise ValueError('Mesh has no decoded vertices')
            vd=data.m_VertexData
            if vd and vd.m_Channels and vd.m_DataSize:
                streams=h.get_streams(vd.m_Channels,vd.m_VertexCount)
                extent=max(x.offset+x.stride*vd.m_VertexCount for x in streams)
                if not extent<=len(vd.m_DataSize)<=extent+15:
                    raise ValueError(f'Unsupported vertex stream layout ({extent} vs {len(vd.m_DataSize)})')
            colors=np.asarray(h.m_Colors,dtype=np.float32) if h.m_Colors else None
            if colors is not None and colors.max()>1:colors/=255.
            # Convert shared attributes once instead of for each renderer/submesh.
            for name in ('m_Vertices','m_Normals','m_UV0','m_UV1'):
                values=getattr(h,name)
                if values is not None:setattr(h,name,np.asarray(values,dtype=np.float64 if name in ('m_Vertices','m_Normals') else '<f4'))
            self.mesh_cache[k]=(h,colors)
        return self.mesh_cache[k]

    def renderer(self,obj,excluded):
        t=self.source.tree(obj);go,g,transform=self.go_info(obj)
        if not t.get('m_Enabled',True) or key(obj) in excluded:return
        if not self.include_inactive and not self.active(transform):return
        if t.get('m_CastShadows',1)==3:
            # Unity ShadowCastingMode.ShadowsOnly is invisible in the color pass.
            # Evaluate per renderer, never by material name; colliders are separate.
            self.omitted_renderers.append({'sourceRenderer':key(obj),'name':g.get('m_Name',''),
                                           'reason':'shadows_only','shadowCastingMode':3})
            return
        if obj.type.name=='SkinnedMeshRenderer':
            self.source.warnings.append(f"{g.get('m_Name')}: skinned renderer requires a pose; not exported as static geometry")
            return
        mf=next((c for c in self.components(go) if c and c.type.name=='MeshFilter'),None)
        if mf is None:raise ValueError('MeshRenderer has no MeshFilter')
        meshobj=self.source.ref(mf,self.source.tree(mf).get('m_Mesh'))
        if meshobj is None:
            self.source.warnings.append(f"{g.get('m_Name')}: null MeshFilter has no authored visual mesh")
            return
        h,colors=self.mesh(meshobj);submeshes=h.get_triangles()
        batch=t.get('m_StaticBatchInfo',{});count=batch.get('subMeshCount',0)
        if count:
            start=batch.get('firstSubMesh',0);indices=list(range(start,start+count))
            root=self.source.ref(obj,t.get('m_StaticBatchRoot'));matrix=self.world(root)
        else:indices=list(range(len(submeshes)));matrix=self.world(transform)
        if indices and max(indices)>=len(submeshes):raise ValueError('Static batch range outside mesh')
        mats=t.get('m_Materials',[])
        for slot,index in enumerate(indices):
            faces=submeshes[index]
            if not faces:continue
            mat=self.source.ref(obj,mats[min(slot,len(mats)-1)]) if mats else None
            mi=self.materials.get(mat);material=self.materials.items[mi]
            m=bake_compact(h.m_Vertices,h.m_Normals,faces,matrix,h.m_UV0,colors,h.m_UV1)
            if material.get('vertexWind'):m['colors']=None
            if material['decal'] and material['blend']=='alpha':
                m['vertices']+=m['normals']*.0005
            if m['uv'] is not None and not (material.get('vertexBlend') or material.get('terrainMask')):
                m['uv']*=material['uv_scale'];m['uv']+=material['uv_offset'];m['uv'][:,1]=1-m['uv'][:,1]
            if m['uv1'] is not None:m['uv1'][:,1]=1-m['uv1'][:,1]
            m.update(name=('nocollision_sky_' if material.get('sky') else 'decal_' if material['decal'] else '')+g.get('m_Name','mesh'),material=mi,
                     extras={'sourceRenderer':key(obj),'sourceMesh':key(meshobj),'submesh':index,
                             'unityWorldMatrix':self.world(transform).flatten(order='F').tolist(),
                             'staticBatch':bool(count),'lightmapIndex':t.get('m_LightmapIndex'),
                             'lightmapScaleOffset':t.get('m_LightmapTilingOffset'),
                             'decal':material['decal'],'sortingOrder':t.get('m_SortingOrder',0),
                             'decalOffsetMetres':.0005 if material['decal'] and material['blend']=='alpha' else 0,
                             'layer':g.get('m_Layer',0),
                             'collision':'separate C2MX COLL chunk'})
            if material.get('vertexBlend') or material.get('terrainMask'):
                from .blending import bake_mesh
                self.log(f"Baking ground layers: {m['name']} ({len(m['faces'])} triangles)")
                self.meshes.extend(bake_mesh(m,self.materials,mi))
            elif material.get('atlas'):
                if m['colors'] is None:raise ValueError('Atlased mesh has no vertex color atlas indices')
                slots=np.rint(m['colors'][:,3]*255).astype(np.int32)//4
                face_slots=slots[m['faces']]
                if (face_slots!=face_slots[:,0,None]).any():raise ValueError('Atlas index varies within a triangle')
                for atlas_slot in np.unique(face_slots[:,0]):
                    subset=m['faces'][face_slots[:,0]==atlas_slot]
                    part=compact(m['vertices'],m['normals'],subset,m['uv'],m['colors'],m['uv1'])
                    part['material']=self.materials.atlas_variant(mi,int(atlas_slot))
                    part['name']=m['name']+f'_tile_{atlas_slot}';part['extras']={**m['extras'],'atlasSlot':int(atlas_slot)}
                    part['colors'][:,3]=1
                    if not material.get('vertexTint'):part['colors'][:,:3]=1
                    self.meshes.append(part)
            else:self.meshes.append(m)

    def collider(self,obj):
        t=self.source.tree(obj);go,g,transform=self.go_info(obj)
        if not t.get('m_Enabled',True) or (not self.include_inactive and not self.active(transform)):return
        world=self.world(transform)
        # Local metre Unity primitives -> local inch Z-up RH primitives.
        basis=np.array([[-1,0,0],[0,0,-1],[0,1,0]],dtype=np.float64)
        matrix=np.eye(4);matrix[:3,:3]=basis@world[:3,:3]@basis.T;matrix[:3,3]=basis@world[:3,3]/.0254
        entry={'id':key(obj),'name':g.get('m_Name','collider'),'kind':obj.type.name,'trigger':bool(t.get('m_IsTrigger',False)),
               'layer':g.get('m_Layer',0),'enabled':True,'matrix':matrix.flatten(order='F').tolist(),
               'source':jsonable(t),'center':(basis@vector(t.get('m_Center',{}))/.0254).tolist()}
        if obj.type.name=='BoxCollider':entry['size']=(vector(t['m_Size'])[[0,2,1]]/.0254).tolist()
        elif obj.type.name in ('SphereCollider','CapsuleCollider'):
            entry['radius']=float(t['m_Radius']/.0254)
            entry['scalePolicy']='unity_max_axis'
            if obj.type.name=='CapsuleCollider':
                entry['height']=float(t['m_Height']/.0254);entry['axis']={0:0,1:2,2:1}[t['m_Direction']]
                entry['scalePolicy']='unity_axis_height_max_perpendicular_radius'
        elif obj.type.name=='MeshCollider':
            mo=self.source.ref(obj,t.get('m_Mesh'))
            if mo is None:
                entry.update(empty=True,vertices=np.empty((0,3),dtype='<f4'),faces=np.empty((0,3),dtype='<u4'),convex=bool(t.get('m_Convex',False)))
                entry['matrix']=np.eye(4).flatten(order='F').tolist();entry['center']=[0,0,0]
                self.colliders.append(entry)
                self.source.warnings.append(f"{g.get('m_Name')}: null MeshCollider retained as empty; no authored collision shape")
                return
            h,_=self.mesh(mo);faces=[f for sub in h.get_triangles() for f in sub]
            m=bake_compact(h.m_Vertices,None,faces,world)
            entry.update(vertices=m['vertices'],faces=m['faces'],convex=bool(t.get('m_Convex',False)))
            entry['matrix']=np.eye(4).flatten(order='F').tolist();entry['center']=[0,0,0]
            if entry['convex']:
                self.collision_errors.append({'id':key(obj),'error':'Convex source mesh retained; cooked PhysX hull not decoded'})
        else:
            raise ValueError(f"Unsupported authored collider {obj.type.name}")
        pm=self.source.ref(obj,t.get('m_Material'))
        if pm:entry['physicsMaterial']=jsonable(self.source.tree(pm))
        self.colliders.append(entry)

    def light(self,obj):
        t=self.source.tree(obj);nonfinite=[]
        record={'id':key(obj),'type':obj.type.name,'data':jsonable(t,nonfinite)}
        if nonfinite:
            record['nonFiniteSourceFields']=nonfinite
            self.source.warnings.append(f"{obj.type.name}: {len(nonfinite)} non-finite source lighting values preserved as explicit metadata markers; not used for rendering")
        if obj.type.name=='LightmapSettings':
            images=[]
            for lightmap in t.get('m_Lightmaps',[]):
                textures={}
                for role,ptr in lightmap.items():
                    if isinstance(ptr,dict) and ptr.get('m_PathID'):
                        try:textures[role]=self.materials.texture(self.source.ref(obj,ptr))
                        except Exception as e:textures[role]={'error':str(e)}
                images.append(textures)
            record['images']=images
            if images:self.source.warnings.append('Baked lighting textures and renderer UV1 scale/offset preserved; not multiplied into exported base color')
        elif obj.type.name=='Light':
            _,_,tr=self.go_info(obj);record['unityWorldMatrix']=self.world(tr).flatten(order='F').tolist()
        self.lighting.append(record)

    def preserve_component(self,obj):
        t=self.source.tree(obj)
        label=self.source.script_name(obj,t) if obj.type.name=='MonoBehaviour' else obj.type.name
        if obj.type.name=='NavMeshData' or any(x in label.lower() for x in ('navmesh','navigation','recast','offmesh')):
            entry=self.source.preserve(obj,self.output/'navigation',label)
            entry['encoding']='unity-serialized-object';entry['nativeUsableInCadence']=False
            entry['kind']='native_payload' if obj.type.name=='NavMeshData' else 'component_settings'
            entry['settings']=jsonable(t)
            entry['dataBase64']=base64.b64encode(obj.get_raw_data()).decode('ascii')
            self.nav.append(entry)
        elif obj.type.name=='MonoBehaviour' and any(x in label.lower() for x in ('decal','terrain','stream','instance','scene')):
            self.entities.append({'id':key(obj),'script':label,'data':jsonable(t)})
            if 'decal' in label.lower():
                self.source.warnings.append(f"Custom decal component {label} preserved; only explicit mesh decals and orthographic Projectors are currently baked")

    def project(self,obj):
        t=self.source.tree(obj);go,g,tr=self.go_info(obj)
        if not t.get('m_Enabled',True) or not self.active(tr):return
        if not t.get('m_Orthographic',False):raise ValueError('Perspective projector requires frustum baking; source component preserved')
        half=t['m_OrthographicSize'];aspect=t.get('m_AspectRatio',1)
        bounds=([-half*aspect,-half,t.get('m_NearClipPlane',.1)],[half*aspect,half,t.get('m_FarClipPlane',10)])
        ignored=t.get('m_IgnoreLayers',0)
        receivers=[m for m in self.meshes if not m['extras']['decal'] and not ignored & (1<<m['extras'].get('layer',0))]
        mesh=clip_projector(receivers,self.world(tr),bounds)
        if len(mesh['faces']):
            mat=self.source.ref(obj,t.get('m_Material'));mesh.update(name='decal_'+g.get('m_Name','projector'),material=self.materials.get(mat,True),extras={'projector':key(obj),'decal':True})
            self.meshes.append(mesh)

    def run(self,scene_names,formats=('c2m','glb'),sidecars=None,allow_empty=False):
        started=time.perf_counter()
        try:
            result=self._run(scene_names,formats,sidecars,allow_empty)
            result['timings']['totalSeconds']=time.perf_counter()-started
            (self.output/'report.json').write_text(json.dumps(result,indent=2),'utf-8')
            return result
        finally:self.materials.bake_session.close()

    def _run(self,scene_names,formats=('c2m','glb'),sidecars=None,allow_empty=False):
        conversion_started=time.perf_counter()
        sidecars=set(('spawns','volumes','tactical') if sidecars is None else sidecars)
        selected_nodes=set()
        for name in scene_names:
            matches=[m for label,m in scene_labels(self.source.catalog) if label==name]
            if len(matches)!=1:raise ValueError(f'Scene name must be unique: {name} ({len(matches)} matches)')
            m=matches[0]
            if m['node'].lower() in selected_nodes:raise ValueError('Selected scenes share an internal file name; export these separate map/tile variants individually')
            selected_nodes.add(m['node'].lower());self.source.load(m['path']);self.scene_files.append(self.source.file(m['node']))
        objects=[o for f in self.scene_files for o in f.objects.values()]
        excluded=set()
        for obj in objects:
            if obj.type.name in ('Transform','RectTransform'):
                t=self.source.tree(obj);go=self.source.ref(obj,t.get('m_GameObject'))
                if go:self.go_transform[key(go)]=obj
            elif obj.type.name=='LODGroup':
                t=self.source.tree(obj)
                # Highest detail only; lower LODs overlap the same physical object.
                for lod in t.get('m_LODs',[])[1:]:
                    for renderer in lod.get('renderers',[]):
                        r=self.source.ref(obj,renderer.get('renderer',renderer))
                        if r:excluded.add(key(r))
        for i,obj in enumerate(objects):
            typ=obj.type.name
            try:
                if typ in ('MeshRenderer','SkinnedMeshRenderer'):self.renderer(obj,excluded)
                elif typ.endswith('Collider'):self.collider(obj)
                elif typ=='Projector':self.projectors.append(obj)
                elif typ in ('NavMeshData','MonoBehaviour'):self.preserve_component(obj)
                elif typ in ('Light','LightmapSettings','RenderSettings'):self.light(obj)
                elif allow_empty and (typ.startswith('Unknown') or typ=='Terrain'):
                    self.source.preserve(obj,self.output/'unsupported_objects')
                    self.errors.append({'id':key(obj),'type':typ,'error':'Unsupported streamed object retained as raw source; not converted to visual geometry'})
            except Exception as e:
                entry={'id':key(obj),'type':typ,'error':str(e)};self.errors.append(entry)
                if typ.endswith('Collider'):self.collision_errors.append(entry)
            if i%200==0:self.log(f'Processed {i+1}/{len(objects)} objects; {len(self.meshes)} surfaces, {len(self.colliders)} colliders')
        for p in self.projectors:
            try:self.project(p)
            except Exception as e:
                self.errors.append({'id':key(p),'type':'Projector','error':str(e)})
                self.source.preserve(p,self.output/'source_projectors')
        if not self.meshes and not allow_empty:
            (self.output/'report.json').write_text(json.dumps({'errors':self.errors,'warnings':self.source.warnings},indent=2),'utf-8')
            raise ValueError('No drawable surfaces extracted; see report.json. Select a visual scene (often *_Atlases).')
        conversion_seconds=time.perf_counter()-conversion_started
        sidecar_started=time.perf_counter()
        from .spawns import extract_spawns,write_spawns
        from .version import APP_NAME
        try:spawns=extract_spawns(self.source.catalog,scene_names,self.log) if 'spawns' in sidecars else {'status':'disabled','complete':True,'spawnCount':0,'sets':[]}
        except Exception as e:
            spawns={'schema':'codm.spawns/1','generator':APP_NAME,'status':'partial','complete':False,'spawnCount':0,'sets':[],'errors':[{'error':str(e)}]}
        if 'spawns' in sidecars:write_spawns(self.output/'spawns.json',spawns)
        gameplay={}
        if sidecars & {'volumes','tactical'}:
            from .gameplay import extract_gameplay
            volumes,tactical=extract_gameplay(self.source.catalog,scene_names,self.log,'volumes' in sidecars,'tactical' in sidecars)
            for option,filename,data in [('volumes','gameplay_volumes.json',volumes),('tactical','tactical_markers.json',tactical)]:
                if option in sidecars:
                    write_spawns(self.output/filename,data)
                    gameplay[option]={'file':filename,'count':data['count'],'status':data['status'],'complete':data['complete']}
        self.log(f"Spawn points: {spawns['spawnCount']} across {len(spawns['sets'])} gameplay scenes ({spawns['status']})")
        name=safe_name(scene_names[0]);metadata={'name':name,'generator':APP_NAME,'scenes':scene_names,'sourceRoot':self.source.catalog['root'],
          'spawnFile':'spawns.json' if 'spawns' in sidecars else None,'spawnCount':spawns['spawnCount'],'spawnStatus':spawns['status'],'spawnComplete':spawns['complete'],
          'gameplaySidecars':gameplay,'gameplayComplete':all(g['complete'] for g in gameplay.values()),
          'surfaceCount':len(self.meshes),'triangleCount':sum(len(m['faces']) for m in self.meshes),'colliderCount':len(self.colliders),
          'collisionComplete':not self.collision_errors,'extractionComplete':not self.errors and not self.materials.failures,'errors':self.errors,
          'textureErrors':self.materials.failures,
          'visualStatus':'exported' if self.meshes else 'no_visible_meshes',
          'omittedRenderers':self.omitted_renderers,
          'baking':dict(self.materials.bake_session.stats),'timings':{'conversionSeconds':conversion_seconds,'sidecarSeconds':time.perf_counter()-sidecar_started},
          'collisionErrors':self.collision_errors,'lighting':self.lighting,
          'visualSurfaces':[{'name':m['name'],'material':m['material'],'triangles':len(m['faces']),**m.get('extras',{})} for m in self.meshes],
          'renderFidelity':'approximate_custom_shaders','collisionScope':'selected scenes only',
          'warnings':list(dict.fromkeys(self.source.warnings)),'loadedBundles':sorted(self.source.loaded),
          'unityToC2M':'(-x,-z,y) / 0.0254','unityToGLB':'(-x,y,z) metres',
          'sceneObjectCounts':dict(Counter(o.type.name for o in objects))}
        navigation={'schema':'codm.navigation/1','status':('native_payload_preserved' if any(n['kind']=='native_payload' for n in self.nav) else 'settings_only') if self.nav else 'not_found_in_selected_scenes',
                    'assets':self.nav,'runtimeReady':False}
        self.log('Writing map files and authored collision extension')
        if 'glb' in formats and self.meshes:
            started=time.perf_counter();write_glb(self.output/(name+'.glb'),self.meshes,self.materials.items,self.output)
            metadata['timings']['glbSeconds']=time.perf_counter()-started
        if 'c2m' in formats and self.meshes:
            started=time.perf_counter();write_c2m(self.output/(name+'.c2m'),self.meshes,self.materials.items,self.colliders,metadata,navigation)
            metadata['timings']['c2mSeconds']=time.perf_counter()-started
        (self.output/'collision.json').write_bytes(collision_chunk(self.colliders))
        (self.output/'report.json').write_text(json.dumps(metadata,indent=2),'utf-8')
        (self.output/'entities.json').write_text(json.dumps(self.entities,indent=2),'utf-8')
        (self.output/'navigation.json').write_text(json.dumps(navigation,indent=2),'utf-8')
        self.log(f"Exported {metadata['triangleCount']:,} triangles, {len(self.colliders)} authored colliders; {len(self.errors)} extraction errors")
        return metadata
