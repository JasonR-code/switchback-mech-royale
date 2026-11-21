"""Regressions for the bearing-only policy on permitted observation sequences."""
import math
import unittest

from motion import Motion
from test_motion import Corridor, Floor, make_obs

def hit(ident, bearing=0., weapon='gun'):
    return dict(type='damaged', by=ident, bearing=bearing, weapon=weapon, amount=45)

class IncomingTests(unittest.TestCase):
    def setUp(self):
        self.motion = Motion({}, 10)
        self.obs = make_obs()

    def input(self, dt, events, reported=()):
        self.obs['t'] += dt
        self.obs['events'] = events
        self.obs['mechs'] = [dict(id=i) for i in reported]
        return self.motion.incoming_guns(self.obs)

    def test_independent_ids_and_expiry(self):
        self.assertFalse(self.input(0, [hit(0), hit(0)]))
        self.assertFalse(self.input(.1, [hit(None, None, 'zone')]))
        self.assertTrue(self.input(.1, [hit(3, .8)]))
        self.assertFalse(self.input(3.1, []))
        self.assertFalse(self.motion.incoming_hits)

    def test_occluded_gun_and_zero_id(self):
        self.assertFalse(self.input(0, [hit(1, 3., 'laser')]))
        self.assertFalse(self.input(.1, [hit(0, math.pi/2)], reported=[0]))
        nx,ny = self.input(.1, [])[0]
        self.assertAlmostEqual(nx,-1.)
        self.assertAlmostEqual(ny, 0.)
        self.assertFalse(self.input(.1, [dict(type='kill',target=1)]))

    def test_no_stale_direction_after_displacement(self):
        self.input(0, [hit(2), hit(3)])
        self.obs['self']['pos'][0] += 17
        self.assertFalse(self.input(.3, []))

    def test_reported_two_guns_and_distinct_weapon_types(self):
        self.assertFalse(self.input(0, [hit(1),hit(2)], [1,2]))
        self.assertEqual(len(self.input(.1, [], [1])),2)
        self.assertFalse(self.input(.1,[hit(2,.7,'lightning')],[1,2]))
        self.assertFalse(self.input(4.,[hit(7,0.,'npc'),hit(8,0.,'mortar')]))
        self.assertFalse(self.input(.1,[hit(0,None),hit(1,float('nan'))]))

    def test_open_ground_and_narrow_corridor(self):
        self.obs['mechs'] = []
        obs=self.obs
        goal=(100.,0.,0.)
        intent={'goal':goal, 'incoming_guns':((0,1),)}
        cross=Motion({},10).act(obs,Floor(),goal[:2],intent)
        normal=Motion({},10).act(obs,Floor(),goal[:2],{'goal':goal})
        self.assertGreater(abs(cross['move'][1]),abs(normal['move'][1]))
        narrow=Motion({},10).act(obs,Corridor(),goal[:2],intent)
        self.assertGreater(narrow['move'][0],0)
        self.assertLess(abs(narrow['move'][1]),.5)
