import tempfile
import unittest
from pathlib import Path
from codm_compiler.source import jsonable
from codm_compiler.formats import encoded,write_c2m,read_extension
from test_compiler import fixture


class SourceMetadataTests(unittest.TestCase):
    def test_nonfinite_ambient_probe_is_preserved_as_metadata(self):
        paths=[]
        source=jsonable({'m_AmbientProbe':{'sh[ 4]':float('nan'),'sh[ 5]':float('nan')},
                         'other':[float('inf'),float('-inf'),1.25]},paths)
        self.assertEqual(len(paths),4)
        self.assertEqual(source['m_AmbientProbe']['sh[ 4]'],{'nonFiniteFloat':'NaN'})
        self.assertEqual(source['other'][0],{'nonFiniteFloat':'+Infinity'})
        self.assertEqual(source['other'][2],1.25)
        mesh,mat=fixture()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.c2m'
            write_c2m(path,[mesh],[mat],[],{'name':'test','lighting':[source]}, {'status':'settings_only'})
            self.assertEqual(read_extension(path)['META']['lighting'][0],source)

    def test_runtime_numbers_remain_strict_and_failed_write_is_atomic(self):
        with self.assertRaises(ValueError):encoded({'runtimePosition':float('nan')})
        mesh,mat=fixture()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.c2m';path.write_bytes(b'existing valid output')
            with self.assertRaises(ValueError):
                write_c2m(path,[mesh],[mat],[],{'name':'test','badRuntimeValue':float('nan')},{})
            self.assertEqual(path.read_bytes(),b'existing valid output')
            self.assertEqual(list(Path(d).glob('*.partial')),[])
