import gc
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from .catalog import scene_labels

TRANSLATION=str.maketrans(dict(zip('PKLJMSHGZDBCEVUAYTFRONXWQI','abcdefghijklmnopqrstuvwxyz')))
PREVIEW_VERSION=2


def decoded_name(path):
    return Path(path).stem.translate(TRANSLATION)


def canonical(name):
    name=re.sub(r'^winners_circle_|^Trans_', '', name, flags=re.I)
    parts=re.split(r'[^a-z0-9]+',name.lower())
    return ''.join(p for p in parts if p and p not in {'mp','pvp','cod','codm','final','hq','new','atlases','atlas'})


def title(name):
    name=re.sub(r'^(MP|BR|ZM|PVE|GW|CLY)_','',name,flags=re.I)
    name=re.sub(r'_(Atlases?|Final|HQ|NEW)(?=_|$)','',name,flags=re.I)
    name=re.sub(r'(?<=[a-z])(?=[A-Z])',' ',name).replace('_',' ')
    return name.strip()


def library(catalog, all_scenes=False):
    groups={}
    for label,scene in scene_labels(catalog):
        name=scene['name']
        if all_scenes:
            groups[label]={'id':label,'name':name,'title':name,'category':'Scene','variants':[label],'scope':'Selected scene only'}
            continue
        atlas='atlas' in name.lower()
        main=name.startswith(('BR_','CLY_','GW_')) and name.endswith('_Main')
        if not (atlas or main):continue
        if not name.startswith(('MP_','BR_','ZM_','PVE_','GW_','CLY_')):continue
        display=re.sub(r'_(SR_)?Main$','',name) if main else name
        identity=canonical(display)
        category='Multiplayer' if name.startswith('MP_') else 'Zombies' if name.startswith(('ZM_','PVE_')) else 'Other / Battle Royale'
        display_title=title(display)
        if name.startswith(('BR_','CLY_','GW_')):display_title+=' · '+name.split('_')[0]
        group=groups.setdefault(identity,{'id':identity,'name':display,'title':display_title,'category':category,'variants':[],
            'scope':'Streamed world: this exports the selected main scene, not every terrain tile.' if main else 'Exports the selected visual scene, including its props and materials.'})
        group['variants'].append(label)
        if atlas:group['scope']='Exports the selected visual scene, including its props and materials.'

    for group in groups.values():
        group['variants'].sort(key=lambda n:('atlas' not in n.lower(), 'new' not in n.lower(), n))
    return sorted(groups.values(),key=lambda g:(g['title'].lower(),g['id']))


@lru_cache(maxsize=16384)
def art_key(name):
    name=canonical(name)
    name=re.sub(r'^(br|cly|gw)','',name)
    name=re.sub(r'(2k|4k|hd|1024)$','',name)
    return {'tunisa':'tunisia','docks':'dock','russiannuketown':'nuketownrussian',
            'chinesenuketown':'nuketownchina','zmsumpf':'zmshinonuma',

            'armadawinnercircle00211':'armada','winnercircleseasidea':'seaside'}.get(name,name)


@lru_cache(maxsize=16384)
def edition_key(name):
    return re.sub(r'(cw|bo3|bo4|bo6|christmas|xmas|halloween|02)$','',name)


def match_preview(entry, images):
    identity=art_key(entry['name'])
    ranked=[]
    for image in images:

        if image.get('kind')!='Map artwork' or image['name'].lower().startswith('trans_'):continue
        key=art_key(image['name'])
        exact=key==identity
        related=False
        if not exact:

            related=key==edition_key(identity)
        if exact or related:
            ranked.append(((0 if exact else 1,0 if image['kind']=='Map artwork' else 1,image['name']),image,related))
    if not ranked:return None
    _,image,related=min(ranked,key=lambda v:v[0])
    return {**image,'caption':image['kind']+(' · related edition' if related else '')}


def preview_bundles(catalog):
    return [b for b in catalog.get('bundles',[]) if any(k in decoded_name(b['path']) for k in
            ('textures$ui$winnerscircle','loadingscreen','loading_screen'))]


def preview_signature(catalog):
    return hashlib.sha256(json.dumps([(b['path'],b.get('size'),b.get('mtime')) for b in preview_bundles(catalog)]).encode()).hexdigest()


def cached_previews(catalog, folder):
    folder=Path(folder);path=folder/'index.json'
    try:
        data=json.loads(path.read_text('utf-8'))
        if (data.get('version')==PREVIEW_VERSION and data.get('signature')==preview_signature(catalog)
            and all(i.get('kind')=='Map artwork' and not i['name'].lower().startswith('trans_')
                    and (folder/i['file']).is_file() for i in data['images'])):return data
    except (OSError,ValueError,KeyError):pass
    return None


def extract_previews(catalog, folder, log=print):
    from .source import Source
    import UnityPy
    from PIL import Image
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cached=cached_previews(catalog,folder)
    if cached:return cached
    source=Source(catalog,lambda _:None);images=[];errors=[];bundles=preview_bundles(catalog)
    for i,bundle in enumerate(bundles):
        log(f'Reading map pictures {i+1}/{len(bundles)}')
        source.env=UnityPy.Environment();source.loaded.clear();source.trees.clear()
        try:
            source.load(bundle['path'])
            for file in list(source.env.assets):
                for obj in file.objects.values():
                    if obj.type.name!='Texture2D':continue
                    data=obj.read();name=data.m_Name
                    art=name.lower().startswith('winners_circle_')
                    if not art:continue
                    try:
                        stream=getattr(data,'m_StreamData',None)
                        if stream and stream.path:source.file(stream.path)
                        im=data.image.convert('RGBA');im.thumbnail((640,360),Image.Resampling.LANCZOS)
                        token=hashlib.sha256((bundle['path']+name+str(obj.path_id)).encode()).hexdigest()[:20]+'.png'
                        im.save(folder/token)
                        images.append({'name':name,'file':token,'kind':'Map artwork',
                            'bundle':bundle['path'],'objectId':obj.path_id})
                    except Exception as e:errors.append({'name':name,'error':str(e)})
        except Exception as e:errors.append({'bundle':bundle['path'],'error':str(e)})
        gc.collect()
    result={'version':PREVIEW_VERSION,'signature':preview_signature(catalog),'images':images,'errors':errors}
    temp=folder/'index.tmp';temp.write_text(json.dumps(result,indent=2),'utf-8');temp.replace(folder/'index.json')
    log(f'Ready: {len(images)} map pictures; {len(errors)} picture errors')
    return result
