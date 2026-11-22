"""Unseen shooter: damage events from unreported attackers, the glance intent, and the combat aim response."""
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_strategy import Plane, enemy, observed  # noqa: E402  (also puts the bot on sys.path)
from test_combat import CFG, Flat, observation  # noqa: E402
import strategy  # noqa: E402
from strategy import Strategy  # noqa: E402
import combat  # noqa: E402
from combat import Combat, wrap  # noqa: E402


def damaged(by, bearing, amount=45, weapon="gun"):
    return {"type": "damaged", "amount": amount, "weapon": weapon, "bearing": bearing, "by": by, "rear": True}


class DamageEventInterpretation(unittest.TestCase):
    def setUp(self):
        self.bot, self.obs = Strategy({}, 6), observed()
        self.obs["mechs"] = [enemy(5, 90, 0)]          # the rival we are fighting, in view

    def step(self, dt=.1, events=()):
        self.obs["t"] = round(self.obs["t"] + dt, 3)
        self.obs["tick"] = self.obs.get("tick", 0) + 2
        self.obs["events"] = list(events)
        return self.bot.plan(self.obs, Plane())

    def test_one_small_unreported_hit_is_not_credible(self):
        out = self.step(events=[damaged(9, 2.5)])
        self.assertIsNone(out["glance"])

    def test_repeated_unreported_hits_give_bearing(self):
        self.step(events=[damaged(9, 2.5)])
        out = self.step(dt=.6, events=[damaged(9, 2.6)])
        self.assertAlmostEqual(out["glance"], 2.6)
        self.assertAlmostEqual(out["scan"], 2.6, places=6)

    def test_one_heavy_unreported_hit_is_credible(self):
        out = self.step(events=[damaged(9, -2., amount=220, weapon="laser")])
        self.assertAlmostEqual(out["glance"], -2.)

    def test_hits_from_a_reported_rival_are_not_unseen(self):
        self.step(events=[damaged(5, 0.)])
        out = self.step(dt=.6, events=[damaged(5, 0.)])
        self.assertIsNone(out["glance"])

    def test_glance_expires_without_new_hits(self):
        self.step(events=[damaged(9, 2.5)])
        self.step(dt=.5, events=[damaged(9, 2.5)])
        self.assertIsNotNone(self.step(dt=2.)["glance"])
        self.assertIsNone(self.step(dt=.6)["glance"])

    def test_hits_spread_over_more_than_window_do_not_add_up(self):
        self.step(events=[damaged(9, 2.5)])
        self.assertIsNone(self.step(dt=3.2, events=[damaged(9, 2.5)])["glance"])

    def test_revealed_shooter_ends_glance(self):
        self.step(events=[damaged(9, 2.5)])
        self.assertIsNotNone(self.step(dt=.5, events=[damaged(9, 2.5)])["glance"])
        self.obs["mechs"].append(enemy(9, 100*math.cos(2.5), 100*math.sin(2.5)))
        self.assertIsNone(self.step()["glance"])

    def test_zone_damage_ignored(self):
        z = {"type": "damaged", "amount": 200, "weapon": "zone", "bearing": None, "by": None}
        self.assertIsNone(self.step(events=[z, z])["glance"])

    def test_switch_off(self):
        old = strategy.UNSEEN
        try:
            strategy.UNSEEN = False
            self.step(events=[damaged(9, 2.5)])
            self.assertIsNone(self.step(dt=.5, events=[damaged(9, 2.5)])["glance"])
        finally:
            strategy.UNSEEN = old


class GlanceAim(unittest.TestCase):
    def aim(self, glance, hp=1400):
        obs = observation('gun', distance=100, hp=hp)    # healthy target due east (yaw 0)
        return Combat(CFG).act(obs, Flat(), {"glance": glance})['aim'][0]

    def test_turns_until_shooter_bearing_is_in_view(self):
        yaw = self.aim(math.pi)
        self.assertLessEqual(abs(wrap(yaw - math.pi)), combat.GLANCE_KEEP + 1e-6)
        self.assertLess(abs(wrap(yaw - math.pi)), math.radians(60))   # inside the 120 deg wedge

    def test_shooter_already_in_view_keeps_target_aim(self):
        base = self.aim(None)
        self.assertAlmostEqual(self.aim(.3), base, places=6)

    def test_nearly_dead_target_is_not_abandoned(self):
        base = self.aim(None, hp=200)
        self.assertAlmostEqual(self.aim(math.pi, hp=200), base, places=6)

    def test_no_target_looks_straight_at_shooter(self):
        obs = observation('gun', distance=100)
        obs['mechs'] = []
        yaw = Combat(CFG).act(obs, Flat(), {"glance": 2., "scan": 2.})['aim'][0]
        self.assertAlmostEqual(yaw, 2., places=6)


if __name__ == '__main__':
    unittest.main()
