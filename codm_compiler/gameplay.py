from itertools import product
import numpy as np
from .spawns import matching_scenes
from .source import Source,key,jsonable
from .geometry import trs,vector
from .version import APP_NAME

VOLUMES={'DeathZoneVolume','ClimbUpTriggerVolume','CrouchVolume','DoorAssistantVolume','LadderVolume','LadderEnterVolume'}
OBJECTIVES={'DOMObjectiveVolume','HPObjectiveVolume','ControlObjectiveVolume','GFObjectiveVolume',
            'BombPlacingPointVolume','BombInitTriggerVolume','SafeGuardTargetVolume'}
VOLUMES |= OBJECTIVES | {'NavMeshModifierVolume'}
TACTICAL={'BOTNaviSpot','CampSpot','CoverSpot','ClimbSpot'}
BASIS=np.array([[-1.,0,0],[0,0,-1],[0,1,0]])


def pose(matrix):
    if not np.isfinite(matrix).all():raise ValueError('Non-finite transform')
    p=matrix[:3,3];f=matrix[:3,2].copy();u=matrix[:3,1].copy()
    if min(np.linalg.norm(f),np.linalg.norm(u))<1e-10:raise ValueError('Degenerate orientation')
    f/=np.linalg.norm(f);u/=np.linalg.norm(u)
    cm=np.eye(4);cm[:3,:3]=BASIS@matrix[:3,:3]@BASIS.T;cm[:3,3]=BASIS@p/.0254
    gm=np.diag([-1.,1,1,1])@matrix@np.diag([-1.,1,1,1])
    return {'position':cm[:3,3].tolist(),'forward':(BASIS@f).tolist(),'up':(BASIS@u).tolist(),
            'matrix':cm.flatten(order='F').tolist(),'glbPositionMetres':gm[:3,3].tolist(),
            'glbForward':(f*[-1,1,1]).tolist(),'glbUp':(u*[-1,1,1]).tolist(),
            'glbMatrixMetres':gm.flatten(order='F').tolist()}


def shape_data(kind,t,matrix):
    result={'kind':kind,**pose(matrix),'enabled':bool(t.get('m_Enabled',True)),
            'trigger':bool(t.get('m_IsTrigger',False)),'sourceProperties':jsonable(t)}
    center=vector(t.get('m_Center',{}))
    result['center']=(BASIS@center/.0254).tolist()
    result['glbCenterMetres']=(center*[-1,1,1]).tolist()
    if kind=='BoxCollider':
        size=vector(t['m_Size'])
        if not np.isfinite(size).all() or (size<0).any():raise ValueError('Invalid box size')
        result['size']=(size[[0,2,1]]/.0254).tolist();result['glbSizeMetres']=size.tolist()
        corners=np.array([center+np.array(sign)*size/2 for sign in product((-1,1),repeat=3)])
        world=corners@matrix[:3,:3].T+matrix[:3,3]
        result['worldCorners']=(world@BASIS.T/.0254).tolist()
        result['glbWorldCornersMetres']=(world*[-1,1,1]).tolist()
    elif kind in ('SphereCollider','CapsuleCollider'):
        radius=float(t['m_Radius'])
        if not np.isfinite(radius) or radius<0:raise ValueError('Invalid radius')
        result.update(radius=radius/.0254,glbRadiusMetres=radius,scalePolicy='unity_max_axis')
        if kind=='CapsuleCollider':
            h=float(t['m_Height']);axis=int(t['m_Direction'])
            if not np.isfinite(h) or h<0 or axis not in (0,1,2):raise ValueError('Invalid capsule')
            result.update(height=h/.0254,glbHeightMetres=h,axis={0:0,1:2,2:1}[axis],glbAxis=axis,
                          scalePolicy='unity_axis_height_max_perpendicular_radius')
    else:raise ValueError(f'Unsupported gameplay volume shape: {kind}')
    return result


def extract_gameplay(catalog,labels,log=print,include_volumes=True,include_tactical=True):
    selected=matching_scenes(catalog,labels)
    def empty(schema):
        return {'schema':schema,'generator':APP_NAME,'visualScenes':list(labels),'coordinateSystem':'RH_Z_UP',
                'units':'inches','status':'not_found','complete':True,'count':0,'sets':[],
                'matchedScenes':[x[1] for x in selected],'sourceBundles':[],'errors':[]}
    volumes=empty('codm.gameplay-volumes/1');tactical=empty('codm.tactical-markers/1')
    source=Source(catalog,log);worlds={}
    def components(go):return [source.ref(go,c.get('component',c)) for c in source.tree(go).get('m_Component',[])]
    def world(obj,stack=()):
        if obj is None:return np.eye(4),True
        ident=key(obj)
        if ident in worlds:return worlds[ident]
        if ident in stack:raise ValueError('Transform cycle')
        t=source.tree(obj);parent=source.ref(obj,t.get('m_Father'));pm,pa=world(parent,stack+(ident,))
        go=source.ref(obj,t.get('m_GameObject'));active=pa and bool(source.tree(go).get('m_IsActive',True))
        value=(pm@trs(t),active);worlds[ident]=value;return value
    def object_pose(obj):
        go=source.ref(obj,source.tree(obj).get('m_GameObject'))
        if go is None:raise ValueError('Missing GameObject')
        comps=components(go);tr=next((c for c in comps if c and c.type.name=='Transform'),None)
        if tr is None:raise ValueError('Missing Transform')
        matrix,active=world(tr)
        return go,comps,matrix,active
    for path,node,family,mode in selected:
        vg={'scene':node,'mapFamily':family,'mode':mode,'modeTypes':[],'items':[]}
        tg={'scene':node,'mapFamily':family,'mode':mode,'modeTypes':[],'items':[]}
        volumes['sets'].append(vg);tactical['sets'].append(tg)
        try:
            source.load(path);file=source.file(node)
            log(f'Reading gameplay: {node}')
            for obj in file.objects.values():
                if obj.type.name!='MonoBehaviour':continue
                dest=None
                try:
                    t=source.tree(obj)
                    if not t.get('m_Script',{}).get('m_PathID'):continue
                    script=source.script_name(obj,t)
                    if not script:raise ValueError('Unresolved script identity')
                    if script=='ModeDetail':
                        vg['modeTypes']=tg['modeTypes']=jsonable(t.get('ModeTypes',[]));continue
                    if script in VOLUMES and include_volumes:dest=volumes;group=vg
                    elif script in TACTICAL and include_tactical:dest=tactical;group=tg
                    else:continue
                    go,comps,matrix,active=object_pose(obj)
                    entry={'id':key(obj),'uid':t.get('UID'),'name':source.tree(go).get('m_Name',''),'kind':script,
                           'enabled':bool(t.get('m_Enabled',True)),'hierarchyActive':active,**pose(matrix),
                           'sourceProperties':jsonable({k:v for k,v in t.items() if k not in ('m_GameObject','m_Script')})}
                    group['items'].append(entry)
                    if script in OBJECTIVES:
                        entry['objectiveId']=t.get('ObjectiveID')
                        entry['additionalTriggerIds']=[]
                        for field in ('AdditionalTriggers','AdditionalTriggers_Dom'):
                            for pointer in t.get(field,[]):
                                target=source.ref(obj,pointer)
                                if target:entry['additionalTriggerIds'].append(key(target))
                    if script=='NavMeshModifierVolume':
                        entry.update(areaId=t.get('m_Area'),affectedAgents=jsonable(t.get('m_AffectedAgents',[])),
                                     shapes=[shape_data('BoxCollider',t,matrix)],shapeStatus='complete',
                                     shapeSource='component_fields',solidCollision=False)
                        continue
                    if script=='LadderEnterVolume':
                        target=source.ref(obj,t.get('TargetLadderVolume'))
                        entry['targetLadderId']=key(target) if target else None
                    if dest is volumes:
                        shapes={key(c):c for c in comps if c and c.type.name.endswith('Collider')}
                        for pointer in t.get('colliders',[]):
                            c=source.ref(obj,pointer)
                            if c:shapes[key(c)]=c
                        if script in OBJECTIVES:
                            visited={key(obj)}
                            def add_trigger(trigger):
                                if trigger is None or key(trigger) in visited:return
                                visited.add(key(trigger))
                                if trigger.type.name.endswith('Collider'):
                                    shapes[key(trigger)]=trigger;return
                                tt=source.tree(trigger)
                                _,tc,_,_=object_pose(trigger)
                                for c in tc:
                                    if c and c.type.name.endswith('Collider'):shapes[key(c)]=c
                                for p in tt.get('colliders',[]):
                                    c=source.ref(trigger,p)
                                    if c:shapes[key(c)]=c
                                for field in ('AdditionalTriggers','AdditionalTriggers_Dom'):
                                    for p in tt.get(field,[]):add_trigger(source.ref(trigger,p))
                            for field in ('AdditionalTriggers','AdditionalTriggers_Dom'):
                                for pointer in t.get(field,[]):add_trigger(source.ref(obj,pointer))
                        entry['shapes']=[];entry['shapeStatus']='complete'
                        for c in shapes.values():
                            try:
                                _,_,cm,ca=object_pose(c)
                                shape=shape_data(c.type.name,source.tree(c),cm)
                                shape.update(id=key(c),hierarchyActive=ca);entry['shapes'].append(shape)
                            except Exception as e:
                                entry['shapeStatus']='partial';dest['errors'].append({'scene':node,'id':key(c),'error':str(e)})
                        if not shapes:
                            entry['shapeStatus']='missing';dest['errors'].append({'scene':node,'id':key(obj),'error':'No attached or explicitly referenced collider'})
                    else:
                        entry['links']={}
                        if script=='ClimbSpot':
                            entry['endpoints']={};entry['endpointStatus']='complete'
                            for field in ('startPoint','endPoint'):
                                target=source.ref(obj,t.get(field))
                                if target:
                                    _,_,tm,ta=object_pose(target)
                                    entry['endpoints'][field]={'id':key(target),'hierarchyActive':ta,**pose(tm)}
                                else:
                                    entry['endpointStatus']='partial'
                                    dest['errors'].append({'scene':node,'id':key(obj),'error':f'Missing climb {field}'})
                            height=float(t.get('height',0))
                            if not np.isfinite(height):raise ValueError('Non-finite climb height')
                            entry.update(height=height/.0254,glbHeightMetres=height,climbType=t.get('climbType'))
                        for field,value in t.items():
                            if field in ('m_GameObject','m_Script'):continue
                            if isinstance(value,dict) and value.get('m_PathID'):
                                target=source.ref(obj,value)
                                entry['links'][field]=key(target) if target else None
                except Exception as e:
                    targets=[dest] if dest else ([volumes] if include_volumes else [])+([tactical] if include_tactical else [])
                    for target in targets:target['errors'].append({'scene':node,'id':key(obj),'error':str(e)})
        except Exception as e:
            for target,enabled in [(volumes,include_volumes),(tactical,include_tactical)]:
                if enabled:target['errors'].append({'scene':node,'error':str(e)})
    for result,enabled in [(volumes,include_volumes),(tactical,include_tactical)]:
        result['sets']=[g for g in result['sets'] if g['items']]
        result['count']=sum(len(g['items']) for g in result['sets']);result['sourceBundles']=sorted(source.loaded)
        result['complete']=not result['errors']
        result['status']='disabled' if not enabled else 'partial' if result['errors'] else 'found' if result['count'] else 'not_found'
    return volumes,tactical
