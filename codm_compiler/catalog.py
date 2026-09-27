import json
import struct
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from collections import Counter


def scene_labels(catalog):
    counts=Counter(m['name'] for m in catalog.get('maps',[]))
    return [(m['name'] if counts[m['name']]==1 else m['name']+' | '+Path(m['path']).name,m) for m in catalog.get('maps',[])]


def cstring(f):
    out = bytearray()
    while len(out) < 4096:
        b = f.read(1)
        if not b:
            raise ValueError("Truncated string")
        if b == b"\0":
            return out.decode("utf-8", "replace")
        out.extend(b)
    raise ValueError("Overlong string")


def directory(path):
    import io
    import lz4.block
    with Path(path).open("rb") as f:
        if cstring(f) != "UnityFS":
            raise ValueError("Not a UnityFS bundle")
        version = struct.unpack(">I", f.read(4))[0]
        player, engine = cstring(f), cstring(f)
        size, compressed, unpacked, flags = struct.unpack(">QIII", f.read(20))
        if size != Path(path).stat().st_size or unpacked > 64 * 1024 * 1024:
            raise ValueError("Invalid bundle bounds")
        if version >= 7:
            f.seek((f.tell()+15)&~15)
        if flags & 128:
            f.seek(size-compressed)
        data = f.read(compressed)
        kind = flags & 63
        if kind in (2, 3):
            data = lz4.block.decompress(data, uncompressed_size=unpacked)
        elif kind != 0:
            raise ValueError(f"Unsupported directory compression {kind}")
        if len(data) != unpacked:
            raise ValueError("Directory length mismatch")
        r = io.BytesIO(data)
        r.seek(16)
        count = struct.unpack(">I", r.read(4))[0]
        if count > len(data)//10:
            raise ValueError("Invalid block count")
        r.seek(count*10, 1)
        count = struct.unpack(">I", r.read(4))[0]
        if count > len(data)//21:
            raise ValueError("Invalid node count")
        nodes = []
        for _ in range(count):
            offset, length, node_flags = struct.unpack(">QQI", r.read(20))
            nodes.append({"name":cstring(r), "size":length, "flags":node_flags})
        return {"engine":engine, "nodes":nodes}


def priority(path, stat=None):
    parts = path.parts

    if "PersistentData" in parts:
        if "Extract" in parts[parts.index("PersistentData")+1:]:
            i = parts.index("Extract", parts.index("PersistentData"))
            patch = int(parts[i+1]) if parts[i+1].isdigit() else 0
            return 2, patch, (stat or path.stat()).st_mtime_ns
        return 1, 0, (stat or path.stat()).st_mtime_ns
    return 0, 0, (stat or path.stat()).st_mtime_ns


def scan(root, destination, log=print, workers=4):
    root, destination = Path(root).resolve(), Path(destination)
    if not root.is_dir():
        raise ValueError(f"Source folder does not exist: {root}")
    previous = {}
    if destination.is_file():
        try:
            old = json.loads(destination.read_text("utf-8"))
            previous = {b["path"]:b for b in old.get("bundles", [])}
        except (OSError,ValueError,KeyError):pass
    started=time.monotonic();last=started;directories=0
    log('Discovering bundles')
    candidates = {}
    pending=[root];discovery_errors=[]
    while pending:
        folder=pending.pop();directories+=1
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not getattr(os.path,'isjunction',lambda _:False)(entry.path):pending.append(entry.path)
                            continue
                        if not entry.name.lower().endswith(('.pak','.assetbundle')) or not entry.is_file():continue
                        p=Path(entry.path);st=entry.stat();rank=priority(p,st);key=entry.name.lower()
                        if key not in candidates or rank>candidates[key][2]:candidates[key]=(p,st,rank)
                    except OSError as e:discovery_errors.append({'path':entry.path,'error':str(e)})
        except OSError as e:discovery_errors.append({'path':str(folder),'error':str(e)})
        if time.monotonic()-last>=.5:
            log(f'Discovering: {directories} folders, {len(candidates)} bundles');last=time.monotonic()
    discovered=time.monotonic()
    log(f'Discovered {len(candidates)} bundles in {discovered-started:.1f}s')
    bundles, errors = [], []
    errors.extend(discovery_errors)
    def index(candidate):
        p,st,_=candidate
        old = previous.get(str(p))
        try:
            if old and old.get("size") == st.st_size and old.get("mtime") == st.st_mtime_ns:
                item = old
            else:
                item = {"path":str(p), "size":st.st_size, "mtime":st.st_mtime_ns, **directory(p)}
            return item,None
        except Exception as e:
            return None,{"path":str(p), "error":str(e)}
    ordered=sorted(candidates.values(),key=lambda c:c[0])
    with ThreadPoolExecutor(max_workers=max(1,min(8,workers))) as pool:

        for start in range(0,len(ordered),128):
            for item,error in pool.map(index,ordered[start:start+128]):
                if item is not None:bundles.append(item)
                if error is not None:errors.append(error)
            log(f'Indexed {min(start+128,len(ordered))}/{len(ordered)} bundles')
    log(f'Indexing completed in {time.monotonic()-discovered:.1f}s')
    maps = []
    for b in bundles:
        for n in b["nodes"]:
            name = n["name"]
            if name.startswith("BuildPlayer-") and "." not in name:
                maps.append({"name":name[len("BuildPlayer-"):], "path":b["path"], "node":name})
    result = {"version":1, "root":str(root), "bundles":bundles, "maps":maps, "errors":errors}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(".tmp")
    temp.write_text(json.dumps(result, indent=2), "utf-8")
    temp.replace(destination)
    log(f"Found {len(maps)} scenes in {len(bundles)} bundles ({len(errors)} unreadable)")
    return result
