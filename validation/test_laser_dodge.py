"""Laser release dodge: exact states built from the public recording's house-laser model.

House laser while charging (fitted to stream.jsonl.gz, mean error 0.36 deg): aim at our
position one observation (0.1 s) earlier plus 0.3 s of our velocity; release 0.8-0.9 s after
the charge first shows. The beam misses when that point is more than the body radius from us.
"""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import motion  # noqa: E402
from motion import Motion  # noqa: E402
from test_motion import Floor, advance, make_obs  # noqa: E402

RADIUS = 2.5


def charger(aim_at_us=True, charging=True, pos=(120., 0., 0.), ident=7):
    aim = math.pi if aim_at_us else math.pi/2
    return dict(id=ident, kind='mech', pos=list(pos), vel=[0, 0, 0], aim=[aim, 0], weapons=['gun', 'laser'],
                charging=charging, hp=1400)


def beam_miss(history, shooter):
    """Miss distance of a release at the last state, house aim model, perpendicular to the line."""
    (t1, p1, v1), (t0, p0, v0) = history[-1], history[-3]       # one observation = 2 ticks earlier
    aim = (p0[0] + .3*v0[0], p0[1] + .3*v0[1])
    sx, sy = shooter[:2]
    ux, uy = aim[0]-sx, aim[1]-sy
    n = math.hypot(ux, uy)
    return abs((p1[0]-sx)*uy/n - (p1[1]-sy)*ux/n)


def run(dodge, start_vel=(-6., 2., 0.), ticks=18, laser=True, flip_at=None):
    old = motion.LASER_DODGE
    motion.LASER_DODGE = dodge
    try:
        m = Motion({'mech': {'walk_speed': 11.7, 'boost_speed': 19.5}}, seed=3)
        obs = make_obs()
        obs['self']['vel'] = list(start_vel)
        obs['mechs'] = [charger()] if laser else []
        # Force the random strafe flip to come due mid-charge, the case seen in the recording.
        m.turn_at = obs['t'] + (flip_at if flip_at is not None else .3)
        hist = [(obs['t'], list(obs['self']['pos']), list(obs['self']['vel']))]
        goal = (-60., 0., 0.)          # retreating straight away from the charger
        for k in range(ticks):
            act = m.act(obs, Floor(), goal, {'goal': goal, 'pressure': .6, 'escape': False})
            if k % 2 == 0:
                cmd = act
            advance(obs, cmd)
            hist.append((obs['t'], list(obs['self']['pos']), list(obs['self']['vel'])))
        return hist, m
    finally:
        motion.LASER_DODGE = old


class LaserDodge(unittest.TestCase):
    def test_release_misses_with_dodge(self):
        hist, _ = run(True)
        self.assertGreater(beam_miss(hist, (120., 0.)), RADIUS)

    def test_baseline_is_hit_in_same_state(self):
        hist, _ = run(False)
        self.assertLess(beam_miss(hist, (120., 0.)), RADIUS)

    def test_dodge_reaches_boost_lateral_speed(self):
        hist, _ = run(True)
        self.assertGreater(abs(hist[-1][2][1]), 15.)

    def test_no_charge_no_change(self):
        a, _ = run(True, laser=False)
        b, _ = run(False, laser=False)
        self.assertEqual(a, b)

    def test_charger_aiming_elsewhere_is_ignored(self):
        old = motion.LASER_DODGE
        try:
            motion.LASER_DODGE = True
            m = Motion({'mech': {}}, seed=3)
            obs = make_obs()
            obs['mechs'] = [charger(aim_at_us=False)]
            self.assertEqual(m._lasers(obs, Floor(), {}), [])
            obs['mechs'] = [charger()]
            self.assertEqual(len(m._lasers(obs, Floor(), {})), 1)
        finally:
            motion.LASER_DODGE = old

    def test_release_eta_counts_from_first_sighting(self):
        m = Motion({'mech': {}}, seed=3)
        obs = make_obs()
        obs['mechs'] = [charger()]
        self.assertAlmostEqual(m._lasers(obs, Floor(), {})[0][2], motion.DODGE_RELEASE)
        obs['t'] += .5
        self.assertAlmostEqual(m._lasers(obs, Floor(), {})[0][2], motion.DODGE_RELEASE - .5)
        obs['mechs'][0]['charging'] = False
        m._lasers(obs, Floor(), {})
        self.assertEqual(m.charge_seen, {})

    def test_blocked_lane_is_ignored(self):
        class Wall(Floor):
            def clear(self, a, b):
                return False
        m = Motion({'mech': {}}, seed=3)
        obs = make_obs()
        obs['mechs'] = [charger()]
        self.assertEqual(m._lasers(obs, Wall(), {}), [])


if __name__ == '__main__':
    unittest.main()
