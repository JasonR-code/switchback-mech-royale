"""Injured-recovery lab: does holding fire on non-engaging rivals buy HP before a hunter arrives?

Builds on combat_squad.Squad with the full main.Pilot (no map) and adds what that
lab lacks: our HP regeneration (regen_per_s after regen_delay without dealing or
taking damage), a 200 m vision limit, idle rivals that look elsewhere, and a
hunter that arrives later from out of view.

ASSUMPTIONS (not measured): idle rivals never shoot unless provoked; with
--provoke, a rival we damage starts hunting us 0.6 s later. House-bot hearing,
shared vision and squad escalation are NOT modelled. There is no cover, so
breaking line of sight is impossible. Results show mechanism costs and benefits
under these assumptions; they are not placement evidence.

Usage: python validation/combat_recovery.py --bot-dir . --split fresh --cases 200 [--provoke] --json out.json
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

from combat_lab import DT, Mover, wrap
from combat_squad import Rival, Squad


class Recovery(Squad):
    def __init__(self, Combat, cfg, seed, pilot, provoke, duration=40.):
        super().__init__(Combat, cfg, seed, 'still', duration=duration, pilot=pilot)
        rng = random.Random(seed*13 + 7)
        self.provoke = provoke
        mech = cfg['mech']
        self.regen_delay, self.regen_rate = mech['regen_delay'], mech['regen_per_s']
        self.hp = 1400*rng.uniform(.3, .8)
        self.hp_taken = 1400 - self.hp   # observation() reads hp_taken
        self.quiet_since = -rng.uniform(0, 3)
        self.regen = 0.
        self.rivals = []
        self.band = {}
        base = rng.uniform(-math.pi, math.pi)
        for i in range(rng.choice((1, 2))):
            angle = base + i*rng.uniform(.8, 2.)
            d = rng.uniform(95, 190)
            r = Rival(rng, 3+i, (d*math.cos(angle), d*math.sin(angle), 0.), cfg, rng.random() < .4)
            r.role, r.look = 'idle', rng.uniform(-math.pi, math.pi)
            r.aim = [r.look, 0.]
            self.rivals.append(r)
            self.band[r.id] = (d*.8, d*1.15)
        if rng.random() < .75:
            angle = rng.uniform(-math.pi, math.pi)
            r = Rival(rng, 9, (230*math.cos(angle), 230*math.sin(angle), 0.), cfg, rng.random() < .4)
            r.role, r.look = 'dormant', 0.
            r.wake = rng.uniform(6, 25)
            self.rivals.append(r)
            self.band[r.id] = (225., 235.)
        self.stats.update(regen=0., provoked=0, hunter=any(r.role == 'dormant' for r in self.rivals))

    def observation(self, tick):
        obs = super().observation(tick)
        me = self.me.pos
        obs['mechs'] = [m for m in obs['mechs'] if math.hypot(m['pos'][0]-me[0], m['pos'][1]-me[1]) <= 200]
        obs['self']['hp'] = max(1., self.hp)
        return obs

    def hurt_rival(self, r, amount, weapon):
        super().hurt_rival(r, amount, weapon)
        self.quiet_since = self.t
        if self.provoke and r.role == 'idle':
            r.role, r.wake = 'provoked', self.t + .6
            self.band[r.id] = (50., 90.)
            self.stats['provoked'] += 1

    def hurt_me(self, r, amount, weapon, source):
        super().hurt_me(r, amount, weapon, source)
        self.hp -= amount if not self.events[-1].get('rear') else amount*1.5
        self.quiet_since = self.t

    def rival_tick(self, r):
        if r.role == 'idle':
            r.look = wrap(r.look + self.rng.gauss(0, .05))
            r.aim[0] = r.look
            return
        if r.role == 'dormant' and self.t >= r.wake:
            r.role = 'hunter'
            self.band[r.id] = (55., 95.)
        if r.role == 'dormant':
            return
        super().rival_tick(r)

    def tick(self, action, first):
        super().tick(action, first)
        self.hp_taken = 1400 - self.hp
        if self.t - self.quiet_since >= self.regen_delay and self.hp < 1400:
            gain = min(1400 - self.hp, self.regen_rate*DT)
            self.hp += gain
            self.regen += gain
            self.hp_taken = 1400 - self.hp

    def run(self):
        out = super().run()
        out['regen'] = round(self.regen, 1)
        out['end_hp'] = round(max(0., self.hp), 1)
        out['death'] = round(self.t, 2) if self.hp <= 0 else None
        out['shots'] = out['gun_shots'] + out['laser_shots']
        return out


def cases(split, count):
    base = {'dev': 4409, 'holdout': 88003, 'fresh': 733001}[split]
    return [base + 5113*i for i in range(count)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot-dir', type=Path, required=True)
    p.add_argument('--split', choices=('dev', 'holdout', 'fresh'), default='dev')
    p.add_argument('--cases', type=int, default=200)
    p.add_argument('--provoke', action='store_true')
    p.add_argument('--json', type=Path)
    a = p.parse_args()
    sys.path.insert(0, str(a.bot_dir.resolve()))
    from combat import Combat
    from main import Pilot
    cfg = json.loads((a.bot_dir/'defaults.json').read_text())
    out = []
    for seed in cases(a.split, a.cases):
        pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir=str(a.bot_dir/'no-map'))))
        row = dict(seed=seed, own='pilot')
        row.update(Recovery(Combat, cfg, seed, pilot, a.provoke).run())
        out.append(row)
    if a.json:
        a.json.write_text(json.dumps(out))
    s = lambda k: sum(r[k] for r in out)
    print(f"cases {len(out)} deaths {sum(r['death'] is not None for r in out)} regen {s('regen'):.0f} "
          f"end_hp {s('end_hp'):.0f} shots {s('shots')} dealt {s('dealt'):.0f} kills {s('kills')} provoked {s('provoked')}")


if __name__ == '__main__':
    main()
