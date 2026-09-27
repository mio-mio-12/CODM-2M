import hashlib
import json
import struct
import tempfile
from pathlib import Path
import numpy as np
from .version import APP_NAME


def encoded(value):
    return json.dumps(value,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('utf-8')


class GLB:
    def __init__(self):
        self.bin=bytearray()
        self.doc={'asset':{'version':'2.0','generator':APP_NAME},'scene':0,
                  'scenes':[{'nodes':[]}],'nodes':[],'meshes':[],'materials':[],
                  'buffers':[{'byteLength':0}],'bufferViews':[],'accessors':[],'images':[],'textures':[]}
        self.textures={}

    def view(self,data):
        self.bin.extend(b'\0'*(-len(self.bin)%4));offset=len(self.bin);self.bin.extend(data)
        result=len(self.doc['bufferViews'])
        self.doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(data)})
        return result

    def accessor(self,array,kind,component=5126,bounds=False):
        array=np.asarray(array,dtype='<u4' if component==5125 else '<f4')
        entry={'bufferView':self.view(array.tobytes()),'componentType':component,'count':len(array),'type':kind}
        if bounds:
            entry['min']=array.min(axis=0).tolist();entry['max']=array.max(axis=0).tolist()
        result=len(self.doc['accessors']);self.doc['accessors'].append(entry);return result

    def texture(self,path):
        path=Path(path)
        if str(path) in self.textures:return self.textures[str(path)]
        idx=len(self.doc['images']);self.doc['images'].append({'bufferView':self.view(path.read_bytes()),'mimeType':'image/png','name':path.name})
        result=len(self.doc['textures']);self.doc['textures'].append({'source':idx});self.textures[str(path)]=result;return result

    def material(self,m,root):
        pbr={'baseColorFactor':m.get('glbColorFactor',m['color']),'metallicFactor':m['metallic'],'roughnessFactor':m['roughness']}
        name=('decal_' if m['decal'] else '')+m['name']
        entry={'name':name,'pbrMetallicRoughness':pbr,'alphaMode':m['alpha'],'doubleSided':m['doubleSided'],
               'extras':{'codm':{k:m[k] for k in ('source','blend','decal')},'collision':False if m['decal'] else None}}
        if m['alpha']=='MASK':entry['alphaCutoff']=m['cutoff']
        for role,path in m['textures'].items():
            if role=='color':path=m.get('glbColorTexture',path)
            info={'index':self.texture(Path(root)/path)}
            if role=='color':pbr['baseColorTexture']=info
            elif role=='metallic':pbr['metallicRoughnessTexture']=info
            elif role=='normal':entry['normalTexture']=info
            elif role=='emissive':entry['emissiveTexture']=info
        if any(m.get('emissive',[])):entry['emissiveFactor']=m['emissive']
        if m.get('unlit'):
            entry['extensions']={'KHR_materials_unlit':{}}
            self.doc['extensionsUsed']=['KHR_materials_unlit']
        self.doc['materials'].append(entry)

    def mesh(self,m):
        attrs={'POSITION':self.accessor(m['vertices'],'VEC3',bounds=True), 'NORMAL':self.accessor(m['normals'],'VEC3')}
        if m.get('uv') is not None:attrs['TEXCOORD_0']=self.accessor(m['uv'],'VEC2')
        if m.get('uv1') is not None:attrs['TEXCOORD_1']=self.accessor(m['uv1'],'VEC2')
        if m.get('colors') is not None:attrs['COLOR_0']=self.accessor(np.clip(m['colors'],0,1),'VEC4')
        primitive={'attributes':attrs,'indices':self.accessor(m['faces'].reshape(-1),'SCALAR',5125),'material':m['material']}
        mesh_idx=len(self.doc['meshes']);self.doc['meshes'].append({'name':m['name'],'primitives':[primitive]})
        idx=len(self.doc['nodes']);self.doc['nodes'].append({'name':m['name'],'mesh':mesh_idx,'extras':m.get('extras',{})});self.doc['scenes'][0]['nodes'].append(idx)

    def save(self,path):
        if len(self.bin)>0xffffffff-1000000:raise ValueError('GLB exceeds 4 GiB limit; split the map into scenes')
        self.doc['buffers'][0]['byteLength']=len(self.bin)
        for field in ('images','textures'):
            if not self.doc[field]:del self.doc[field]
        j=encoded(self.doc);j+=b' '*(-len(j)%4)
        padding=b'\0'*(-len(self.bin)%4);binary_length=len(self.bin)+len(padding)
        with Path(path).open('wb') as f:
            f.write(struct.pack('<4sII','glTF'.encode(),2,12+8+len(j)+8+binary_length))
            f.write(struct.pack('<I4s',len(j),b'JSON'));f.write(j)
            f.write(struct.pack('<I4s',binary_length,b'BIN\0'));f.write(self.bin);f.write(padding)


def write_glb(path,meshes,materials,root):
    g=GLB()
    used=sorted({m['material'] for m in meshes})
    remap={original:i for i,original in enumerate(used)}
    for index in used:g.material(materials[index],root)
    for m in meshes:g.mesh({**m,'material':remap[m['material']]})
    g.save(path)


def cs(s):

    if '\0' in s:raise ValueError('NUL in C2M string')
    return b'\1'+s.encode('utf-8')+b'\0'


def to_c2m(v,normal=False):
    a=np.asarray(v,dtype=np.float64)
    return (a[:,[0,2,1]]*[1,-1,1]*(1 if normal else 1/.0254)).astype('<f4')


def collision_chunk(colliders):
    records=[]
    for c in colliders:
        record={k:v for k,v in c.items() if k not in ('vertices','faces')}
        if 'vertices' in c:
            record['vertices']=to_c2m(c['vertices']).tolist()
            record['triangles']=np.asarray(c['faces'],dtype=np.uint32).tolist()
        records.append(record)
    return encoded({'schema':'codm.collision/1','coordinateSystem':'RH_Z_UP','units':'inches','colliders':records})


def write_c2m(path,meshes,materials,colliders,metadata,navigation):
    path=Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent,prefix=path.name+'.',suffix='.partial',delete=False) as tmp:
        pending=Path(tmp.name)
    try:
        _write_c2m(pending,meshes,materials,colliders,metadata,navigation)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def _write_c2m(path,meshes,materials,colliders,metadata,navigation):
    if len(materials)>65535:raise ValueError('C2M supports at most 65535 materials')

    with Path(path).open('w+b') as f:
        f.write(b'C2M'+bytes([3,255])+cs(metadata['name'])+cs(''))
        table=f.tell();f.write(b'\0'*80)
        object_offset=f.tell();nv=sum(len(m['vertices']) for m in meshes);nf=sum(len(m['faces']) for m in meshes)
        f.write(cs('mapGeometry'));f.write(struct.pack('<IIIIf',nv,len(meshes),nf,0,0))
        for m in meshes:f.write(to_c2m(m['vertices']).tobytes())
        for m in meshes:f.write(to_c2m(m['normals'],True).tobytes())
        for m in meshes:
            uv=m.get('uv');uv=np.zeros((len(m['vertices']),2),dtype='<f4') if uv is None else uv
            block=np.empty(len(uv),dtype=[('sets','<u4'),('uv','<f4',(2,))]);block['sets']=1;block['uv']=uv;f.write(block.tobytes())
        for m in meshes:
            colors=m.get('colors');colors=np.ones((len(m['vertices']),4)) if colors is None else colors
            f.write(np.uint8(np.clip(colors,0,1)*255).tobytes())
        offset=0
        for m in meshes:
            f.write(cs(m['name'])+struct.pack('<QBBH',0,1,1,m['material'])+struct.pack('<I',len(m['faces'])))
            f.write((m['faces']+offset).astype('<u4').tobytes());offset+=len(m['vertices'])
        instance_offset=f.tell();image_offset=f.tell();material_offset=f.tell()
        for m in materials:
            name=('decal_' if m['decal'] else 'foliage_' if m['alpha']=='MASK' else '')+m['name']
            m['c2mMaterialName']=name
            tech='codm_'+('multiply' if m['blend']=='multiply' else 'additive' if m['blend']=='additive' else 'mc_glass' if m['alpha']=='BLEND' and not m['decal'] else 'opaque')
            textures=[(p,{'color':'colorMap','normal':'normalMap','metallic':'specularMap','emissive':'emissiveMap'}[role]) for role,p in m['textures'].items()]
            f.write(cs(name)+cs(tech)+cs('')+bytes([0,12 if m['decal'] else 0,len(textures),0]))
            for p,role in textures:f.write(cs(Path(p).stem)+cs(role))
        light_offset=f.tell();ents_offset=f.tell();f.write(cs(''))
        base_end=f.tell()
        f.seek(table)

        f.write(struct.pack('<IQIIQIQIQIQQ',1,object_offset,0,0,instance_offset,0,image_offset,len(materials),material_offset,0,light_offset,ents_offset))
        f.seek(base_end)
        chunks=[]
        metadata={**metadata,'schema':'codm.c2mx/1','baseFormat':'C2M v3','visualMaterials':materials,
                  'collisionPolicy':'authored_only','legacyCollisionIsApproximate':True}
        for tag,payload in [(b'META',encoded(metadata)),(b'COLL',collision_chunk(colliders)),(b'NAVM',encoded(navigation))]:
            f.write(b'\0'*(-f.tell()%8));start=f.tell();f.write(payload)
            chunks.append((tag,1,start,len(payload)))
        f.write(b'\0'*(-f.tell()%8));directory=f.tell()
        for c in chunks:f.write(struct.pack('<4sIQQ',*c))
        length=f.tell()-directory

        f.write(struct.pack('<4sIQQII',b'C2MX',1,directory,length,len(chunks),0))


def read_extension(path):
    path=Path(path);size=path.stat().st_size
    with path.open('rb') as f:
        if size<32:raise ValueError('No C2MX footer')
        f.seek(size-32);magic,version,offset,length,count,flags=struct.unpack('<4sIQQII',f.read(32))
        if magic!=b'C2MX' or version!=1 or flags or length!=count*24 or offset+length!=size-32:
            raise ValueError('Invalid C2MX footer')
        f.seek(offset);records=[struct.unpack('<4sIQQ',f.read(24)) for _ in range(count)]
        chunks={};spans=[]
        for tag,version,start,length in records:
            if start<5 or start+length>offset or version!=1 or tag in chunks:
                raise ValueError('Invalid C2MX chunk')
            if any(start<end and start+length>begin for begin,end in spans):raise ValueError('Overlapping C2MX chunks')
            spans.append((start,start+length));f.seek(start);chunks[tag.decode('ascii')]=json.loads(f.read(length))
        return chunks
