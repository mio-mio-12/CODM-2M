"""Spatial chunk planning from authored streaming bounds, without loading geometry."""
import hashlib
import json
import math
from pathlib import Path
from .catalog import scene_labels
from .map_library import decoded_name,title
from .source import Source,key
from .version import APP_NAME

LAYER_NAMES={'Physics':'Collision','Road':'Roads','Grass':'Grass','Tree':'Trees','Tree_Sky':'Distant trees',
             'Obj_Detail':'Detail props','Obj_Mini':'Tiny props','Obj_Small':'Small props',
             'Obj_Med':'Medium structures','Obj_Big':'Large structures','Obj_BigAnim':'Animated structures',
             'Obj_LandMark':'Landmarks','Obj_InnerProps':'Interior props'}

def signature(catalog):
    return hashlib.sha256(json.dumps([(b['path'],b.get('size'),b.get('mtime')) for b in catalog['bundles']]).encode()).hexdigest()

def world_prefix(path):
    name=decoded_name(path)
    return name.split('$tiledscene$')[0] if '$tiledscene$' in name else name.rsplit('$',1)[0]

def world_scenes(catalog):
    tiled={world_prefix(m['path']) for m in catalog['maps'] if '$tiledscene$' in decoded_name(m['path'])}
    return {label:world_prefix(m['path']) for label,m in scene_labels(catalog)
            if m['name'].endswith('_Main') and world_prefix(m['path']) in tiled}

def index_path(base,scene):
    return Path(base)/'zones'/(hashlib.sha256(scene.encode()).hexdigest()[:16]+'.json')

def bounds(value):
    c=value['m_Center'];e=value['m_Extent']
    box=[float(c['x']-e['x']),float(c['z']-e['z']),float(c['x']+e['x']),float(c['z']+e['z'])]
    if not all(math.isfinite(x) for x in box) or box[2]<box[0] or box[3]<box[1]:raise ValueError('Invalid streaming bounds')
    return box

def column_name(n):
    result=''
    while n>=0:result=chr(65+n%26)+result;n=n//26-1
    return result

def grid(chunks,size=200):
    occupied=set()
    for chunk in chunks:
        x0,z0,x1,z1=chunk['bounds']
        if (math.ceil(x1/size)-math.floor(x0/size)+1)*(math.ceil(z1/size)-math.floor(z0/size)+1)>10000:
            raise ValueError('Streaming bounds exceed the supported zone grid')
        for x in range(math.floor(x0/size),max(math.floor(x0/size)+1,math.ceil(x1/size))):
            for z in range(math.floor(z0/size),max(math.floor(z0/size)+1,math.ceil(z1/size))):occupied.add((x,z))
    if not occupied:return []
    left=min(x for x,z in occupied);top=max(z for x,z in occupied)
    if (max(x for x,z in occupied)-left+1)*(top-min(z for x,z in occupied)+1)>10000:
        raise ValueError('World extent exceeds the supported zone grid')
    return [{'id':f'{x}:{z}','name':column_name(x-left)+str(top-z+1),'x':x,'z':z,
             'bounds':[x*size,z*size,(x+1)*size,(z+1)*size]} for x,z in sorted(occupied,key=lambda p:(-p[1],p[0]))]

def intersects(a,b):
    return a[0]<b[2] and a[2]>b[0] and a[1]<b[3] and a[3]>b[1]

def build_index(catalog,scene,log=print):
    worlds=world_scenes(catalog)
    if scene not in worlds:raise ValueError('Select a streamed-world Main scene')
    labels=list(scene_labels(catalog));main=next(m for label,m in labels if label==scene)
    prefix=worlds[scene];candidates={}
    for label,m in labels:
        if world_prefix(m['path'])==prefix:candidates.setdefault(m['name'].lower(),[]).append((label,m))
    source=Source(catalog,log);source.load(main['path']);file=source.file(main['node'])
    chunks=[];layers={};errors=[]
    for obj in file.objects.values():
        if obj.type.name!='MonoBehaviour':continue
        t=source.tree(obj)
        if source.script_name(obj,t)!='TiledSceneStreamer':continue
        for layer in t.get('streamingLayers',[]):
            lid=layer['baseScenePath'].replace('\\','/').rstrip('/').rsplit('/',1)[-1]
            info=layer.get('layerInfo',{});layers[lid]=LAYER_NAMES.get(lid,lid.replace('_',' '))
            for item in layer.get('streamingScenes',[]):
                lods=item.get('sceneLODs',[])
                if not lods:
                    if item.get('virtualScene',{}).get('prefabInstances'):errors.append({'layer':lid,'error':'Virtual prefab-only chunk is not supported'})
                    continue
                lod=min(lods,key=lambda l:l['lodIndex']);name=lod['sceneName']
                matches=candidates.get(name.lower(),[])
                b=bounds(item.get('compactBounds') or item['streamingBounds'])
                chunk={'id':lid+'/'+name,'name':name,'layer':lid,'layerName':layers[lid],
                       'bounds':b,'lod':lod['lodIndex'],'sourceStreamer':key(obj),
                       'disabledInSource':bool(info.get('disable',False)),
                       'scene':matches[0][0] if len(matches)==1 else None,
                       'status':'available' if len(matches)==1 else 'missing' if not matches else 'ambiguous'}
                chunks.append(chunk)
    if not chunks:raise ValueError('No authored streamed chunks found')
    # A scene can be referenced more than once. Preserve layer membership, but export it once.
    chunks=list({c['id']:c for c in chunks}.values())
    result={'schema':'codm.zone-index/1','generator':APP_NAME,'signature':signature(catalog),
            'world':scene,'title':title(scene.removesuffix('_Main')),'units':'Unity metres, X/Z',
            'cellSize':200,'layers':layers,'chunks':chunks,'cells':grid(chunks),'errors':errors}
    log(f"Zones: {len(result['cells'])} cells, {len(chunks)} chunks")
    return result

def plan(index,cells,layers,name):
    cells=set(cells);layers=set(layers)
    if not cells or not layers:raise ValueError('Select zones and layers')
    selected=[c for c in index['cells'] if c['id'] in cells]
    if len(selected)!=len(cells) or not layers<=index['layers'].keys():raise ValueError('Stale zone selection; reload the zone index')
    chunks=[];seen=set()
    for c in index['chunks']:
        if c['layer'] not in layers or c.get('disabledInSource') or not any(intersects(c['bounds'],s['bounds']) for s in selected):continue
        ident=c['scene'] or c['id']
        if ident in seen:continue
        seen.add(ident);chunks.append(dict(c))
    return {'schema':'codm.zone-export/1','generator':APP_NAME,'world':index['world'],'name':name.strip() or 'Zone',
            'indexSignature':index['signature'],'coordinatePolicy':'Original world coordinates; no recentering',
            'selectionPolicy':'Whole chunks intersecting selected 200 m cells; geometry is not clipped',
            'cells':selected,'layers':sorted(layers),'chunks':chunks,
            'scope':'Streamed chunks only; global landscape, runtime prefab/foliage instances and gameplay sets are not automatically assembled',
            'indexWarnings':index['errors']}

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8');temp.replace(path)
