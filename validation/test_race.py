"""Kill race: commit to a rival we are measurably about to kill instead of retreating."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_strategy import Plane, enemy, observed  # noqa: E402
import strategy  # noqa: E402
from strategy import Strategy  # noqa: E402


def hit(target, amount=100):
    return {"type": "hit", "target": target, "amount": amount, "weapon": "gun"}


def took(by, amount, bearing=0.):
    return {"type": "damaged", "amount": amount, "weapon": "gun", "bearing": bearing, "by": by}


class KillRace(unittest.TestCase):
    def setUp(self):
        self.bot, self.obs = Strategy({}, 6), observed()
        self.obs["self"]["hp"] = 560          # 40%: the 4.85 HP rule retreats from any pressure
        self.obs["mechs"] = [enemy(5, 80, 0, hp=200)]

    def step(self, events=(), dt=.5):
        self.obs["t"] = round(self.obs["t"] + dt, 3)
        self.obs["events"] = list(events)
        return self.bot.plan(self.obs, Plane())

    def test_baseline_rule_retreats_without_evidence(self):
        self.assertTrue(self.step()["escape"])

    def test_measured_kill_holds_the_fight_and_focus(self):
        self.step([hit(5)])
        out = self.step([hit(5)])
        self.assertFalse(out["escape"])
        self.assertEqual(out["focus"], 5)

    def test_single_hit_is_not_evidence(self):
        self.assertTrue(self.step([hit(5)])["escape"])

    def test_healthy_target_is_not_a_race(self):
        self.obs["mechs"] = [enemy(5, 80, 0, hp=1000)]
        self.step([hit(5)])
        self.assertTrue(self.step([hit(5)])["escape"])

    def test_heavy_incoming_damage_still_retreats(self):
        self.step([hit(5), took(5, 300)])
        self.assertTrue(self.step([hit(5), took(5, 300)])["escape"])

    def test_crossfire_commit_needs_the_race_to_add_up(self):
        self.obs["mechs"] = [enemy(5, 80, 0, hp=200), enemy(6, -90, 30)]
        self.step([hit(5)])
        self.assertFalse(self.step([hit(5)])["escape"])
        self.obs["self"]["hp"] = 560
        self.step([hit(5), took(6, 250, 2.8)])
        self.assertTrue(self.step([hit(5), took(6, 250, 2.8)])["escape"])

    def test_old_hits_expire(self):
        self.step([hit(5)])
        self.step([hit(5)])
        self.assertTrue(self.step(dt=3.)["escape"])

    def test_late_game_and_switch_off(self):
        self.obs["alive"] = 16 - strategy.SNOWBALL_UNTIL_DEAD
        self.step([hit(5)])
        self.assertTrue(self.step([hit(5)])["escape"])
        old = strategy.RACE
        try:
            strategy.RACE = False
            bot, self.bot = self.bot, Strategy({}, 6)
            self.obs["alive"] = 16
            self.step([hit(5)])
            self.assertTrue(self.step([hit(5)])["escape"])
        finally:
            strategy.RACE = old


if __name__ == "__main__":
    unittest.main()
