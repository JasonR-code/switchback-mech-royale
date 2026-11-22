"""Regression tests for tick-exact launch, rear-arc exposure and shell drift forecasts."""
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_combat import CFG, Flat, observation  # noqa: E402  (also fixes sys.path to the bot)
import combat  # noqa: E402
from combat import Combat, DriftTrack, drifting, rear_exposure  # noqa: E402


class LaunchTiming(unittest.TestCase):
    def test_own_motion_shifts_gun_origin(self):
        # Strafing north at walk speed: the bullet spawns from the muzzle one tick
        # later, so a still target due east needs a slightly southward yaw.
        still = observation('gun', distance=120)
        moving = observation('gun', distance=120)
        moving['self']['vel'] = [0., 11.7, 0.]
        a = Combat(CFG).act(still, Flat(), {})['aim'][0]
        b = Combat(CFG).act(moving, Flat(), {})['aim'][0]
        expected = -math.atan2(11.7*.05, 120)
        self.assertAlmostEqual(a, 0., places=4)
        self.assertAlmostEqual(b, expected, delta=.0015)

    def test_ready_gun_leads_from_observation_time(self):
        # Ready now: the shot fires on tick 1 and behaves as launched at obs time,
        # so the lead equals the zero-delay intercept (no half-tick offset).
        obs = observation('gun', distance=150, velocity=(0., 10., 0.))
        yaw = Combat(CFG).act(obs, Flat(), {})['aim'][0]
        delta = (150., 0., 4.59 - 7.)
        sol = combat.gun_solution(delta, (0., 10., 0.), 252., 3.)
        self.assertAlmostEqual(yaw, sol[0], delta=.002)

    def test_second_tick_shot_adds_one_tick_of_target_motion(self):
        ready = observation('gun', distance=150, velocity=(0., 10., 0.))
        late = observation('gun', distance=150, velocity=(0., 10., 0.))
        late['self']['weapons'][0]['cooldown'] = .08
        a = Combat(CFG).act(ready, Flat(), {})['aim'][0]
        b = Combat(CFG).act(late, Flat(), {})['aim'][0]
        self.assertAlmostEqual(b - a, math.atan2(10*.05, 150), delta=.0012)


class RearArc(unittest.TestCase):
    def test_exposure_counts_only_rivals_outside_front_arc(self):
        threats = [(0., 1., math.pi/2), (math.pi, .5, math.pi/2)]
        self.assertEqual(rear_exposure(threats, 0.), .5)
        self.assertEqual(rear_exposure(threats, math.pi), 1.)
        self.assertEqual(rear_exposure(threats, math.pi/4), .5)

    def test_prefers_target_that_keeps_aimed_rival_in_front(self):
        # Two equal rivals 150 degrees apart; the one we would turn our back on
        # is charging a laser at us, so face it.
        obs = observation('gun', distance=80)
        laser = dict(id=2, kind='mech', pos=[80*math.cos(2.6), 80*math.sin(2.6), 0], vel=(0, 0, 0), hp=1400,
                     weapons=['gun', 'laser'], aim=[2.6 - math.pi, 0], charging=True)
        obs['mechs'][0]['aim'] = [math.pi + 1.2, 0]  # gun rival looks elsewhere
        obs['mechs'].append(laser)
        obs['self']['aim'] = [1.3, 0]
        yaw = Combat(CFG).act(obs, Flat(), {})['aim'][0]
        self.assertLess(abs(combat.wrap(yaw - 2.6)), .2)


class ShellDrift(unittest.TestCase):
    def feed(self, velocity_at, seconds=8.):
        track = DriftTrack()
        x = y = 0.
        t = 0.
        while t < seconds:
            vx, vy = velocity_at(t)
            track.step(t, (x, y, 0.), (vx, vy, 0.))
            x, y, t = x + vx*.1, y + vy*.1, round(t + .1, 3)
        return track, velocity_at(t)

    def test_straight_mover_keeps_linear_lead(self):
        track, v = self.feed(lambda t: (12., 0.))
        self.assertEqual(drifting((12., 0., 0.), track, 2.), (12., 0., 0.))

    def test_strafer_is_led_toward_its_mean(self):
        track, v = self.feed(lambda t: (2., 12. if int(t/.8) % 2 == 0 else -12.))
        mean = drifting((v[0], v[1], 0.), track, 2.)
        self.assertGreater(track.drift(2.), .5)
        self.assertLess(abs(mean[1]), abs(v[1])*.6)

    def test_no_history_defaults_to_linear(self):
        self.assertEqual(drifting((5., 1., 0.), DriftTrack(), 2.), (5., 1., 0.))
        self.assertEqual(drifting((5., 1., 0.), None, 2.), (5., 1., 0.))


class LowProfileRecovery(unittest.TestCase):
    """While hurt and unharmed for a moment, leave non-engaging rivals alone."""
    def act(self, hp=700, distance=130, foe_aim=math.pi/2, foe_hp=1400, events=(), **intent):
        obs = observation('gun', distance=distance, hp=foe_hp)
        obs['self']['hp'] = hp
        obs['mechs'][0]['aim'] = [foe_aim, 0]
        obs['events'] = list(events)
        return Combat(CFG).act(obs, Flat(), intent)['fire'][0]

    def test_holds_fire_on_distant_rival_looking_away_when_hurt(self):
        self.assertFalse(self.act())

    def test_fires_when_healthy(self):
        self.assertTrue(self.act(hp=1300))

    def test_fires_at_rival_aiming_at_us(self):
        self.assertTrue(self.act(foe_aim=math.pi))

    def test_fires_at_close_rival(self):
        self.assertTrue(self.act(distance=60))

    def test_finishes_nearly_dead_rival(self):
        self.assertTrue(self.act(foe_hp=150))

    def test_returns_fire_at_recent_attacker(self):
        hit = dict(type='damaged', by=1, amount=45, weapon='gun', bearing=0.)
        self.assertTrue(self.act(events=[hit]))

    def test_not_quiet_while_another_rival_is_hitting_us(self):
        # Regeneration is already blocked, so no reason to hold fire.
        hit = dict(type='damaged', by=7, amount=45, weapon='gun', bearing=2.)
        self.assertTrue(self.act(events=[hit]))

    def test_disabled_by_constant(self):
        old = combat.LOW_PROFILE_HP
        try:
            combat.LOW_PROFILE_HP = 0
            self.assertTrue(self.act())
        finally:
            combat.LOW_PROFILE_HP = old


if __name__ == '__main__':
    unittest.main()
