"""Independent synthetic fire-control fixtures. Run directly to print aiming ablations."""
import json
import math
import random
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent/'bot', HERE.parent):
    if (path/'combat.py').is_file():
        sys.path.insert(0, str(path))
        break
from combat import Combat, ZERO, gun_solution, mortar_solutions, wrap

CFG = json.loads((Path(sys.path[0])/'defaults.json').read_text())


class Flat:
    def clear(self, a, b):
        return min(a[2], b[2]) >= 0


class Slab(Flat):
    def __init__(self, x, height):
        self.x = x
        self.height = height

    def clear(self, a, b):
        if not super().clear(a, b):
            return False
        if (a[0]-self.x) * (b[0]-self.x) <= 0 and a[0] != b[0]:
            z = a[2] + (b[2]-a[2]) * (self.x-a[0])/(b[0]-a[0])
            return z > self.height
        return True


def observation(*kinds, distance=100, velocity=ZERO, hp=1400):
    slots = [dict(kind=k, cooldown=0, stats=CFG['weapons'][k], ammo=12, charge=0) for k in kinds]
    me = dict(id=0, pos=[0,0,0], aim=[0,0], hp=1400, max_hp=1400, energy=100, weapons=slots)
    foe = dict(id=1, kind='mech', pos=[distance,0,0], vel=velocity, hp=hp,
               weapons=['gun'], aim=[math.pi,0])
    return dict(self=me, mechs=[foe], crates=[], events=[], t=1)


def settle(bot, obs, arena=None, **intent):
    arena = arena or Flat()
    action = bot.act(obs, arena, intent)
    obs['self']['aim'] = action['aim']
    obs['t'] += .1
    return bot.act(obs, arena, intent)


def aiming_ablation(n=256):
    """Common-random-number shot pairs with an independent 4 ms collision sampler."""
    rng = random.Random(59531)
    out = dict(gun=[0,0,0], mortar=[0,0,0])
    for _ in range(n):
        r, angle = rng.uniform(35, 175), rng.uniform(-math.pi, math.pi)
        height = rng.uniform(-8, 25)
        speed, heading = rng.uniform(0,17), rng.uniform(-math.pi, math.pi)
        vx, vy = speed*math.cos(heading), speed*math.sin(heading)
        target = (r*math.cos(angle), r*math.sin(angle), height+4.5)
        vel = (vx,vy,0)
        spread = [rng.gauss(0, math.radians(.6)) for _ in range(2)]
        for kind in out:
            shell = kind == 'mortar'
            z0 = 9.5 if shell else 7
            vs = 72 if shell else 252
            g = 22 if shell else 0
            d = (target[0],target[1],target[2]-z0)
            if shell:
                stationary = mortar_solutions(d,ZERO,vs,g,3,7)
                moving = mortar_solutions(d,vel,vs,g,3,7)
                if not moving or not stationary:
                    continue
                solutions = [stationary[0],moving[0]]
            else:
                solutions = [gun_solution(d,v,vs,3) for v in (ZERO,vel)]
            out[kind][2] += 1
            for variant,(yaw,pitch,expected_t) in enumerate(solutions):
                if not shell:
                    yaw += spread[0]
                    pitch += spread[1]
                dx,dy,dz = math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),math.sin(pitch)
                for i in range(int((expected_t+.27)/.004)):
                    t=i*.004
                    x,y,z = (3+vs*t)*dx,(3+vs*t)*dy,z0+(3+vs*t)*dz-g*t*t/2
                    if (abs(z-target[2])<=4.5 and
                            (x-target[0]-vx*t)**2 + (y-target[1]-vy*t)**2 <= 2.5**2):
                        out[kind][variant] += 1
                        break
    return out


class CombatTests(unittest.TestCase):
    def setUp(self):
        self.bot = Combat(CFG)

    def test_ballistic_lifetime_pitch_and_unreachable(self):
        roots = mortar_solutions((190,0,-5), (0,10,0), 72,22,3,7)
        self.assertEqual(len(roots),2)
        for yaw,pitch,t in roots:
            length=3+72*t
            self.assertAlmostEqual(length*math.cos(pitch)*math.cos(yaw),190,places=3)
            self.assertAlmostEqual(length*math.cos(pitch)*math.sin(yaw),10*t,places=3)
            self.assertAlmostEqual(length*math.sin(pitch)-11*t*t,-5,places=3)
        self.assertFalse(mortar_solutions((350,0,0),ZERO,72,22,3,7))
        self.assertFalse(mortar_solutions((190,0,-5),ZERO,72,22,3,1))

    def test_cover_and_clear_high_arc(self):
        wall=Slab(90,38)
        obs=observation('gun','mortar',distance=180)
        a=settle(self.bot,obs,arena=wall)
        self.assertGreater(a['aim'][1],.95)
        self.assertEqual(a['fire'],[False,True])
        self.assertFalse(any(settle(self.bot,obs,arena=Slab(90,180))['fire']))

    def test_mortar_proximity_and_wall_by_tube(self):
        self.assertFalse(any(settle(self.bot,observation('mortar',distance=8))['fire']))
        self.assertFalse(any(settle(self.bot,observation('mortar',distance=45),arena=Slab(1,20))['fire']))

    def test_slew_and_wrap(self):
        obs=observation('gun')
        obs['self']['aim']=[math.pi,0.]
        a=self.bot.act(obs,Flat(),{})
        self.assertFalse(a['fire'][0])
        obs['mechs'][0]['pos']=[-100,-.25,0]
        self.assertTrue(self.bot.act(obs,Flat(),{})['fire'][0])

    def test_gun_and_lightning_share_aim(self):
        obs=observation('gun','lightning',distance=41,velocity=(0,19,0))
        a=settle(self.bot,obs)
        self.assertEqual(a['fire'],[True,True])
        self.assertGreater(a['aim'][0],.06)
        obs['self']['energy']=2
        self.assertEqual(settle(self.bot,obs)['fire'],[True,False])
        self.assertFalse(settle(self.bot,observation('lightning',distance=51))['fire'][0])

    def test_laser_charge_release_and_cookoff(self):
        obs=observation('gun','laser',hp=245)
        self.assertEqual(settle(self.bot,obs)['fire'],[True,True])
        obs['self']['weapons'][1]['charge']=.3
        self.assertTrue(settle(self.bot,obs)['fire'][1])
        obs['mechs'][0]['weapons']=['mortar']
        self.assertFalse(settle(self.bot,obs)['fire'][1])
        obs['self']['weapons'][1]['charge']=.75
        obs['self']['aim']=[math.pi,0]
        self.assertTrue(self.bot.act(obs,Flat(),{})['fire'][1])
        self.assertFalse(settle(self.bot,obs)['fire'][1])

    def test_cover_upper_body(self):
        obs=observation('gun')
        self.assertTrue(settle(self.bot,obs,arena=Slab(50,6.3))['fire'][0])
        self.assertFalse(settle(self.bot,obs,arena=Slab(50,14))['fire'][0])

    def test_reload_and_regeneration(self):
        obs=observation('gun')
        obs['self']['weapons'][0]['ammo']=4
        obs['mechs']=[]
        obs['crates']=[dict(id=1001,pos=[20,0,0],hp=300)]
        a=settle(self.bot,obs,recover=True)
        self.assertEqual(a['fire'],[False,False])
        self.assertTrue(a['reload'])
        self.assertTrue(settle(self.bot,obs,focus=1001)['fire'][0])
        obs['mechs']=[dict(id=1,kind='mech',pos=[150,0,0],aim=[0,0],hp=1400)]
        obs['crates']=[]
        self.assertFalse(settle(self.bot,obs,recover=True)['fire'][0])

    def test_elimination_and_signed_pitch(self):
        obs=observation('gun',distance=46)
        obs['mechs'].append(dict(id=2,kind='mech',pos=[50,15,0],vel=ZERO,hp=40,aim=[math.pi,0]))
        a=settle(self.bot,obs)
        self.assertAlmostEqual(a['aim'][0],math.atan2(15,50),places=3)
        self.assertLess(a['aim'][1],0)

    def test_common_random_shots(self):
        results = aiming_ablation()
        for baseline,leading,count in results.values():
            self.assertGreater(leading-baseline,.20*count)
            self.assertGreater(leading,.70*count)


if __name__=='__main__':
    print('synthetic hits [stationary aim, velocity lead, eligible pairs]',aiming_ablation())
    unittest.main()
