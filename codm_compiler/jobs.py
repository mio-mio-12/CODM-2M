import json
import sys
import traceback
from pathlib import Path
from .version import APP_NAME


def execute_job(path):
    from .spawns import write_spawns,extract_spawns
    from .gameplay import extract_gameplay
    result_path=path.with_suffix('.result.json');log_path=path.with_suffix('.log')
    with log_path.open('w',encoding='utf-8',buffering=1) as log:
        oldout,olderr=sys.stdout,sys.stderr;sys.stdout=sys.stderr=log
        try:
            job=json.loads(path.read_text(encoding='utf-8'))
            def progress(message):
                print(message)
                p=path.with_suffix('.progress.json');tmp=p.with_suffix('.tmp')
                tmp.write_text(json.dumps({'message':message}),encoding='utf-8');tmp.replace(p)
            if job['kind']=='scan':
                from .catalog import scan
                from .map_library import extract_previews
                catalog=scan(job['source'],job['catalog'],log=progress)
                if not job.get('defer_previews'):extract_previews(catalog,job['previews'],log=progress)
                result={'status':'Ready'}
            elif job['kind']=='previews':
                from .map_library import extract_previews
                catalog=json.loads(Path(job['catalog']).read_text(encoding='utf-8'))
                extract_previews(catalog,job['previews'],log=progress)
                result={'status':'Ready'}
            elif job['kind']=='zones-index':
                from .zones import build_index,write_json
                catalog=json.loads(Path(job['catalog']).read_text(encoding='utf-8'))
                data=build_index(catalog,job['scene']);write_json(job['index'],data)
                result={'status':'Ready','index':job['index']}
            else:
                catalog=json.loads(Path(job['catalog']).read_text(encoding='utf-8'))
                out=Path(job['out'])
                if out.exists() and any(out.iterdir()):raise ValueError('Output directory is not empty')
                out.mkdir(parents=True,exist_ok=True)
                options=job['sidecars'];summary={}
                if job['formats']:
                    from .compiler import Compiler
                    report=Compiler(catalog,out,max_texture=job['quality'],include_inactive=job.get('inactive',False),baking=job.get('baking','auto')).run(job['scenes'],job['formats'],options,allow_empty=job.get('allow_empty',False))
                    summary={'triangles':report['triangleCount'],'colliders':report['colliderCount'],'spawns':report['spawnCount'],
                             'volumes':report['gameplaySidecars'].get('volumes',{}).get('count',0),
                             'tactical':report['gameplaySidecars'].get('tactical',{}).get('count',0)}
                    complete=report['extractionComplete'] and report['spawnComplete'] and report['gameplayComplete']
                else:
                    complete=True
                    if 'spawns' in options:
                        data=extract_spawns(catalog,job['scenes']);write_spawns(out/'spawns.json',data)
                        summary['spawns']=data['spawnCount'];complete&=data['complete']
                    if set(options)&{'volumes','tactical'}:
                        v,t=extract_gameplay(catalog,job['scenes'],include_volumes='volumes' in options,include_tactical='tactical' in options)
                        for option,file,data in [('volumes','gameplay_volumes.json',v),('tactical','tactical_markers.json',t)]:
                            if option in options:write_spawns(out/file,data);summary[option]=data['count'];complete&=data['complete']
                result={'status':'Complete' if complete else 'Partial','out':str(out),'counts':summary,'generator':APP_NAME}
            write_spawns(result_path,result)
            return 2 if result['status']=='Partial' else 0
        except Exception as e:
            traceback.print_exc();write_spawns(result_path,{'status':'Error','error':str(e)})
            return 1
        finally:sys.stdout,sys.stderr=oldout,olderr
