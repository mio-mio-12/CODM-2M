import argparse
import json
from pathlib import Path
import sys


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--ui-smoke':
        import traceback
        try:
            from .imgui_ui import launch
            launch(test_frames=20,screenshot=sys.argv[2]);return 0
        except Exception:
            Path(sys.argv[2]+'.log').write_text(traceback.format_exc(),encoding='utf-8');return 1
    if len(sys.argv)==3 and sys.argv[1]=='--worker':
        from .jobs import execute_job
        return execute_job(Path(sys.argv[2]))
    p=argparse.ArgumentParser(description='Compile installed COD Mobile scenes to GLB or C2M with separate authored collision.')
    from .version import APP_NAME
    p.add_argument('--version',action='version',version=APP_NAME)
    sub=p.add_subparsers(dest='command')
    scan=sub.add_parser('scan');scan.add_argument('root');scan.add_argument('--catalog',default='catalog.json')
    ls=sub.add_parser('list');ls.add_argument('--catalog',default='catalog.json');ls.add_argument('--filter',default='')
    export=sub.add_parser('export');export.add_argument('--catalog',default='catalog.json');export.add_argument('--scene',action='append',required=True)
    export.add_argument('--out',required=True);export.add_argument('--format',choices=['both','c2m','glb'],default='both')
    export.add_argument('--texture-size',type=int,choices=[0,512,1024,2048,4096],default=2048);export.add_argument('--include-inactive',action='store_true')
    export.add_argument('--baking',choices=['auto','cpu'],default='auto')
    for option in ('spawns','volumes','tactical'):export.add_argument('--no-'+option,action='store_true')
    check=sub.add_parser('inspect');check.add_argument('file')
    sp=sub.add_parser('spawns',help='Extract spawn points without converting map geometry')
    sp.add_argument('--catalog',default='catalog.json');sp.add_argument('--scene',action='append',required=True)
    sp.add_argument('--out',required=True,help='New JSON sidecar path')
    args=p.parse_args()
    try:
        if not args.command:
            from .imgui_ui import launch
            launch();return 0
        if args.command=='scan':
            from .catalog import scan
            scan(args.root,args.catalog)
        elif args.command=='list':
            from .catalog import scene_labels
            catalog=json.loads(Path(args.catalog).read_text('utf-8'))
            for label,m in scene_labels(catalog):
                if args.filter.lower() in label.lower():print(label)
        elif args.command=='export':
            from .compiler import Compiler
            out=Path(args.out)
            if out.exists() and any(out.iterdir()):raise ValueError('Choose a new or empty output folder; existing exports are never overwritten')
            result=Compiler(json.loads(Path(args.catalog).read_text('utf-8')),out,max_texture=args.texture_size,
                            include_inactive=args.include_inactive,baking=args.baking).run(args.scene,('c2m','glb') if args.format=='both' else (args.format,),
                            [name for name in ('spawns','volumes','tactical') if not getattr(args,'no_'+name)])
            return 2 if not result['extractionComplete'] or not result.get('spawnComplete',True) or not result.get('gameplayComplete',True) else 0
        elif args.command=='spawns':
            from .spawns import extract_spawns,write_spawns
            from .catalog import scene_labels
            catalog=json.loads(Path(args.catalog).read_text('utf-8'))
            labels=[label for label,_ in scene_labels(catalog)]
            if any(labels.count(scene)!=1 for scene in args.scene):raise ValueError('Choose exact, unique visual scene labels from the catalog')
            out=Path(args.out)
            if out.exists():raise ValueError('Choose a new sidecar path; existing files are never overwritten')
            out.parent.mkdir(parents=True,exist_ok=True)
            result=extract_spawns(catalog,args.scene);write_spawns(out,result)
            print(f"Spawn points: {result['spawnCount']} ({result['status']}) -> {out}")
            return 0 if result['complete'] else 2
        elif args.command=='inspect':
            from .formats import read_extension
            data=read_extension(args.file)
            print(json.dumps({tag:{k:v for k,v in value.items() if k not in ('colliders','assets','visualMaterials','loadedBundles')} for tag,value in data.items()},indent=2))
        return 0
    except Exception as e:
        print(f'ERROR: {e}',file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
