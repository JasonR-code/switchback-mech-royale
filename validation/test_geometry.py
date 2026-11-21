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

class BodyClearanceTests(unittest.TestCase):
    """A short passage narrows to seven meters between two tall wings."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        v = Path(cls.tmp.name) / 'v2'
        v.mkdir()
        side = 121
        world = dict(bounds=dict(minX=0, maxX=120, minY=0, maxY=120),
                     terrain=dict(nx=side, ny=side, minX=0, minY=0, step=1),
                     prisms=[dict(base=-1, top=80, ring=rectangle(48,20,72,54.5), holes=[]),
                             dict(base=-1, top=80, ring=rectangle(48,61.5,72,96), holes=[]),
                             dict(base=13, top=15, ring=rectangle(24,80,34,97), holes=[])])
        (v/'world.json').write_text(json.dumps(world))
        # A short 2:1 slope in the top-left corner, independent of the passage.
        samples = array.array('h', (200*max(0,min(6,x-8)) if y>105 else 0
                                    for y in range(side) for x in range(side)))
        if sys.byteorder != 'little':
            samples.byteswap()
        (v/'terrain.i16').write_bytes(samples.tobytes())
        cls.a = Arena(cls.tmp.name, {})
        assert cls.a.handle, cls.a.error

    @classmethod
    def tearDownClass(cls):
        cls.a.close()
        cls.tmp.cleanup()

    def setUp(self):
        self.a.set_body(2.5, 9)

    def test_clearance_after_growing_at_bridge(self):
        self.assertTrue(self.a.can_move((12,88,0),(43,88,0)))
        self.a.set_body(4, 14.4)
        self.assertFalse(self.a.walkable(29,88,0))
        self.assertFalse(self.a.can_move((12,88,0),(43,88,0)))

    def test_route_changes_with_body_size(self):
        def passage_y():
            x, y = 14., 58.
            for _ in range(160):
                nx, ny = self.a.waypoint((x,y,0),(105,58,0))
                length = ((nx-x)**2 + (ny-y)**2)**.5
                scale = min(1., 1.2/max(length, 1.e-7))
                nx,ny = x+scale*(nx-x), y+scale*(ny-y)
                self.assertTrue(self.a.can_move((x,y,0),(nx,ny,0)))
                x,y = nx,ny
                if x>=60:
                    return y
            self.fail('waypoint stalled before passage')
        self.assertLess(abs(passage_y()-58), 2)
        self.a.set_body(4.0, 14.4)
        crossing = passage_y()
        self.assertTrue(crossing <= 16 or crossing >= 100, crossing)

    def test_uphill_gradient_and_downhill(self):
        self.assertFalse(self.a.can_move((8,110,0),(14,110,12)))
        self.assertTrue(self.a.can_move((14,110,12),(8,110,0)))
