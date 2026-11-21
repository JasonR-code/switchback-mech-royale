"""Component scenarios for short-horizon movement. Run with python3 -m unittest discover."""
import math
import random
import statistics
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
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


class LaneExit(Floor):
    """Approximate the end of a firing lane. No building collision is modeled."""

    def __init__(self, length):
        self.length = length

    def clear(self, start, end):
        return end[0] < self.length or end[1] < -4


def retreat_trial(motion_type, seed, count):
    """A 20 Hz straight-ground physics probe with several scripted arm guns.

    Shots use exact observed pursuit velocities and a random lead fraction
    per shooter. They have independent firing phases and spread. Projectile
    observations within 200 m omit sensor occlusion. The trial ends at the
    lane exit or at 15 s. Hits to the front deal 45 damage in this probe.
    """
    rng = random.Random(seed)
    rng.uniform(45, 78)  # Keep the recorded case sequence stable.
    obs = make_obs()
    controller = motion_type({}, seed + 57)
    arena = LaneExit(rng.uniform(40, 100))
    me = obs['self']
    me['pos'][1] = rng.uniform(-6, 6)
    goal = (arena.length + 4, 0., 0.)
    width = .27 if seed % 2 else 1.15
    bearings = [rng.uniform(-width, width) for _ in range(count)]
    shooters = []
    for bearing in bearings:
        d = rng.uniform(52, 100)
        shooters.append([-d * math.cos(bearing), -d * math.sin(bearing), 0.])
    leads = [rng.choice((0., .4, .75, 1.)) for _ in shooters]
    noises = [random.Random(seed + 197*i) for i in range(count)]
    phases = [rng.randint(0, 4) for _ in shooters]
    shots = []
    hits = 0
    last_boost = -10.
    reached = False
    for k in range(300):
        px, py = me['pos'][:2]
        vx, vy = me['vel'][:2]
        obs['mechs'] = []
        for i, where in enumerate(shooters):
            dx, dy = px - where[0], py - where[1]
            t = math.hypot(dx, dy) / 252 * leads[i]
            yaw = math.atan2(dy + t*vy, dx + t*vx)
            obs['mechs'].append(dict(kind='mech', pos=where, aim=[yaw, 0], weapons=['gun']))
            magazine_tick = (k + phases[i]) % 106
            if magazine_tick < 60 and magazine_tick % 5 == 0 and arena.clear(where, me['pos']):
                bearing = yaw + noises[i].gauss(0, math.radians(.6))
                shots.append({'kind':'gun', 'pos':where[:2] + [4.5], 'age':0.,
                              'vel':[252*math.cos(bearing), 252*math.sin(bearing), 0.]})
        obs['projectiles'] = [p for p in shots if math.dist(p['pos'], me['pos']) < 200]
        if k % 2 == 0:
            action = controller.act(obs, arena, goal[:2], {'goal':goal, 'escape':True, 'pressure':1.})
        advance(obs, action)
        if action['boost']:
            me['energy'] = max(0, me['energy'] - .05*17)
            last_boost = obs['t']
        elif obs['t'] - last_boost > .6:
            me['energy'] = min(100, me['energy'] + .05*18)
        for p in shots[:]:
            rx, ry = p['pos'][0]-px, p['pos'][1]-py
            p['pos'][0] += .05 * p['vel'][0]
            p['pos'][1] += .05 * p['vel'][1]
            p['age'] += .05
            dx, dy = p['pos'][0]-me['pos'][0]-rx, p['pos'][1]-me['pos'][1]-ry
            fraction = max(0., min(1., -(rx*dx+ry*dy)/max(1e-9, dx*dx+dy*dy)))
            hit = math.hypot(rx+dx*fraction, ry+dy*fraction) < 2.8
            if hit or p['age'] > .92:
                hits += hit
                shots.remove(p)
        if not arena.clear(shooters[0], me['pos']):
            reached = True
            break
    return reached and hits*45 < 1400, hits, (k+1)*.05


def retreat_summary(motion_type, start, count, shooters):
    rows = [retreat_trial(motion_type, seed, shooters) for seed in range(start, start+count)]
    return dict(arrived_alive=sum(r[0] for r in rows), cases=count,
                mean_contacts=round(statistics.mean(r[1] for r in rows), 2),
                mean_seconds=round(statistics.mean(r[2] for r in rows), 2))


class MotionTests(unittest.TestCase):
    def test_reaching_lane_exit_under_three_shooters(self):
        result = retreat_summary(Motion, 14110, 12, 3)
        self.assertEqual(result['arrived_alive'], result['cases'])
        self.assertLess(result['mean_seconds'], 7.8)

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
    if len(sys.argv) > 1 and sys.argv[1] == '--retreat':
        import argparse
        import importlib.util
        parser = argparse.ArgumentParser()
        parser.add_argument('--retreat', action='store_true')
        parser.add_argument('--motion-file', type=Path)
        parser.add_argument('--first', type=int, default=14110)
        parser.add_argument('--cases', type=int, default=64)
        parser.add_argument('--shooters', type=int, default=3)
        args = parser.parse_args()
        policy = Motion
        if args.motion_file:
            spec = importlib.util.spec_from_file_location('motion_under_test', args.motion_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            policy = mod.Motion
        print(retreat_summary(policy, args.first, args.cases, args.shooters))
        sys.exit(0)
    print('Synthetic projectile contacts over 48 bearings / lead times (goal-only, predictive):',
          gun_evasion(False), gun_evasion(True))
    unittest.main()
