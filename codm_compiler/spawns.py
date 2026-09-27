import json
import re
from pathlib import Path
import numpy as np
from .source import Source, key, jsonable
from .geometry import trs
from .version import APP_NAME


def visual_family(label):
    name=label.split(' | ',1)[0]

    return re.sub(r'(?:_(?:Atlases|Final|HQ|New))+$','',name,flags=re.I)


def matching_scenes(catalog, labels):
    families={visual_family(label).lower() for label in labels}
    exact={'buildplayer-'+label.split(' | ',1)[0].lower() for label in labels}
    matches=[]
    for bundle in catalog['bundles']:
        for node in bundle['nodes']:
            name=node['name']
            if '.sharedassets' in name.lower():continue
            match=re.fullmatch(r'BuildPlayer-(.+?)_(Main(?:_.*)?|LDBasic)',name,re.I)
            if match and (match[1].lower() in families or name.lower() in exact):
                matches.append((bundle['path'],name,match[1],match[2]))
    return sorted(set(matches))


def extract_spawns(catalog, labels, log=print):
    selected=matching_scenes(catalog,labels)
    result={'schema':'codm.spawns/1','generator':APP_NAME,'visualScenes':list(labels),
            'coordinateSystem':'RH_Z_UP','units':'inches',
            'positionConversion':'Unity (-x,-z,y)/0.0254; GLB (-x,y,z) metres',
            'status':'not_found','complete':True,'spawnCount':0,'sets':[],
            'sourceBundles':[],'matchedScenes':[r[1] for r in selected],'errors':[]}
    if not selected:return result
    source=Source(catalog,log);worlds={};active={}
    basis=np.array([[-1.,0,0],[0,0,-1],[0,1,0]])
    def transform(o,stack=()):
        if o is None:return np.eye(4),True
        ident=key(o)
        if ident in worlds:return worlds[ident],active[ident]
        if ident in stack:raise ValueError('Cycle in spawn transform hierarchy')
        t=source.tree(o);parent=source.ref(o,t.get('m_Father'))
        pm,pa=transform(parent,stack+(ident,));m=pm@trs(t)
        go=source.ref(o,t.get('m_GameObject'))
        enabled=pa and (bool(source.tree(go).get('m_IsActive',True)) if go else True)
        if not np.isfinite(m).all():raise ValueError('Non-finite spawn transform')
        worlds[ident]=m;active[ident]=enabled;return m,enabled
    for path,node,family,mode in selected:
        log(f'Reading spawn points: {node}')
        group={'scene':node,'mapFamily':family,'mode':mode,'modeTypes':[], 'spawns':[]}
        result['sets'].append(group)
        try:
            source.load(path);file=source.file(node)
            for obj in file.objects.values():
                if obj.type.name!='MonoBehaviour':continue
                try:
                    t=source.tree(obj)
                    if not t.get('m_Script',{}).get('m_PathID'):continue
                    script=source.script_name(obj,t)
                    if not script:raise ValueError('Unresolved component script identity')
                    if script=='ModeDetail':group['modeTypes']=jsonable(t.get('ModeTypes',[]));continue
                    if script!='StartSpot':continue
                    go=source.ref(obj,t.get('m_GameObject'))
                    if go is None:raise ValueError('StartSpot has no GameObject')
                    g=source.tree(go);tr=None
                    for component in g.get('m_Component',[]):
                        candidate=source.ref(go,component.get('component',component))
                        if candidate and candidate.type.name=='Transform':tr=candidate;break
                    if tr is None:raise ValueError('StartSpot has no Transform')
                    matrix,hierarchy=transform(tr);p=matrix[:3,3];rotation=matrix[:3,:3]
                    forward=rotation[:,2].copy();up=rotation[:,1].copy()
                    if min(np.linalg.norm(forward),np.linalg.norm(up))<1e-10:raise ValueError('Degenerate spawn orientation')
                    forward/=np.linalg.norm(forward);up/=np.linalg.norm(up)
                    group['spawns'].append({'id':key(obj),'uid':t.get('UID'),'name':g.get('m_Name',''),
                        'position':(basis@p/.0254).tolist(),'forward':(basis@forward).tolist(),'up':(basis@up).tolist(),
                        'glbPositionMetres':(p*[-1,1,1]).tolist(),'glbForward':(forward*[-1,1,1]).tolist(),'glbUp':(up*[-1,1,1]).tolist(),
                        'enabled':bool(t.get('m_Enabled',1)),'hierarchyActive':hierarchy,
                        'available':bool(t.get('m_Available',1)),'initialSpawn':bool(t.get('m_SupportInitialSpawn',0)),
                        'camp':t.get('m_Camp'),'group':t.get('m_Group'),'aiOnly':bool(t.get('bOnlyForAI',0)),
                        'sourceProperties':jsonable({k:v for k,v in t.items() if k not in ('m_GameObject','m_Script','m_Name')})})
                except Exception as e:result['errors'].append({'scene':node,'id':key(obj),'error':str(e)})
        except Exception as e:result['errors'].append({'scene':node,'error':str(e)})
    result['sourceBundles']=sorted(source.loaded)
    result['sets']=[g for g in result['sets'] if g['spawns']]
    result['spawnCount']=sum(len(g['spawns']) for g in result['sets'])
    result['complete']=not result['errors']
    result['status']='partial' if result['errors'] else 'found' if result['spawnCount'] else 'not_found'
    return result


def write_spawns(path, data):
    path=Path(path);pending=path.with_suffix(path.suffix+'.partial')
    try:
        pending.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
        pending.replace(path)
    finally:pending.unlink(missing_ok=True)
