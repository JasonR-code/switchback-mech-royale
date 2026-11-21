"""Synthetic decisions on a flat arena and a single sight-blocking wall."""
import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))
from strategy import Strategy, distance, future_circle


class Plane:
    bounds = (-500, -400, 500, 400)

    def ground(self, x, y):
        return 0

    def surface(self, x, y, z):
        return 0

    def walkable(self, x, y, z):
        return True

    def cover(self, x, y, z):
        return 0

    def clear(self, a, b):
        return True


class WithWall(Plane):
    # Solid slab between y=8..35 and |x|<3. Standing behind its north half
    # breaks line of sight to an enemy approaching from the east.
    def walkable(self, x, y, z):
        return not (-5 < x < 5 and 6 < y < 37)

    def clear(self, a, b):
        if (a[0] < 0) == (b[0] < 0):
            return True
        y = a[1] + (b[1]-a[1]) * (-a[0]) / (b[0]-a[0])
        return not (8 <= y <= 35)

    def cover(self, x, y, z):
        return .85 if abs(x)<18 and 6<y<35 else 0


def observed():
    return {"tick": 200, "t": 10.0, "alive": 16, "self":
            {"id": 2, "pos":[0,0,0], "vel":[0,0,0], "hp":1400, "max_hp":1400,
             "energy":100, "cubes":0, "grounded":True, "in_zone":True, "stats":{},
             "aim":[0,0], "weapons":[{"kind":"gun"}, None], "upgrades":[]},
            "zone":{"center":[0,0], "radius":280, "next_center":[20,0], "next_radius":190,
                    "shrink_start":70,"shrink_end":100,"dps":20},
            "mechs":[], "events":[], "sounds":[], "drops":[], "crates":[], "cubes":[], "pickups":[]}


def enemy(i,x,y, hp=1400):
    return {"id":i,"kind":"mech","pos":[x,y,0],"vel":[0,0,0],"hp":hp,"max_hp":1400,
            "aim":[math.atan2(-y,-x),0],"weapons":["gun"]}


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.arena, self.obs = Plane(), observed()
        self.bot = Strategy({}, 6)

    def plan(self):
        return self.bot.plan(self.obs, self.arena)

    def test_new_circle_from_live_state_once(self):
        z = dict(center=(50,0), radius=90, next_center=(70,0), next_radius=30, shrink_start=10, shrink_end=30)
        self.assertEqual(future_circle(z,20,5),((60,0),60))
        self.assertEqual(future_circle(z,0,6),((50,0),90))

    def test_cube_and_first_upgrade(self):
        self.obs.update(cubes=[{"id":5002,"pos":(13,0,0)}], offer={"choices":[{"id":"sensors"},{"id":"nanites"},{"id":"gun_rate"}]})
        p=self.plan()
        self.assertEqual(p["goal"], (13,0,0))
        self.assertEqual(p["actions"]["pick"],1)

    def test_first_pickup_range_vertical_and_locked_laser(self):
        self.obs["pickups"]=[{"id":8001,"kind":"laser","pos":(0,1,8)},{"id":8002,"kind":"lightning","pos":(0,3,0)}]
        self.assertEqual(self.plan()["actions"],{"take":8002})
        self.obs["zone"].update(radius=22,next_radius=15)
        self.obs["self"]["weapons"]=[{"kind":"mortar"},{"kind":"laser","charge":.3}]
        self.assertEqual(self.plan()["actions"],{"take":8002, "drop":0})

    def test_zone_urgency_refuses_bait(self):
        self.obs["zone"].update(center=(0,0),radius=38,next_center=(12,0),next_radius=10,shrink_start=0,shrink_end=14,dps=160)
        self.obs["self"]["pos"]=[-36,0,0]
        self.obs["pickups"]=[{"id":8003,"kind":"laser","pos":(-62,0,0)}]
        p=self.plan()
        self.assertTrue(p["urgent"])
        self.assertLess(distance(p["goal"],(12,0)),29)

    def test_uncontested_drop_can_repair(self):
        self.obs["self"]["hp"]=390
        self.obs["drops"]=[{"id":20002,"pos":(12,0,0),"holder":None,"progress":0,"lands_in":0,"radius":8,"capture_s":4}]
        p=self.plan()
        self.assertEqual(p["goal"],(12,0,0))
        self.assertTrue(p["hold"])
        self.assertEqual(p["capture_radius"],8)
        self.obs.update(mechs=[enemy(3,13,1)])
        self.obs["t"]+=.9
        self.assertEqual(self.plan()["capture_radius"],0)

    def test_wounded_mech_breaks_sight(self):
        self.arena = WithWall()
        self.obs["self"].update(pos=[-10,0,0],hp=445)
        self.obs.update(mechs=[enemy(3,34,0)],events=[{"type":"damaged","weapon":"gun","amount":45,"bearing":0,"by":3}])
        p=self.plan()
        self.assertTrue(p["escape"])
        self.assertFalse(self.arena.clear(p["goal"],self.obs["mechs"][0]["pos"]))

    def test_single_contact_focus_group_fallback(self):
        self.obs["mechs"]=[enemy(3,40,0,184)]
        p=self.plan()
        self.assertFalse(p["escape"])
        self.assertEqual(p["focus"],3)
        self.obs["mechs"].append(enemy(4,0,-37))
        p=self.plan()
        self.assertTrue(p["escape"])
        self.assertEqual(p["focus"],3)

    def test_hidden_contact_pressure_and_fading(self):
        self.obs["mechs"]=[enemy(3,15,25)]
        self.obs["self"].update(pos=[-15,25,0])
        exposed=self.plan()["pressure"]
        self.arena=WithWall()
        hidden=self.plan()["pressure"]
        self.assertLess(hidden,.4*exposed)
        self.obs["mechs"]=[]
        self.obs["t"]+=7
        self.assertLess(self.plan()["pressure"],hidden)
        self.obs["t"]+=6
        self.assertEqual(self.plan()["threats"],[])

    def test_step_sound_sweep_and_damage_face(self):
        self.obs["sounds"]=[{"kind":"gun","bearing":1.3,"dist":"near","age":.1}]
        self.assertAlmostEqual(self.plan()["scan"],1.3)
        self.obs.update(t=11,events=[{"type":"damaged","amount":40,"weapon":"gun","bearing":-2.1,"by":3}])
        self.assertAlmostEqual(self.plan()["scan"],-2.1)

    def test_resource_memory_out_of_view(self):
        self.obs["pickups"]=[{"id":8100,"kind":"laser","pos":(19,0,0)}]
        self.assertEqual(self.plan()["goal"],(19,0,0))
        self.obs.update(t=11,pickups=[])
        self.assertEqual(self.plan()["goal"],(19,0,0))
        self.obs["self"]["pos"]=[17,0,0]
        self.obs["t"]+=1
        self.assertNotEqual(self.bot.plan(self.obs,self.arena)["goal"],(19,0,0))

    def test_resource_heights_roundtrip(self):
        self.obs["self"]["energy"]=15
        self.obs["pickups"]=[{"id":8001,"kind":"laser","pos":(6,0,55)},{"id":8002,"kind":"mortar","pos":(15,0,0)}]
        self.assertEqual(self.plan()["goal"],(15,0,0))


if __name__ == "__main__":
    unittest.main()
