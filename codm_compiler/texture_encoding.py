import json
from pathlib import Path
from PIL import Image, features


def replace_paths(value, replacements):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [replace_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item, replacements) for key, item in value.items()}
    return value


def convert_textures(root, materials, quality, *records):
    if not isinstance(quality, int) or isinstance(quality, bool) or not 0 <= quality <= 100:
        raise ValueError('WebP quality must be between 0 and 100')
    if not features.check('webp'):
        raise RuntimeError('This Pillow build does not support WebP')
    root = Path(root)
    images = sorted((root / 'images').glob('*.png'))
    replacements = {}
    for source in images:
        target = source.with_suffix('.webp')
        if target.exists():
            raise FileExistsError(target)
        with Image.open(source) as image:
            image.save(target, format='WEBP', quality=quality, method=4, exact=True)
        with Image.open(target) as image:
            image.verify()
        replacements[source.relative_to(root).as_posix()] = target.relative_to(root).as_posix()
    materials.items[:] = replace_paths(materials.items, replacements)
    materials.images = replace_paths(materials.images, replacements)
    for record in records:
        record[:] = replace_paths(record, replacements)
    for source in (root / 'source_materials').glob('*.json'):
        data = replace_paths(json.loads(source.read_text(encoding='utf-8')), replacements)
        source.write_text(json.dumps(data, indent=2), encoding='utf-8')
    for source in images:
        source.unlink()
    return len(images)
