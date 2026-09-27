import hashlib
import json
from pathlib import Path
import UnityPy
import re
import math


def install_codm_bundle_adapter():
    from UnityPy.files.ObjectReader import ObjectReader
    if getattr(ObjectReader, '_codm_bundle_adapter', False):return
    original=ObjectReader.parse_as_object
    def parse(self,node=None,check_read=True):
        try:return original(self,node,check_read)
        except ValueError as e:
            match=re.fullmatch(r'Expected to read (\d+) bytes, but only read (\d+) bytes',str(e))
            if self.type.name=='AssetBundle' and match and int(match[1])-int(match[2])==4:
                return original(self,node,False)
            raise
    ObjectReader.parse_as_object=parse
    ObjectReader._codm_bundle_adapter=True


def key(obj):
    return f"{obj.assets_file.name}:{obj.path_id}"


def jsonable(value,nonfinite=None,path='$'):


    if isinstance(value,float) and not math.isfinite(value):
        if nonfinite is not None:nonfinite.append(path)
        return {'nonFiniteFloat':'NaN' if math.isnan(value) else '+Infinity' if value>0 else '-Infinity'}
    if isinstance(value, bytes):
        return {"hex":value.hex()}
    if isinstance(value,dict): return {str(k):jsonable(v,nonfinite,path+'.'+str(k)) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [jsonable(v,nonfinite,path+'['+str(i)+']') for i,v in enumerate(value)]
    return value


class Source:
    def __init__(self, catalog, log=print):
        install_codm_bundle_adapter()
        self.catalog=catalog;self.log=log;self.env=UnityPy.Environment()
        self.nodes={};self.loaded=set();self.trees={};self.warnings=[]
        self._typed_files=set();self._typed_env=self.env
        from UnityPy.helpers.TypeTreeNode import TypeTreeNode
        schema=json.loads(Path(__file__).with_name('codm_types.json').read_text('utf-8'))
        self.type_nodes={int(k):TypeTreeNode.from_list(v['nodes']) for k,v in schema.items()}
        for b in catalog['bundles']:
            for node in b['nodes']:
                name=node['name'].lower()
                if name in self.nodes and self.nodes[name]!=b['path']:

                    continue
                self.nodes[name]=b['path']

    def load(self,path):
        if path in self.loaded: return
        self.log(f"Loading {Path(path).name}")
        self.env.load_file(path);self.loaded.add(path)
        if self._typed_env is not self.env:
            self._typed_files.clear();self._typed_env=self.env
        for f in self.env.assets:
            if f in self._typed_files:continue
            if f.unity_version.splitlines()[0]=='5.6.4p4':
                for t in f.types:
                    if not t.node and t.class_id in self.type_nodes:t.node=self.type_nodes[t.class_id]
            self._typed_files.add(f)

    def file(self,name):
        clean=name.replace('\\','/').rsplit('/',1)[-1].lower()
        f=self.env.get_cab(clean)
        if f is not None:return f
        path=self.nodes.get(clean)
        if path:
            self.load(path)
            f=self.env.get_cab(clean)
            if f is not None:return f
        raise FileNotFoundError(f"Missing serialized dependency: {name}")

    def ref(self,owner,ptr):
        if not ptr or not ptr.get('m_PathID'):return None
        file=owner.assets_file if hasattr(owner,'assets_file') else owner
        if ptr['m_FileID']:
            file=self.file(file.externals[ptr['m_FileID']-1].path)
        return file.objects[ptr['m_PathID']]

    def tree(self,obj):
        k=key(obj)
        if k not in self.trees:self.trees[k]=obj.read_typetree()
        return self.trees[k]

    def script_name(self,obj,t):
        try:
            script=self.ref(obj,t.get('m_Script'))
            return self.tree(script).get('m_ClassName', self.tree(script).get('m_Name','')) if script else ''
        except Exception:
            return ''

    def preserve(self,obj,folder,label=None):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        token=hashlib.sha256(key(obj).encode()).hexdigest()[:16]
        path=folder/(token+'.bin');path.write_bytes(obj.get_raw_data())
        entry={'id':key(obj),'type':obj.type.name,'label':label,'raw':path.name}
        try:
            t=self.tree(obj)
            path.with_suffix('.json').write_text(json.dumps(jsonable(t),indent=2), 'utf-8')
            entry['decoded']=path.with_suffix('.json').name
        except Exception as e:entry['decode_error']=str(e)
        return entry
