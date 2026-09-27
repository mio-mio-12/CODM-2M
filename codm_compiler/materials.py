import hashlib
import json
import re
import copy
from pathlib import Path
import numpy as np
from PIL import Image
from .source import key, jsonable


def safe_name(s):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', s)[:100] or 'unnamed'


def visible_pass_state(shader, material, floats):
    form=shader.get('m_ParsedForm',{})
    defaults={}
    for prop in form.get('m_PropInfo',{}).get('m_Props',[]):
        value=prop.get('m_DefValue',[])
        if isinstance(value,(list,tuple)) and value:defaults[prop.get('m_Name')]=value[0]
    values={**defaults,**floats}
    def resolve(entry):
        if not isinstance(entry,dict):return None
        name=entry.get('name','')
        if name and name!='<noninit>':return values.get(name)
        return entry.get('val')
    subs=form.get('m_SubShaders',[])
    if not subs:return {}
    disabled={n.lower() for n in material.get('disabledShaderPasses',[])}
    sub=subs[0]
    for p in sub.get('m_Passes',[]):
        st=p.get('m_State',{});name=st.get('m_Name',p.get('m_Name',''))
        tags=dict(sub.get('m_Tags',{}).get('tags',[]));tags.update(st.get('m_Tags',{}).get('tags',[]))
        mode=next((v for k,v in tags.items() if k.lower()=='lightmode'),'').lower()
        if name.lower() in disabled or mode in ('shadowcaster','meta','depthonly','depthnormals','forwardadd','motionvectors'):
            continue
        blend=st.get('rtBlend0',{})
        if resolve(blend.get('colMask'))==0:continue
        result={'pass':name,'lightMode':mode,'tags':tags}
        for key,entry in [('srcBlend',blend.get('srcBlend')),('dstBlend',blend.get('destBlend')),
                          ('blendOp',blend.get('blendOp')),('cull',st.get('culling'))]:
            value=resolve(entry)
            if value is not None:result[key]=int(value)
        if any(k in result for k in ('srcBlend','dstBlend','cull')):return result
    return {}


class Materials:
    def __init__(self, source, output, max_texture=2048):
        self.source=source;self.output=Path(output);self.max_texture=max_texture
        self.items=[];self.cache={};self.images={};self.failures=[]
        (self.output/'images').mkdir(parents=True,exist_ok=True)
        (self.output/'source_materials').mkdir(parents=True,exist_ok=True)

    def texture(self, obj, usage='color'):
        k=(key(obj),usage)
        if k in self.images:return self.images[k]
        data=obj.read()

        stream=getattr(data,'m_StreamData',None)
        path=getattr(stream,'path','') if stream else ''
        if path:self.source.file(path)
        im=data.image.convert('RGBA')
        if usage in ('normal','packed_normal'):
            a=np.asarray(im,dtype=np.float32)/255

            fmt=int(getattr(data,'m_TextureFormat',0))
            x=(a[:,:,0]*a[:,:,3] if fmt in (12,) and usage=='normal' else a[:,:,0])*2-1
            y=a[:,:,1]*2-1
            z=np.sqrt(np.maximum(0,1-x*x-y*y))
            im=Image.fromarray(np.uint8(np.clip(np.stack([x,y,z],axis=2)*.5+.5,0,1)*255),'RGB')
        if self.max_texture and max(im.size)>self.max_texture:
            im.thumbnail((self.max_texture,self.max_texture),Image.Resampling.LANCZOS)
        name=safe_name(data.m_Name)+'_'+hashlib.sha256(repr(k).encode()).hexdigest()[:10]+'.png'
        relative='images/'+name;im.save(self.output/relative,compress_level=1)
        self.images[k]=relative
        return relative

    def get(self,obj,force_decal=False):
        if obj is None:
            k=('missing',force_decal)
        else:k=(key(obj),force_decal)
        if k in self.cache:return self.cache[k]
        idx=len(self.items);self.cache[k]=idx
        mat={'name':'missing_material','color':[1,0,1,1],'metallic':0.,'roughness':.85,
             'alpha':'OPAQUE','cutoff':.5,'doubleSided':False,'decal':force_decal,'blend':'alpha',
             'textures':{},'uv_scale':[1,1],'uv_offset':[0,0],'source':None}
        self.items.append(mat)
        if obj is None:
            self.source.warnings.append('Renderer has a missing material; exported diagnostic magenta')
            return idx
        t=self.source.tree(obj);mat['source']=key(obj);mat['name']=t.get('m_Name','material')
        props=t.get('m_SavedProperties',{})
        floats=dict(props.get('m_Floats',[])); colors=dict(props.get('m_Colors',[]));tex=dict(props.get('m_TexEnvs',[]))
        shader='';st={}
        try:
            so=self.source.ref(obj,t.get('m_Shader'))
            st=self.source.tree(so) if so else {}
            shader=st.get('m_Name') or st.get('m_ParsedForm',{}).get('m_Name','')
        except Exception as e:self.source.warnings.append(f"Shader for {mat['name']}: {e}")
        text=(mat['name']+' '+shader+' '+t.get('m_ShaderKeywords','')).lower()
        src,dst=int(floats.get('_SrcBlend',-1)),int(floats.get('_DstBlend',-1))


        screen_fx=shader in ('CODM/FX/TVScanLineAdd','CODM/FX/CodmKGTVScreen')
        pass_state=visible_pass_state(st,t,floats)
        src=pass_state.get('srcBlend',src);dst=pass_state.get('dstBlend',dst)
        if pass_state:mat['resolvedRenderState']=pass_state
        mat['decal']=force_decal or any(x in (mat['name']+' '+shader).lower() for x in ('decal','projector'))
        known_blend='srcBlend' in pass_state and 'dstBlend' in pass_state
        if ((src,dst) in ((2,0),(0,3)) and pass_state.get('blendOp',0)==0
                or not known_blend and 'multiply' in shader.lower()):mat['blend']='multiply'
        elif (dst==1 and src in (1,5) and pass_state.get('blendOp',0)==0
              or not known_blend and 'additive' in shader.lower()):mat['blend']='additive'
        mode=int(floats.get('_Mode',0));queue=t.get('m_CustomRenderQueue',-1)
        tags={**pass_state.get('tags',{}),**dict(t.get('stringTagMap',[]))}
        if ('_alphatest_on' in text or '_static_foliage' in text or mode==1 or 'cutout' in text
                or tags.get('RenderType','').lower()=='transparentcutout' or floats.get('_AlphaClip',0)>0):
            mat['alpha']='MASK'
        elif mode in (2,3) or dst in (1,10) or queue>=3000 or mat['decal'] or 'transparent' in shader.lower():
            mat['alpha']='BLEND'
        if mat['blend']!='alpha':
            mat['decal']=True;mat['alpha']='BLEND'
            self.source.warnings.append(f"{mat['name']}: {mat['blend']} blending is preserved in C2M; GLB uses alpha fallback")
        mat['cutoff']=float(floats.get('_Cutoff',.5));mat['doubleSided']=floats.get('_Cull',floats.get('_cull',2))==0
        if 'cull' in pass_state:mat['doubleSided']=pass_state['cull']==0
        color=colors.get('_BaseColor',colors.get('_Color',{'r':1,'g':1,'b':1,'a':1}))
        mat['color']=[float(color.get(c,1)) for c in 'rgba']
        if (shader=='UnityBuiltIn/Unlit/Texture' and '_STATIC_COLOR' in t.get('m_ShaderKeywords','')
                and not any(env.get('m_Texture',{}).get('m_PathID') for env in tex.values())
                and '_TintColor' in colors):
            mat['color']=[float(colors['_TintColor'].get(c,1)) for c in 'rgba']
            mat['staticColorSource']='_TintColor'
        mat['metallic']=float(np.clip(floats.get('_Metallic',0),0,1))
        mat['roughness']=float(np.clip(1-floats.get('_Glossiness',floats.get('_Smoothness',.15)),0,1))
        mat['shader']=shader;mat['renderQueue']=queue;mat['srcBlend']=src;mat['dstBlend']=dst
        mat['vertexTint']='_static_albedotintvertex' in text
        mat['vertexWind']='_wind_wave' in text and shader=='CODStandard Foliage'
        mat['sky']='sky' in shader.lower() or 'skybox' in mat['name'].lower()
        mat['unlit']='unlit' in shader.lower()
        roles={'color':('_BaseMap','_MainTex','_BaseColorMap','_DiffuseTex','_Diffuse','_BaseTexture','_Tex'),
               'normal':('_BumpMap','_NormalMap','_NormalTex','_BumpMapPakced','_BaseNormal'),
               'emissive':('_EmissionMap',), 'metallic':('_MetallicGlossMap',)}
        selected=set();mat['textureSlots']={}
        vectors=dict(props.get('m_VectorArrays',[]))
        if '_texture_atlasing_on' in text:
            mat['atlas']={'new':bool(floats.get('_New_Atlasing_Data',0)),
                          'transforms':{name:[v[k] for v in values for k in 'xyzw'] for name,values in vectors.items() if name.endswith('_AtlasTrans')}}
        for usage,names in roles.items():
            slot=next((n for n in names if n in tex and tex[n].get('m_Texture',{}).get('m_PathID')),None)
            if not slot:continue
            selected.add(slot);env=tex[slot]
            try:
                texture=self.source.ref(obj,env['m_Texture'])
                if texture.type.name!='Texture2D':
                    self.source.preserve(texture,self.output/'source_textures',slot)
                    self.source.warnings.append(f"{mat['name']}/{slot}: {texture.type.name} preserved as raw source; not a 2D material texture")
                    continue
                path=self.texture(texture,('packed_normal' if slot=='_BumpMapPakced' else 'normal') if usage=='normal' else 'color')
                if usage=='metallic':
                    im=np.asarray(Image.open(self.output/path).convert('RGBA')).copy()

                    packed=np.zeros_like(im);packed[:,:,0]=255;packed[:,:,1]=255-im[:,:,3];packed[:,:,2]=im[:,:,0];packed[:,:,3]=255
                    path=str(Path(path).with_stem(Path(path).stem+'_mr')).replace('\\','/')
                    Image.fromarray(packed).save(self.output/path,compress_level=1)
                    mat['metallic']=1.;mat['roughness']=1.
                mat['textures'][usage]=path
                mat['textureSlots'][usage]=slot
                scale=env.get('m_Scale',{'x':1,'y':1});off=env.get('m_Offset',{'x':0,'y':0})
                if usage=='color':
                    mat['uv_scale']=[scale['x'],scale['y']];mat['uv_offset']=[off['x'],off['y']]
                elif shader!='CODM/Terrain/3Tex_VertexBlend_NormSpecRealtime' and ([scale['x'],scale['y']]!=mat['uv_scale'] or [off['x'],off['y']]!=mat['uv_offset']):
                    self.source.warnings.append(f"{mat['name']}: {slot} uses a separate UV transform; preserved in source material")
            except Exception as e:
                self.failures.append({'material':mat['name'],'slot':slot,'error':str(e)})
                self.source.warnings.append(f"Texture {mat['name']}/{slot}: {e}")
        emission=colors.get('_EmissionColor',{})
        mat['emissive']=[float(np.clip(emission.get(c,0),0,1)) for c in 'rgb']
        if 'emissive' in mat['textures'] and not any(mat['emissive']):mat['emissive']=[1,1,1]
        if screen_fx and 'color' in mat['textures']:


            tint=colors.get('_MainColor',{'r':1,'g':1,'b':1,'a':1})
            mat['color']=[float(np.clip(tint.get(c,1),0,1)) for c in 'rgba']
            mat['unlit']=True;mat['emissive']=[0,0,0]
            mat['staticFX']={'animation':'not baked','sourceShader':shader}
            if shader=='CODM/FX/CodmKGTVScreen':mat['alpha']='OPAQUE'
            self.source.warnings.append(f"{mat['name']}: exported static screen artwork; animated distortion/scanlines are preserved in source material")
        if mat['blend']=='additive' and 'color' in mat['textures']:


            if not screen_fx and '_TintColor' in colors:
                tint=colors['_TintColor'];brightness=max(0,float(floats.get('_Brightness',1)))
                mat['color']=[max(0,float(tint.get(c,1)))*brightness for c in 'rgb']+[float(np.clip(tint.get('a',1),0,1))]
            mat['unlit']=True;mat['emissive']=[0,0,0]
            mat['glbColorTexture']=self.additive_preview(mat)
            mat['glbColorFactor']=[1,1,1,1]
            mat['additivePreview']={'method':'linear_radiance_to_straight_alpha',
                                    'sourceTexture':mat['textures']['color'],
                                    'glbBlend':'alpha approximation; exact over black within LDR range'}
            if screen_fx:mat['staticFX']['glbBlend']='alpha approximation, exact over black only'
        extras={}
        for slot,env in tex.items():
            if slot in selected or not env.get('m_Texture',{}).get('m_PathID'):continue
            try:extras[slot]=self.texture(self.source.ref(obj,env['m_Texture']))
            except Exception as e:extras[slot]={'error':str(e)}
        from .blending import SHADER
        if shader==SHADER:
            recipe={'shader':shader,'keywords':t.get('m_ShaderKeywords','').split(),'floats':floats,'textures':{}}
            for slot in ('_BaseTexture','_BaseNormal','_Albedo1','_Normal1','_Albedo2'):
                env=tex.get(slot,{})
                if not env.get('m_Texture',{}).get('m_PathID'):continue
                try:
                    texture=self.source.ref(obj,env['m_Texture'])
                    path=self.texture(texture,'color')
                    scale=env.get('m_Scale',{'x':1,'y':1});off=env.get('m_Offset',{'x':0,'y':0})
                    recipe['textures'][slot]={'path':path,'srgb':slot not in ('_BaseNormal','_Normal1'),
                        'transform':[scale['x'],scale['y'],off['x'],off['y']]}
                except Exception as e:
                    self.failures.append({'material':mat['name'],'slot':slot,'error':str(e)})

            for normal,albedo in (('_BaseNormal','_BaseTexture'),('_Normal1','_Albedo1')):
                if normal in recipe['textures'] and albedo in recipe['textures']:
                    recipe['textures'][normal]['transform']=recipe['textures'][albedo]['transform'][:]
            mat['vertexBlend']=recipe;mat['color']=[1,1,1,1]
        TERRAIN_MASK='CODM/Terrain/4Tex_Mask_Terrain'
        if shader==TERRAIN_MASK:
            recipe={'shader':shader,'textures':{},'basis':{},'controlWorldScale':1/1024,
                    'sourceKeywords':t.get('m_ShaderKeywords','').split()}
            for slot in ('_Control','_Splat0','_Splat1','_Splat2','_Splat3'):
                env=tex.get(slot,{})
                if not env.get('m_Texture',{}).get('m_PathID'):
                    self.failures.append({'material':mat['name'],'slot':slot,'error':'Missing required terrain texture'})
                    continue
                try:
                    texture=self.source.ref(obj,env['m_Texture'])
                    path=self.texture(texture)
                    scale=env.get('m_Scale',{'x':1,'y':1});off=env.get('m_Offset',{'x':0,'y':0})
                    recipe['textures'][slot]={'path':path,'transform':[scale['x'],scale['y'],off['x'],off['y']]}
                except Exception as e:self.failures.append({'material':mat['name'],'slot':slot,'error':str(e)})
            for i in range(4):
                recipe['basis'][str(i)]={role:[float(colors.get(f'_Splat{i}_{role}',{}).get(c,default))
                                       for c,default in zip('rgb',(0,0,0) if role!='Offset' else (0.5,0.5,0.5))]
                                       for role in ('BasisX','BasisY','Offset')}
            if len(recipe['textures'])==5:
                mat['terrainMask']=recipe;mat['color']=[1,1,1,1]
                self.source.warnings.append(f"{mat['name']}: four-layer terrain baked from control mask and PCA splats")
        if extras and shader not in (SHADER,TERRAIN_MASK):
            self.source.warnings.append(f"{mat['name']}: additional shader textures preserved, not composited: {', '.join(extras)}")
        if mat['name'].lower().startswith('empty') and '_donotmodify' in mat['name'].lower() and not mat['textures']:
            mat['unresolvedPlaceholder']=True
            self.source.warnings.append(f"{mat['name']}: visible renderer uses an untextured source placeholder; retained without guessing a replacement texture")
        record={'source':jsonable(t),'shader':shader,'export':mat,'additional_textures':extras}
        token=hashlib.sha256(repr(k).encode()).hexdigest()[:16]
        (self.output/'source_materials'/f'{token}.json').write_text(json.dumps(record,indent=2),'utf-8')
        return idx

    def additive_preview(self,mat):
        from .blending import linear,srgb
        path=mat['textures']['color']
        a=np.asarray(Image.open(self.output/path).convert('RGBA'),dtype=np.float32)/255
        emitted=linear(a[:,:,:3])*np.asarray(mat['color'][:3])
        if mat['srcBlend']==5:emitted*=a[:,:,3:4]*mat['color'][3]
        alpha=np.clip(emitted.max(axis=2,keepdims=True),0,1)
        rgb=srgb(np.divide(emitted,alpha,out=np.zeros_like(emitted),where=alpha>0))
        pixels=np.concatenate((np.clip(rgb,0,1),alpha),axis=2)
        token=hashlib.sha256(repr((path,mat['color'],mat['srcBlend'])).encode()).hexdigest()[:12]
        dest=f'images/additive_preview_{token}.png'
        Image.fromarray(np.rint(pixels*255).astype(np.uint8)).save(self.output/dest,compress_level=1)
        return dest

    def atlas_variant(self, index, slot_index):
        cache_key=('atlas',index,int(slot_index))
        if cache_key in self.cache:return self.cache[cache_key]
        base=self.items[index];atlas=base.get('atlas')
        if not atlas:return index
        variant=copy.deepcopy(base);variant['name']+=f'_tile_{slot_index}'
        for role,path in base['textures'].items():
            slot=base['textureSlots'].get(role,'')
            transforms=atlas['transforms'].get(slot+'_AtlasTrans')
            if not transforms:continue
            if slot_index>=len(transforms):raise ValueError(f'Atlas index {slot_index} exceeds {slot} transform table')
            packed=int(transforms[slot_index]);x,y,w,h=atlas_rect(packed,atlas['new'])
            im=Image.open(self.output/path)

            box=(round(x*im.width),round((1-y-h)*im.height),round((x+w)*im.width),round((1-y)*im.height))
            if box[0]<0 or box[1]<0 or box[2]>im.width or box[3]>im.height or box[2]<=box[0] or box[3]<=box[1]:
                raise ValueError(f'Invalid atlas rectangle {box} for {slot}')
            cropped=im.crop(box)

            if min(cropped.size)>4:cropped=cropped.crop((1,1,cropped.width-1,cropped.height-1))
            target=str(Path(path).with_stem(Path(path).stem+f'_tile_{slot_index}_{packed}')).replace('\\','/')
            cropped.save(self.output/target,compress_level=1);variant['textures'][role]=target
        variant['atlasSlot']=int(slot_index)
        if variant.get('glbColorTexture') and variant['blend']=='additive':
            variant['glbColorTexture']=self.additive_preview(variant)
            variant['additivePreview']['sourceTexture']=variant['textures']['color']
        result=len(self.items);self.items.append(variant);self.cache[cache_key]=result;return result


def atlas_rect(packed,new=False):
    if new:
        return ((packed>>15&127)/128,(packed>>8&127)/128,(1<<(packed>>4&15))/8192,(1<<(packed&15))/8192)
    size=((packed&15)+1)/16
    return ((packed>>8&15)/16,(packed>>4&15)/16,size,size)
