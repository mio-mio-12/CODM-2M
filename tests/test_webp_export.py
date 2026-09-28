import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
from codm_compiler.formats import GLB, write_c2m
from codm_compiler.texture_encoding import convert_textures


class WebPExportTests(unittest.TestCase):
    def test_webp_only_rewrites_material_and_source_references(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'images').mkdir();(root/'source_materials').mkdir()
            pixels=np.array([[[255,0,0,255],[0,255,0,0]]],dtype=np.uint8)
            Image.fromarray(pixels).save(root/'images'/'leaf.png')
            material={'name':'leaf','textures':{'color':'images/leaf.png'},'terrainMask':{'textures':{'_Control':{'path':'images/leaf.png'}}},
                      'color':[1,1,1,1],'metallic':0.,'roughness':1.,'decal':False,'alpha':'MASK','cutoff':.5,
                      'doubleSided':True,'blend':'alpha','source':None}
            materials=SimpleNamespace(items=[material],images={'leaf':'images/leaf.png'})
            (root/'source_materials'/'leaf.json').write_text(json.dumps({'texture':'images/leaf.png'}),encoding='utf-8')
            lighting=[{'path':'images/leaf.png'}]
            self.assertEqual(convert_textures(root,materials,82,lighting),1)
            self.assertFalse(list((root/'images').glob('*.png')))
            self.assertEqual(materials.items[0]['textures']['color'],'images/leaf.webp')
            self.assertEqual(lighting[0]['path'],'images/leaf.webp')
            self.assertEqual(json.loads((root/'source_materials'/'leaf.json').read_text())['texture'],'images/leaf.webp')
            with Image.open(root/'images'/'leaf.webp') as image:
                self.assertEqual(image.format,'WEBP')
                self.assertEqual(image.getpixel((1,0))[3],0)
            glb=GLB();glb.material(materials.items[0],root)
            self.assertEqual(glb.doc['images'][0]['mimeType'],'image/webp')
            self.assertEqual(glb.doc['textures'][0],{'extensions':{'EXT_texture_webp':{'source':0}}})
            self.assertIn('EXT_texture_webp',glb.doc['extensionsRequired'])
            self.assertEqual(len(glb.doc['images']),1)
            materials.items[0]['unlit']=True
            unlit=GLB();unlit.material(materials.items[0],root)
            self.assertEqual(set(unlit.doc['extensionsUsed']),{'EXT_texture_webp','KHR_materials_unlit'})
            write_c2m(root/'map.c2m',[],materials.items,[],{'name':'map'},{} )
            self.assertIn(b'leaf\x00', (root/'map.c2m').read_bytes())

    def test_quality_bounds_and_png_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'images').mkdir();(root/'source_materials').mkdir()
            materials=SimpleNamespace(items=[],images={})
            for quality in (-1,101):
                with self.assertRaises(ValueError):convert_textures(root,materials,quality)
            image=root/'images'/'plain.png';Image.new('RGB',(1,1)).save(image)
            glb=GLB();glb.texture(image)
            self.assertEqual(glb.doc['images'][0]['mimeType'],'image/png')
            self.assertNotIn('extensionsRequired',glb.doc)
