"""Match-like snowball lab: tiered rivals, escalation, retreat-and-regenerate, cubes from kills.

The full main.Pilot (no map) fights 6 scripted rivals for up to 120 s.

ASSUMPTIONS (not measured on house bots):
- tiers (easy/medium/hard/expert) differ in aim jitter, lead and laser share;
- one rival hunts us at the start and one more joins after each of our kills,
  following the track page's "one early, more as you thin them out";
- a rival we damage starts hunting;
- a rival below 35% HP withdraws beyond vision, regenerates by the mech rules
  and returns at 85%;
- kills drop 2 cubes (+4% max HP and damage each, rules section 10).

Rules modelled: our regeneration, 200 m vision, laser/gun mechanics from combat_squad.
Not modelled: map, cover, loot crates, drones, zone, sound, upgrades. A gain here
says the policy acts as designed under these assumptions; it is not placement evidence.

Usage: python validation/combat_snowball.py --bot-dir . --split fresh --cases 120 --json out.json
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

from combat_lab import DT, wrap
from combat_squad import Rival, Squad

TIERS = {'easy': (.06, .3, .1), 'medium': (.035, .55, .3), 'hard': (.02, .8, .5), 'expert': (.01, .95, .7)}


class Snowball(Squad):
    def __init__(self, Combat, cfg, seed, pilot, duration=120., scale=1., provoke=True, fov=False):
        super().__init__(Combat, cfg, seed, 'still', duration=duration, pilot=pilot)
        # fov: protocol section 8 vision (120 deg wedge on our aim, 45 m proximity, 5 s tracking memory).
        self.fov, self.seen_t = fov, {}
        self.hidden_dmg, self.hidden_events = 0., []
        rng = random.Random(seed*17 + 3)
        self.scale, self.provoke = scale, provoke
        mech = cfg['mech']
        self.regen_delay, self.regen_rate = mech['regen_delay'], mech['regen_per_s']
        self.max_hp = self.hp = 1400.
        self.hp_taken = 0.
        self.quiet_since = 0.
        self.cube_count = 0
        self.cube_items = []
        self.next_cube = 5000
        self.travel = 0.
        self.rivals, self.band = [], {}
        tiers = ['easy', 'easy', 'medium', 'medium', 'hard', 'expert']
        rng.shuffle(tiers)
        for i, tier in enumerate(tiers):
            angle = rng.uniform(-math.pi, math.pi)
            d = rng.uniform(70, 260)
            jitter, lead, laser = TIERS[tier]
            r = Rival(rng, 3+i, (d*math.cos(angle), d*math.sin(angle), 0.), cfg, rng.random() < laser)
            r.jitter, r.lead, r.tier = jitter, lead, tier
            r.role, r.look, r.quiet = 'idle', rng.uniform(-math.pi, math.pi), 0.
            r.home = d
            self.rivals.append(r)
            self.band[r.id] = (d*.85, d*1.15)
        first = min(self.rivals, key=lambda r: r.home)
        self.hunt(first)
        self.stats.update(cubes=0, kills_60=0, kills_120=0, death_60=False, travel=0., failed_hunts=0)

    def hunt(self, r):
        if r.alive and r.role in ('idle', 'withdrawn'):
            r.role = 'hunter'
            r.wake = self.t + .6
            self.band[r.id] = (45., 95.)

    def observation(self, tick):
        obs = super().observation(tick)
        me = self.me.pos
        obs['mechs'] = [m for m in obs['mechs'] if math.hypot(m['pos'][0]-me[0], m['pos'][1]-me[1]) <= 200]
        if self.fov:
            vision = self.cfg.get('vision', {})
            half = math.radians(vision.get('fov_deg', 120))/2
            near, memory = vision.get('near_range', 45), vision.get('memory_s', 5)
            kept = []
            for m in obs['mechs']:
                d = math.hypot(m['pos'][0]-me[0], m['pos'][1]-me[1])
                yaw = math.atan2(m['pos'][1]-me[1], m['pos'][0]-me[0])
                if d <= near or abs(wrap(yaw - self.aim[0])) <= half:
                    self.seen_t[m['id']] = self.t
                if self.t - self.seen_t.get(m['id'], -1e9) <= memory:
                    kept.append(m)
            obs['mechs'] = kept
        obs['self'].update(hp=max(1., self.hp), max_hp=self.max_hp, cubes=self.cube_count)
        obs['cubes'] = [dict(id=c[0], pos=list(c[1])) for c in self.cube_items if math.dist(c[1][:2], me[:2]) <= 200]
        obs['alive'] = 16 - self.stats['kills']
        return obs

    def hurt_rival(self, r, amount, weapon):
        was_alive = r.alive
        amount *= 1 + .04*min(self.cube_count, 10)
        super().hurt_rival(r, amount, weapon)
        r.quiet = self.t
        self.quiet_since = self.t
        if r.role == 'idle' and self.provoke:
            self.hunt(r)
        if was_alive and not r.alive:
            if self.t <= 60:
                self.stats['kills_60'] += 1
            if self.t <= 120:
                self.stats['kills_120'] += 1
            for k in range(2):
                self.cube_items.append((self.next_cube, (r.body.pos[0]+k, r.body.pos[1], 0.)))
                self.next_cube += 1
            idle = [q for q in self.rivals if q.alive and q.role == 'idle']
            if idle:
                self.hunt(min(idle, key=lambda q: math.dist(q.body.pos[:2], self.me.pos[:2])))

    def hurt_me(self, r, amount, weapon, source):
        amount *= self.scale
        if self.fov and self.t - self.seen_t.get(r.id, -1e9) > self.cfg.get('vision', {}).get('memory_s', 5):
            self.hidden_events.append((round(self.t, 2), r.id, amount))
        super().hurt_me(r, amount, weapon, source)
        if self.fov and self.hidden_events and self.hidden_events[-1][0] == round(self.t, 2) and self.hidden_events[-1][1] == r.id:
            self.hidden_dmg += self.events[-1]['amount']
        self.hp -= amount*(1.5 if self.events[-1].get('rear') else 1.)
        self.quiet_since = self.t

    def rival_tick(self, r):
        if r.role in ('idle', 'withdrawn'):
            r.look = wrap(r.look + self.rng.gauss(0, .05))
            r.aim[0] = r.look
            if r.role == 'withdrawn' and r.hp >= .85*1400:
                self.hunt(r)
            return
        if r.hp < .35*1400:
            r.role = 'withdrawn'
            self.band[r.id] = (240., 270.)
            return
        super().rival_tick(r)

    def tick(self, action, first):
        before = list(self.me.pos)
        super().tick(action, first)
        self.travel += math.dist(before[:2], self.me.pos[:2])
        for r in self.rivals:
            if r.alive and r.role == 'withdrawn' and self.t - r.quiet >= self.regen_delay:
                r.hp = min(1400., r.hp + self.regen_rate*DT)
        if self.t - self.quiet_since >= self.regen_delay and self.hp < self.max_hp:
            self.hp = min(self.max_hp, self.hp + self.regen_rate*DT)
        kept = []
        for cid, pos in self.cube_items:
            if math.dist(pos[:2], self.me.pos[:2]) <= 3.5:
                self.cube_count += 1
                if self.cube_count <= 10:
                    self.max_hp += 56.
                    self.hp += 56.
                self.events.append(dict(type='pickup', cubes=self.cube_count))
            else:
                kept.append((cid, pos))
        self.cube_items = kept
        self.hp_taken = self.max_hp - self.hp

    def run(self):
        tick = 0
        while self.t < self.duration - 1e-9 and any(r.alive for r in self.rivals) and self.hp > 0:
            obs = self.observation(tick)
            action = self.pilot.act(obs)
            move = action.get('move') or (0., 0.)
            self.move, self.boost = (float(move[0]), float(move[1])), bool(action.get('boost'))
            self.events = []
            if action.get('aim'):
                self.cmd = list(action['aim'])
            self.tick(action, True)
            self.tick(action, False)
            tick += 2
        out = dict(self.stats)
        out.update(death=round(self.t, 2) if self.hp <= 0 else None, cubes=self.cube_count,
                   travel=round(self.travel, 1), end_hp=round(max(0., self.hp), 1),
                   death_60=self.hp <= 0 and self.t <= 60,
                   outlasted=self.stats['kills'], hidden_taken=round(self.hidden_dmg, 1),
                   hidden_hits=len(self.hidden_events),
                   abandoned=sum(1 for r in self.rivals if r.alive and r.hp < 1400*.35 or (r.alive and r.role == 'withdrawn')))
        for k in ('dealt', 'taken', 'rear'):
            out[k] = round(out[k], 1)
        return out


def cases(split, count):
    base = {'dev': 12011, 'holdout': 47017, 'fresh': 90031}[split]
    return [base + 3911*i for i in range(count)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot-dir', type=Path, required=True)
    p.add_argument('--split', choices=('dev', 'holdout', 'fresh'), default='dev')
    p.add_argument('--cases', type=int, default=120)
    p.add_argument('--json', type=Path)
    p.add_argument('--rival-damage', type=float, default=1., help='scale on damage rivals deal (stand-in for cover)')
    p.add_argument('--no-provoke', action='store_true', help='rivals we shoot do not start hunting')
    p.add_argument('--fov', action='store_true', help='protocol vision: 120 deg wedge, 45 m proximity, 5 s memory')
    a = p.parse_args()
    sys.path.insert(0, str(a.bot_dir.resolve()))
    from combat import Combat
    from main import Pilot
    cfg = json.loads((a.bot_dir/'defaults.json').read_text())
    out = []
    for seed in cases(a.split, a.cases):
        pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir=str(a.bot_dir/'no-map'))))
        row = dict(seed=seed)
        row.update(Snowball(Combat, cfg, seed, pilot, scale=a.rival_damage, provoke=not a.no_provoke, fov=a.fov).run())
        out.append(row)
    if a.json:
        a.json.write_text(json.dumps(out))
    s = lambda k: sum(r[k] for r in out)
    print(f"cases {len(out)} kills {s('kills')} deaths {sum(r['death'] is not None for r in out)} cubes {s('cubes')}")


if __name__ == '__main__':
    main()
