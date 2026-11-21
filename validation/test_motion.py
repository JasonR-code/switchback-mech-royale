"""Component scenarios for short-horizon movement. Run with python3 -m unittest discover."""
import math
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'bot'))
from motion import Motion


class Floor:
    climb_height = None
    def ground(self, x, y):
        return 0.
    def surface(self, x, y, z):
        return 0.
    def clear(self, a, b):
        return True
    def can_move(self, a, b, radius=None):
        return True


class Corridor(Floor):
    def can_move(self, a, b, radius=None):
        return abs(b[1]) < 2.6


def make_obs():
    return {'self': {'pos': [0., 0., 0.], 'vel':[0., 0., 0.], 'energy':100,
                     'grounded':True, 'in_zone':True, 'max_energy':100},
            't':5., 'mechs': [], 'projectiles':[]}


def advance(obs, act, dt=.05):
    me = obs['self']
    max_v = (19.5 if act['boost'] else 11.7)
    vx, vy = me['vel'][:2]
    dx, dy = act['move'][0]*max_v-vx, act['move'][1]*max_v-vy
    scale = min(1, 58.5 * dt / max(.00001, math.hypot(dx,dy)))
    me['vel'] = [vx+scale*dx, vy+scale*dy, 0.]
    me['pos'][0] += dt*me['vel'][0]
    me['pos'][1] += dt*me['vel'][1]
    obs['t'] += dt


def gun_evasion(use_controller):
    # Crossing at 12 bearings and four lead times. Baseline steers to the same
    # objective and has the same ground acceleration and boost speed.
    contacts = 0
    for k in range(12):
        angle = math.pi * k / 6
        nx, ny = math.cos(angle), math.sin(angle)
        for delay in (.28, .38, .49, .64):
            obs = make_obs()
            ctrl = Motion({}, 42)
            intent = {'goal':(90.,0.,0.),'pressure':.4}
            bullet = {'kind':'gun','pos':[-252*delay*nx, -252*delay*ny, 4.5],
                      'vel':[252*nx,252*ny,0.]}
            obs['projectiles'] = [bullet]
            hit = False
            for k2 in range(math.ceil((delay+.15)/.05)):
                if k2 % 2 == 0:
                    act = ctrl.act(obs, Floor(), (90.,0.),intent) if use_controller else {'move':[1.,0.], 'boost':True}
                rx, ry = bullet['pos'][0]-obs['self']['pos'][0], bullet['pos'][1]-obs['self']['pos'][1]
                advance(obs,act)
                bullet['pos'][0] += bullet['vel'][0]*.05
                bullet['pos'][1] += bullet['vel'][1]*.05
                dx = bullet['pos'][0]-obs['self']['pos'][0]-rx
                dy = bullet['pos'][1]-obs['self']['pos'][1]-ry
                t = max(0.,min(1., -(rx*dx + ry*dy)/max(1e-9,dx*dx + dy*dy)))
                if math.hypot(rx+dx*t,ry+dy*t) < 2.8:
                    hit = True
            contacts += hit
    return contacts


class MotionTests(unittest.TestCase):
    def test_stuck_approach_recovers_without_leaving_capture_ring(self):
        obs = make_obs()
        m = Motion({}, 3)
        intent = {'goal': (32.,0.,0.), 'hold':True, 'capture_radius':8}
        m.act(obs,Floor(),(6.,0.),intent)
        obs['t'] += 1.2
        self.assertTrue(m.act(obs,Floor(),(6.,0.),intent)['jump'])
        obs['self']['pos'] = [31.,0.,0.]
        obs['t'] += .1
        self.assertFalse(m.act(obs,Floor(),(32.,0.),intent)['jump'])

    def test_open_progress_and_energy(self):
        ctrl = Motion({},1)
        obs = make_obs()
        goal = (50., 20., 0.)
        intent = {'goal':goal}
        action = ctrl.act(obs, Floor(), goal[:2], intent)
        self.assertAlmostEqual(action['move'][1]/action['move'][0], .4)
        self.assertFalse(action['jump'])
        obs['self']['energy'] = 12
        self.assertFalse(ctrl.act(obs,Floor(),goal[:2],intent)['boost'])
        obs['self']['energy'] = 62
        obs['self']['in_zone'] = False
        self.assertTrue(ctrl.act(obs,Floor(),goal[:2],intent)['boost'])

    def test_capture_for_four_seconds_under_observation(self):
        goal = (0.,0.,0.)
        ctrl = Motion({},15)
        obs = make_obs()
        obs['self'].update(pos=[6.8,0.,0.],vel=[9.,0.,0.])
        obs['mechs'] = [{'kind':'mech','pos':[85.,0.,0.],'aim':[math.pi,0.]}]
        r = 8
        radii = []
        for _ in range(40):
            action = ctrl.act(obs,Floor(),goal[:2],{'goal':goal,'hold':True,'capture_radius':r,'pressure':.75})
            advance(obs, action)
            advance(obs, action)
            radii.append(math.hypot(*obs['self']['pos'][:2]))
        self.assertLess(max(radii),r)

    def test_movement_preserves_corridor(self):
        goal = (80.,0.,0.)
        ctrl = Motion({},56)
        obs = make_obs()
        obs['mechs'] = [{'kind':'mech','pos':[-35.,1.,0.],'aim':[0.,0.],'charging':True}]
        action = ctrl.act(obs,Corridor(),goal[:2],{'goal':goal, 'urgent':True,'pressure':1.})
        self.assertGreater(action['move'][0],.8)
        self.assertLess(abs(action['move'][1]),.4)

    def test_orbit_instead_of_standing_at_an_exposed_anchor(self):
        obs = make_obs()
        obs['mechs'] = [{'kind':'mech','pos':[35.,0.,0.],'aim':[math.pi,0.]}]
        action = Motion({},17).act(obs, Floor(), (0.,0.), {'goal':(0.,0.,0.), 'pressure':.8})
        self.assertGreater(abs(action['move'][1]),.75)

    def test_hazard_ablation(self):
        baseline, predictive = gun_evasion(False), gun_evasion(True)
        self.assertGreaterEqual(baseline-predictive,6)

    def test_mortar_departure_from_stationary_goal(self):
        obs = make_obs()
        obs['projectiles'] = [{'kind':'mortar','pos':[0.,0.,11.], 'vel':[0.,0.,-10.]}]
        a = Motion({},17).act(obs, Floor(), (0.,0.), {'goal':(0,0,0),'hold':True})
        self.assertGreater(math.hypot(*a['move']),.85)

    def test_shots_too_high_have_no_influence(self):
        goal = (80.,0.,0.)
        obs = make_obs()
        basic = Motion({},17).act(obs, Floor(), goal[:2], {'goal':goal})
        obs['projectiles'] = [{'kind':'gun','pos':[-96.,0.,40.], 'vel':[252.,0.,0.]}]
        self.assertEqual(basic,Motion({},17).act(obs, Floor(), goal[:2], {'goal':goal}))

    def test_climb_commits_and_does_not_jump_with_no_fuel(self):
        obs = make_obs()
        roof = Floor()
        roof.climb_height = 16.
        ctrl = Motion({},55)
        goal = (8.,0.,16.)
        obs['self']['energy'] = 14
        wait = ctrl.act(obs, roof, goal[:2], {'goal':goal})
        self.assertFalse(wait['jump'])
        obs['self']['energy'] = 72
        self.assertTrue(ctrl.act(obs, roof, goal[:2], {'goal':goal})['jump'])
        obs['self'].update(grounded=False,pos=[2.,0.,14.])
        self.assertTrue(ctrl.act(obs, roof, goal[:2], {'goal':goal})['boost'])
        obs['self']['pos'] = [3.,0.,17.2]
        self.assertFalse(ctrl.act(obs, roof, goal[:2], {'goal':goal})['boost'])


if __name__ == '__main__':
    print('Synthetic projectile contacts over 48 bearings / lead times (goal-only, predictive):',
          gun_evasion(False), gun_evasion(True))
    unittest.main()
