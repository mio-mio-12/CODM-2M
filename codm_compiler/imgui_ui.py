"""Dear ImGui frontend. Heavy tasks run in disposable, hidden worker processes."""
import json
import configparser
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from datetime import datetime
from .version import APP_NAME
from .map_library import library,match_preview,cached_previews
from .materials import safe_name


class BrowserState:
    def __init__(self,base=None):
        self.base=Path(base) if base else Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
        self.cache=self.base/'catalog.json';self.previews=self.base/'map_previews'
        self.settings=self.base/'settings.ini'
        self.source='';self.output=str(self.base/'exports')
        try:
            settings=configparser.ConfigParser(interpolation=None)
            settings.read(self.settings,encoding='utf-8')
            saved=settings.get('paths','codm_directory',fallback='').strip()
            if saved and Path(saved).is_dir():self.source=saved
        except (OSError,configparser.Error,UnicodeError):pass
        self.catalog=None;self.entries=[];self.pictures=[];self.matches={};self.selected=set();self.variant=0
        self.query='';self.category=0;self.advanced=False;self.geometry=True;self.c2m=True;self.glb=True
        self.spawns=True;self.volumes=True;self.tactical=True;self.inactive=False;self.quality=2;self.baking=0
        self.status='Ready';self.error='';self.counts={};self.last_output=None;self.process=None;self.job=None
        self.dialog=None;self.dialog_field=None;self.started=0.;self.elapsed=0.;self.scan_job=False
        self.zone_index=None;self.zone_cells=set();self.zone_layers=set();self.zone_name='Zone';self.zone_open=False
        self.zone_queue=[];self.zone_manifest=None;self.zone_current=None;self.zone_out=None;self.index_job=False
        self.zone_presets={};self.zone_preset=0
        self.load_cache()

    def load_cache(self):
        try:
            self.catalog=json.loads(self.cache.read_text(encoding='utf-8'))
            if not self.source or Path(self.catalog['root']).resolve()!=Path(self.source).resolve():
                self.catalog=None;self.entries=[];return
            cached=cached_previews(self.catalog,self.previews)
            self.pictures=cached['images'] if cached else [];self.refresh()
        except (OSError,ValueError,KeyError):self.catalog=None;self.entries=[]

    def refresh(self):
        from .zones import world_scenes
        self.worlds=world_scenes(self.catalog) if self.catalog else {}
        self.entries=library(self.catalog or {'maps':[]},self.advanced)
        valid={e['id'] for e in self.entries};self.selected&=valid
        self.matches={e['id']:match_preview(e,self.pictures) for e in self.entries}
        self.variant=0

    def filtered(self):
        categories=['All','Multiplayer','Zombies','Other / Battle Royale']
        return [e for e in self.entries if self.query.lower() in (e['title']+' '+e['name']).lower()
                and (self.advanced or not self.category or e['category']==categories[self.category])]

    def scenes(self):
        selected=[e for e in self.entries if e['id'] in self.selected]
        if len(selected)==1:return [selected[0]['variants'][min(self.variant,len(selected[0]['variants'])-1)]]
        return [e['variants'][0] for e in selected]

    def can_export(self):
        return bool(not self.process and self.catalog and Path(self.source).resolve()==Path(self.catalog['root']).resolve()
                    and self.scenes() and ((self.geometry and (self.c2m or self.glb)) or self.spawns or self.volumes or self.tactical))

    def start(self,job):
        if self.process:return
        directory=self.base/'.jobs';directory.mkdir(exist_ok=True)
        self.job=directory/(uuid.uuid4().hex+'.json');self.job.write_text(json.dumps(job),encoding='utf-8')
        command=[sys.executable]
        if not getattr(sys,'frozen',False):command+=['-m','codm_compiler']
        command+=['--worker',str(self.job.resolve())]
        env=os.environ.copy()
        if not getattr(sys,'frozen',False):env['PYTHONPATH']=str(self.base)+os.pathsep+env.get('PYTHONPATH','')
        flags=(subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name=='nt' else 0
        self.process=subprocess.Popen(command,cwd=self.base,env=env,stdin=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=flags)
        self.started=time.monotonic();self.scan_job=job['kind']=='scan';self.status='Scanning' if self.scan_job else 'Exporting'
        self.error='';self.counts={}

    def scan(self):
        if not self.source or not Path(self.source).is_dir():
            self.error='Select a CODM directory';return
        self.start({'kind':'scan','source':self.source,'catalog':str(self.cache.resolve()),'previews':str(self.previews.resolve())})

    def set_source(self,value):
        path=Path(value).expanduser().resolve()
        if not path.is_dir():raise ValueError('Select an existing directory')
        settings=configparser.ConfigParser(interpolation=None)
        try:settings.read(self.settings,encoding='utf-8')
        except (configparser.Error,UnicodeError):settings=configparser.ConfigParser(interpolation=None)
        if not settings.has_section('paths'):settings.add_section('paths')
        settings.set('paths','codm_directory',str(path))
        pending=self.settings.with_suffix('.ini.tmp')
        with pending.open('w',encoding='utf-8') as f:settings.write(f)
        pending.replace(self.settings)
        self.source=str(path);self.catalog=None;self.entries=[];self.pictures=[];self.matches={};self.selected.clear()
        self.zone_index=None;self.zone_open=False;self.worlds={}
        self.load_cache()
        if self.catalog is None:self.scan()

    def export(self):
        if not self.can_export():return
        if self.geometry and self.zone_world() and any(s in self.worlds for s in self.scenes()):self.open_zones();return
        entries=[e for e in self.entries if e['id'] in self.selected]
        out=Path(self.output)/(safe_name(entries[0]['title'])+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.start({'kind':'export','catalog':str(self.cache.resolve()),'out':str(out.resolve()),'scenes':self.scenes(),
                    'formats':([n for n,on in [('c2m',self.c2m),('glb',self.glb)] if on] if self.geometry else []),
                    'sidecars':[n for n,on in [('spawns',self.spawns),('volumes',self.volumes),('tactical',self.tactical)] if on],
                    'quality':[512,1024,2048,4096,0][self.quality],'inactive':self.inactive,'baking':['auto','cpu'][self.baking]})

    def zone_world(self):
        if not self.catalog:return None
        worlds=self.worlds
        entries=[e for e in self.entries if e['id'] in self.selected]
        return next((s for e in entries for s in e['variants'] if s in worlds),None) if len(entries)==1 else None

    def open_zones(self):
        from .zones import index_path,signature
        world=self.zone_world()
        if not world or self.process:return
        path=index_path(self.base,world)
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            if data['world']==world and data['signature']==signature(self.catalog):self.set_zone_index(data);return
        except (OSError,ValueError,KeyError):pass
        self.index_job=True
        self.start({'kind':'zones-index','catalog':str(self.cache.resolve()),'scene':world,'index':str(path.resolve())})
        self.status='Indexing zones'

    def set_zone_index(self,data):
        self.zone_index=data;self.zone_cells=set();self.zone_layers=set(data['layers']);self.zone_open=True
        self.zone_name=data['title']+' zone';self.zone_preset=0
        try:self.zone_presets=json.loads((self.base/'zones/presets.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.zone_presets={}

    def save_zone(self):
        from .zones import write_json
        name=self.zone_name.strip()
        if not name:return
        self.zone_presets.setdefault(self.zone_index['world'],{})[name]={'cells':sorted(self.zone_cells),'layers':sorted(self.zone_layers)}
        write_json(self.base/'zones/presets.json',self.zone_presets)

    def zone_plan(self):
        from .zones import plan
        k=(id(self.zone_index),frozenset(self.zone_cells),frozenset(self.zone_layers),self.zone_name)
        if getattr(self,'_zone_plan_key',None)!=k:
            self._zone_plan_value=plan(self.zone_index,self.zone_cells,self.zone_layers,self.zone_name);self._zone_plan_key=k
        return self._zone_plan_value

    def export_zone(self):
        from .zones import write_json
        import copy
        if self.process or not self.geometry or not (self.glb or self.c2m):return
        if Path(self.source).resolve()!=Path(self.catalog['root']).resolve():raise ValueError('Scan the selected source first')
        data=copy.deepcopy(self.zone_plan())
        if not data['chunks']:raise ValueError('No chunks in this selection')
        if any(c['status']!='available' for c in data['chunks']):raise ValueError('Selection contains missing or ambiguous chunks; select another zone or rescan')
        self.zone_out=Path(self.output)/(safe_name(data['name'])+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.zone_out.mkdir(parents=True,exist_ok=False)
        self.zone_manifest=data;self.zone_queue=[];self.zone_current=None
        for i,chunk in enumerate(data['chunks']):
            chunk['folder']=f'{i+1:04d}_'+safe_name(chunk['layerName']+'_'+chunk['name']);chunk['status']='Pending'
            self.zone_queue.append(i)
        data['status']='Exporting';write_json(self.zone_out/'zone.json',data);self.zone_open=False
        self.next_zone_chunk()

    def next_zone_chunk(self):
        from .zones import write_json
        if not self.zone_queue:
            self.zone_manifest['status']='Complete' if all(c['status']=='Complete' for c in self.zone_manifest['chunks']) else 'Partial'
            write_json(self.zone_out/'zone.json',self.zone_manifest);self.status=self.zone_manifest['status'];self.last_output=self.zone_out
            self.zone_current=None;return
        self.zone_current=self.zone_queue.pop(0);chunk=self.zone_manifest['chunks'][self.zone_current]
        chunk['status']='Exporting';write_json(self.zone_out/'zone.json',self.zone_manifest)
        self.start({'kind':'export','catalog':str(self.cache.resolve()),'out':str((self.zone_out/chunk['folder']).resolve()),
                    'scenes':[chunk['scene']],'formats':[n for n,on in [('c2m',self.c2m),('glb',self.glb)] if on],
                    'sidecars':[],'quality':[512,1024,2048,4096,0][self.quality],'inactive':self.inactive,
                    'baking':['auto','cpu'][self.baking],'allow_empty':True})
        self.status=f"Exporting chunk {self.zone_current+1}/{len(self.zone_manifest['chunks'])}"

    def poll(self):
        if self.process:
            self.elapsed=time.monotonic()-self.started
            code=self.process.poll()
            if code is not None:
                self.process=None
                try:
                    result=json.loads(self.job.with_suffix('.result.json').read_text(encoding='utf-8'))
                    self.status=result['status'];self.error=result.get('error','');self.counts=result.get('counts',{})
                    if result.get('out'):self.last_output=Path(result['out'])
                    if self.scan_job and code==0:self.load_cache()
                    if self.index_job and code==0:self.set_zone_index(json.loads(Path(result['index']).read_text(encoding='utf-8')))
                except (OSError,ValueError,KeyError):self.status='Error';self.error=f'Worker exit {code}'
                self.index_job=False
                if self.zone_current is not None:
                    from .zones import write_json
                    chunk=self.zone_manifest['chunks'][self.zone_current];chunk['status']=self.status;chunk['counts']=self.counts;chunk['error']=self.error
                    report_path=self.zone_out/chunk['folder']/'report.json'
                    if report_path.is_file():
                        report=json.loads(report_path.read_text(encoding='utf-8'));chunk['visualStatus']=report.get('visualStatus')
                    write_json(self.zone_out/'zone.json',self.zone_manifest);self.next_zone_chunk()
        if self.dialog and self.dialog.ready(0):
            result=self.dialog.result()
            if result:
                try:
                    if self.dialog_field=='source':self.set_source(result)
                    else:setattr(self,self.dialog_field,result)
                except Exception as e:self.error=str(e)
            self.dialog=None

    def cancel(self):
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            self.process=None;self.status='Cancelled'
            if self.zone_current is not None:
                from .zones import write_json
                self.zone_manifest['chunks'][self.zone_current]['status']='Cancelled';self.zone_manifest['status']='Cancelled'
                write_json(self.zone_out/'zone.json',self.zone_manifest);self.last_output=self.zone_out
                self.zone_current=None;self.zone_queue=[]
            self.index_job=False


def launch(base=None,test_frames=0,screenshot=None):
    from imgui_bundle import imgui,hello_imgui,portable_file_dialogs as pfd
    state=BrowserState(base);params=hello_imgui.RunnerParams()
    params.app_window_params.window_title=APP_NAME
    params.app_window_params.window_geometry.size=(1180,780)
    params.app_window_params.restore_previous_geometry=False
    params.imgui_window_params.show_menu_bar=False;params.imgui_window_params.show_status_bar=False
    params.ini_filename=str(state.base/(APP_NAME+'.ini'));params.ini_filename_use_app_window_title=False
    params.fps_idling.fps_idle=8;params.fps_idling.enable_idling=True;params.fps_idling.fps_max=60
    hello_imgui.set_assets_folder(str(state.base))
    frames=0
    if test_frames:
        candidate=next((e for e in state.entries if 'sbnc' in e['id'].lower()),None)
        if candidate:state.selected={candidate['id']}
        smoke_world=os.environ.get('CODM_UI_SMOKE_WORLD')
        if smoke_world:
            candidate=next(e for e in state.entries if smoke_world in e['variants']);state.selected={candidate['id']}
            state.open_zones()
            if state.zone_index:
                state.zone_cells={state.zone_index['cells'][len(state.zone_index['cells'])//2]['id']}
    def init():
        imgui.style_colors_dark();s=imgui.get_style();s.window_padding=(12,12);s.frame_padding=(8,6)
        s.item_spacing=(10,8);s.frame_rounding=3;s.child_rounding=3
        if not state.source and not test_frames:
            state.dialog=pfd.select_folder('CODM directory','');state.dialog_field='source'
        elif state.source and state.catalog is None and not test_frames:state.scan()
    def photo(entry,size):
        picture=state.matches.get(entry['id'])
        if picture and (state.previews/picture['file']).is_file():
            hello_imgui.image_from_asset('map_previews/'+picture['file'],size)
        else:imgui.dummy(size)
    def checkbox(label,attr):
        changed,value=imgui.checkbox(label,getattr(state,attr))
        if changed:setattr(state,attr,value)
        return changed

    def draw_zones():
        if not state.zone_open or not state.zone_index:return
        data=state.zone_index
        condition=imgui.Cond_.always if test_frames else imgui.Cond_.first_use_ever
        imgui.set_next_window_pos((35,30),condition)
        imgui.set_next_window_size((1100,710),condition)
        imgui.set_next_window_bg_alpha(1.0)
        visible,state.zone_open=imgui.begin('Zones',state.zone_open)
        if visible:
            imgui.text(data['title']);imgui.same_line();imgui.text('200 m cells | Unity X/Z')
            _,state.zone_name=imgui.input_text('Zone name',state.zone_name);imgui.same_line()
            if imgui.button('Save selection'):state.save_zone()
            presets=state.zone_presets.get(data['world'],{});names=['Saved zones']+sorted(presets)
            changed,state.zone_preset=imgui.combo('##presets',min(state.zone_preset,len(names)-1),names)
            if changed and state.zone_preset:
                name=names[state.zone_preset];p=presets[name];state.zone_name=name
                state.zone_cells=set(p['cells'])&{c['id'] for c in data['cells']};state.zone_layers=set(p['layers'])&set(data['layers'])
            if imgui.button('Clear selection'):state.zone_cells.clear()
            imgui.same_line();imgui.text(f'Selected cells  {len(state.zone_cells)}')
            imgui.begin_child('zone-grid',(0,315),imgui.ChildFlags_.borders)
            cells={(c['x'],c['z']):c for c in data['cells']}
            xs=range(min(x for x,z in cells),max(x for x,z in cells)+1)
            zs=range(max(z for x,z in cells),min(z for x,z in cells)-1,-1)
            width=max(18,min(38,(imgui.get_content_region_avail().x-10)/len(xs)-4))
            for z in zs:
                for col,x in enumerate(xs):
                    if col:imgui.same_line(0,4)
                    cell=cells.get((x,z))
                    if not cell:imgui.dummy((width,23));continue
                    selected=cell['id'] in state.zone_cells
                    if selected:imgui.push_style_color(imgui.Col_.button,(.15,.5,.7,1))
                    if imgui.button(cell['name']+'##'+cell['id'],(width,23)):
                        if selected:state.zone_cells.remove(cell['id'])
                        else:state.zone_cells.add(cell['id'])
                    if selected:imgui.pop_style_color()
                    if imgui.is_item_hovered():
                        a,b,c,d=cell['bounds'];imgui.set_tooltip(f'{cell["name"]}   X {a:g} to {c:g}   Z {b:g} to {d:g} m')
            imgui.end_child()
            for i,(lid,label) in enumerate(data['layers'].items()):
                if i%4:imgui.same_line((i%4)*240+12)
                changed,on=imgui.checkbox(label,lid in state.zone_layers)
                if changed:
                    if on:state.zone_layers.add(lid)
                    else:state.zone_layers.discard(lid)
            checkbox('C2M','c2m');imgui.same_line();checkbox('GLB','glb')
            imgui.same_line();imgui.set_next_item_width(100);_,state.quality=imgui.combo('Textures##zone',state.quality,['512','1024','2048','4096','Original'])
            imgui.same_line();imgui.set_next_item_width(130);_,state.baking=imgui.combo('Baking##zone',state.baking,['Auto (GPU)','CPU'])
            chunks=[]
            if state.zone_cells and state.zone_layers:chunks=state.zone_plan()['chunks']
            missing=sum(c['status']!='available' for c in chunks)
            imgui.text(f'Chunks  {len(chunks)}   Unavailable  {missing}')
            imgui.begin_disabled(not chunks or bool(missing) or state.process is not None or not (state.c2m or state.glb))
            if imgui.button('Export zone',(150,32)):
                try:state.geometry=True;state.export_zone()
                except Exception as e:state.error=str(e)
            imgui.end_disabled()
            if state.error:imgui.text_wrapped(state.error)
        imgui.end()
    def draw():
        nonlocal frames
        state.poll();frames+=1
        imgui.begin_disabled(state.process is not None)
        if imgui.button('Scan'):state.scan()
        imgui.same_line()
        right=imgui.get_cursor_pos_x()+imgui.get_content_region_avail().x-150
        imgui.set_cursor_pos_x(max(imgui.get_cursor_pos_x(),right))
        if imgui.button('CODM directory',(150,0)) and state.dialog is None:
            state.dialog=pfd.select_folder('CODM directory',state.source);state.dialog_field='source'
        if imgui.is_item_hovered():imgui.set_tooltip(state.source or 'CODM directory')
        for label,field in [('Output','output')]:
            imgui.text(label);imgui.same_line(72);imgui.set_next_item_width(max(200,imgui.get_content_region_avail().x-160))
            _,value=imgui.input_text('##'+field,getattr(state,field));setattr(state,field,value)
            imgui.same_line()
            if imgui.button('...##'+field) and state.dialog is None:
                state.dialog=pfd.select_folder(label,getattr(state,field));state.dialog_field=field
            imgui.same_line()
            if field=='source':
                if imgui.button('Scan'):state.scan()
            elif imgui.button('Open'):
                target=state.last_output or Path(state.output)
                if target.is_dir():os.startfile(str(target))
        imgui.separator()
        imgui.set_next_item_width(max(200,imgui.get_content_region_avail().x-400));_,state.query=imgui.input_text('Filter',state.query)
        imgui.same_line();imgui.set_next_item_width(170);_,state.category=imgui.combo('##category',state.category,['All','Multiplayer','Zombies','Battle Royale'])
        imgui.same_line()
        if checkbox('All scenes','advanced'):state.refresh()
        imgui.end_disabled()
        rows=state.filtered();height=max(300,imgui.get_content_region_avail().y-85);left=max(370,imgui.get_content_region_avail().x-395)
        imgui.begin_child('maps',(left,height),imgui.ChildFlags_.borders)
        imgui.text(f'Maps  {len(rows)}');imgui.separator()
        clipper=imgui.ListClipper();clipper.begin(len(rows),60)
        while clipper.step():
            for i in range(clipper.display_start,clipper.display_end):
                entry=rows[i];imgui.push_id(entry['id']);photo(entry,(86,48));imgui.same_line()
                clicked,_=imgui.selectable(entry['title'],entry['id'] in state.selected,size=(0,52))
                if clicked and not state.process:
                    if state.advanced and imgui.get_io().key_ctrl:
                        if entry['id'] in state.selected:state.selected.remove(entry['id'])
                        else:state.selected.add(entry['id'])
                    else:state.selected={entry['id']}
                    state.variant=0
                imgui.pop_id()
        imgui.end_child();imgui.same_line()
        imgui.begin_child('options',(0,height),imgui.ChildFlags_.borders)
        selected=[e for e in state.entries if e['id'] in state.selected]
        if len(selected)==1:
            imgui.text(selected[0]['title']);photo(selected[0],(350,197))
            imgui.begin_disabled(state.process is not None)
            imgui.set_next_item_width(-1);_,state.variant=imgui.combo('##variant',state.variant,selected[0]['variants'])
            if state.zone_world() and imgui.button('Zones',(140,28)):state.open_zones()
            imgui.end_disabled()
        else:imgui.text(f'Selected  {len(selected)}');imgui.dummy((350,197))
        imgui.separator();imgui.begin_disabled(state.process is not None)
        checkbox('Geometry','geometry');imgui.same_line();checkbox('C2M','c2m');imgui.same_line();checkbox('GLB','glb')
        checkbox('Spawns','spawns');checkbox('Gameplay volumes','volumes');checkbox('Tactical markers','tactical')
        checkbox('Inactive objects','inactive')
        imgui.set_next_item_width(160);_,state.quality=imgui.combo('Textures',state.quality,['512','1024','2048','4096','Original'])
        imgui.set_next_item_width(160);_,state.baking=imgui.combo('Baking',state.baking,['Auto (GPU)','CPU'])
        imgui.end_disabled();imgui.separator()
        for name,value in state.counts.items():imgui.text(f'{name.title()}  {value:,}')
        imgui.end_child();imgui.separator()
        imgui.begin_disabled(not state.can_export())
        export_label='Select zone' if state.geometry and state.zone_world() and any(s in state.worlds for s in state.scenes()) else 'Export'
        if imgui.button(export_label,(140,34)):
            try:state.export()
            except Exception as e:state.status='Error';state.error=str(e)
        imgui.end_disabled();imgui.same_line()
        imgui.begin_disabled(state.process is None)
        if imgui.button('Cancel',(100,34)):state.cancel()
        imgui.end_disabled();imgui.same_line();imgui.text(f'{state.status}   {int(state.elapsed)//60:02}:{int(state.elapsed)%60:02}')
        if state.error:imgui.text_wrapped(state.error)
        draw_zones()
        if test_frames and frames>=test_frames:params.app_shall_exit=True
    params.callbacks.post_init=init;params.callbacks.show_gui=draw;params.callbacks.before_exit=state.cancel
    hello_imgui.run(params)
    if screenshot:
        from PIL import Image
        Image.fromarray(hello_imgui.final_app_window_screenshot()).save(screenshot)
