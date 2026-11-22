"""Snowball policy: bystanders do not trigger retreat early; engaged rivals still do."""
import math
import unittest

from test_strategy import Plane, enemy, observed
import strategy
from strategy import Strategy


def looking_away(i, x, y, hp=1400):
    e = enemy(i, x, y, hp)
    e["aim"] = [math.atan2(-y, -x) + math.pi/2, 0]
    return e


class SnowballEscape(unittest.TestCase):
    def setUp(self):
        self.obs = observed()
        self.obs["self"]["hp"] = 900          # 64%: two "visible" rivals would trigger escape at 4.63
        self.bot = Strategy({}, 6)

    def plan(self):
        return self.bot.plan(self.obs, Plane())

    def test_hunter_plus_bystander_is_not_a_crossfire(self):
        self.obs["mechs"] = [enemy(5, 90, 0), looking_away(6, -120, 40)]
        self.assertFalse(self.plan()["escape"])

    def test_two_rivals_aiming_at_us_still_escape(self):
        self.obs["mechs"] = [enemy(5, 90, 0), enemy(6, -120, 40)]
        self.assertTrue(self.plan()["escape"])

    def test_close_bystander_counts_as_engaging(self):
        self.obs["mechs"] = [enemy(5, 90, 0), looking_away(6, -40, 20)]
        self.assertTrue(self.plan()["escape"])

    def test_rival_that_just_hit_us_counts_even_when_turned(self):
        self.obs["mechs"] = [enemy(5, 90, 0), looking_away(6, -120, 40)]
        self.obs["events"] = [{"type": "damaged", "amount": 45, "weapon": "gun", "bearing": 2.8, "by": 6}]
        self.assertTrue(self.plan()["escape"])

    def test_late_game_reverts_to_baseline(self):
        self.obs["alive"] = 16 - strategy.SNOWBALL_UNTIL_DEAD
        self.obs["mechs"] = [enemy(5, 90, 0), looking_away(6, -120, 40)]
        self.assertTrue(self.plan()["escape"])

    def test_switch_off_restores_baseline(self):
        old = strategy.SNOWBALL
        try:
            strategy.SNOWBALL = False
            self.obs["mechs"] = [enemy(5, 90, 0), looking_away(6, -120, 40)]
            self.assertTrue(self.plan()["escape"])
        finally:
            strategy.SNOWBALL = old


class Spoils(unittest.TestCase):
    def test_kill_leaves_a_cube_destination(self):
        bot, obs = Strategy({}, 6), observed()
        obs["mechs"] = [enemy(5, 60, 0, hp=40)]
        bot.plan(obs, Plane())
        obs.update(t=10.5, tick=210, mechs=[], events=[{"type": "kill", "target": 5}])
        out = bot.plan(obs, Plane())
        self.assertEqual(bot.last_goal[2], "spoils")
        self.assertLess(math.dist(out["goal"][:2], (60, 0)), 1)


if __name__ == "__main__":
    unittest.main()
