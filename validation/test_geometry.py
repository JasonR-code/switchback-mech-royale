"""Synthetic map with a courtyard building, an elevated bridge and sloped terrain."""
import array
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'bot' if (BASE/'bot').is_dir() else BASE))
from arena import Arena


def rectangle(x0,y0,x1,y1):
    return [x0,y0,x1,y0,x1,y1,x0,y1]


class GeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        v = Path(cls.tmp.name)/'v2'
        v.mkdir()
        terrain = {'nx':101,'ny':101,'minX':0,'minY':0,'step':1}
        solids = [dict(kind='building',base=-2,top=18,ring=rectangle(20,20,50,50),
                       holes=[rectangle(29,29,41,41)]),
                  dict(kind='bridge',base=14,top=16,ring=rectangle(62,20,72,55),holes=[])]
        (v/'world.json').write_text(json.dumps(dict(bounds=dict(minX=0,maxX=100,minY=0,maxY=100),
                                                    terrain=terrain,prisms=solids)))
        a=array.array('h',(x for y in range(101) for x in range(101)))
        if sys.byteorder!='little':
            a.byteswap()
        (v/'terrain.i16').write_bytes(a.tobytes())
        cls.a = Arena(cls.tmp.name,{})
        assert cls.a.handle, cls.a.error

    @classmethod
    def tearDownClass(cls):
        cls.a.close()
        cls.tmp.cleanup()

    def test_ground_and_hole(self):
        self.assertAlmostEqual(self.a.ground(5.5,30),.055,places=5)
        self.assertTrue(self.a.clear((35,35,2),(35,35,32)))
        self.assertFalse(self.a.clear((25,25,2),(25,25,32)))
        self.assertFalse(self.a.walkable(24,25))
        self.assertTrue(self.a.walkable(35,35))

    def test_bridge_height(self):
        self.assertTrue(self.a.clear((58,35,5),(77,35,5)))
        self.assertFalse(self.a.clear((58,35,15),(77,35,15)))
        self.assertTrue(self.a.can_move((58,35,.58),(77,35,.77)))
        self.assertAlmostEqual(self.a.surface(68,35,16),16)
