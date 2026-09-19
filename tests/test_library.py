import json
from pathlib import Path
import tempfile
import unittest
from codm_compiler.map_library import library,match_preview,cached_previews,preview_signature,PREVIEW_VERSION,preview_bundles


class LibraryTests(unittest.TestCase):
    def test_groups_visual_versions_but_retains_named_editions(self):
        names=['MP_Crash_Final_HQ_New_Atlases','MP_Crash_Final_Atlases','MP_Crash_Main_TDM',
               'MP_Standoff_Atlases','MP_Standoff_Halloween_Atlases','Menu_Atlases']
        c={'maps':[{'name':n,'path':n+'.pak'} for n in names]}
        entries=library(c);self.assertEqual(len(entries),3)
        crash=next(e for e in entries if e['id']=='crash')
        self.assertEqual(crash['variants'],names[:2])
        self.assertEqual(len(library(c,True)),6)

    def test_exact_map_art_preferred_without_day_night_confusion(self):
        e={'name':'MP_Crash_Final_HQ_New_Atlases'}
        images=[{'name':'winners_circle_Crash_night','kind':'Map artwork','file':'night.png'},
                {'name':'Trans_PVP_COD_Crash','kind':'Tactical map','file':'map.png'},
                {'name':'winners_circle_Crash','kind':'Map artwork','file':'day.png'}]
        self.assertEqual(match_preview(e,images)['file'],'day.png')
        self.assertIsNone(match_preview(e,images[:2]))
        self.assertIsNone(match_preview(e,images[:1]))
        related=match_preview({'name':'MP_Raid_CW_Atlases'},[{'name':'winners_circle_Raid','kind':'Map artwork','file':'raid.png'}])
        self.assertIn('related edition',related['caption'])

    def test_verified_unusual_art_names_and_no_minimap_fallback(self):
        for scene,art in [('MP_Armada_Atlases','Armada_WinnerCircle_002-1(1)'),
                          ('MP_Seaside_Atlases','WinnerCircle_SeaSidea')]:
            images=[{'name':'Trans_'+scene,'kind':'Tactical map','file':'minimap.png'},
                    {'name':'winners_circle_'+art,'kind':'Map artwork','file':'art.png'}]
            self.assertEqual(match_preview({'name':scene},images)['file'],'art.png')
        images=[{'name':'Trans_MP_Raid_CW','kind':'Tactical map','file':'map.png'},
                {'name':'winners_circle_Raid','kind':'Map artwork','file':'base.png'}]
        self.assertEqual(match_preview({'name':'MP_Raid_CW_Atlases'},images)['file'],'base.png')
        images=[{'name':'winners_circle_Raid_Christmas','kind':'Map artwork','file':'xmas.png'}]
        self.assertIsNone(match_preview({'name':'MP_Raid_Atlases'},images))
        self.assertIsNone(match_preview({'name':'MP_Raid_CW_Atlases'},images))

    def test_only_artwork_bundles_are_scanned(self):
        catalog={'bundles':[{'path':'textures$ui$winnerscircle.pak'},
                            {'path':'textures$ui$tacticaltopviewmap.pak'}]}
        self.assertEqual(preview_bundles(catalog),catalog['bundles'][:1])

    def test_preview_cache_tracks_bundle_revision_and_missing_files(self):
        c={'bundles':[{'path':'textures$ui$winnerscircle.pak','size':30,'mtime':1}]}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'test.png').write_bytes(b'test')
            data={'version':PREVIEW_VERSION,'signature':preview_signature(c),
                  'images':[{'file':'test.png','name':'winners_circle_Crash','kind':'Map artwork'}]}
            (p/'index.json').write_text(json.dumps(data))
            self.assertIsNotNone(cached_previews(c,p))
            data['version']=1;(p/'index.json').write_text(json.dumps(data))
            self.assertIsNone(cached_previews(c,p))
            data['version']=PREVIEW_VERSION;(p/'index.json').write_text(json.dumps(data))
            c['bundles'][0]['mtime']=2
            self.assertIsNone(cached_previews(c,p))
            c['bundles'][0]['mtime']=1;(p/'test.png').unlink()
            self.assertIsNone(cached_previews(c,p))
