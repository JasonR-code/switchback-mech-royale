"""Open-field fire-control lab: one shooter driven by combat.Combat versus one moving mech.

Isolates aiming and trigger decisions from navigation and strategy. No walls, loot,
squad logic or return fire. Tick ordering follows what the public recording
(check/stream.jsonl.gz) shows: within a 0.05 s tick a mech slews and moves first,
then a weapon whose cooldown has reached zero fires from the post-move muzzle,
and a new bullet also travels a full tick in that same tick (see
validation/COMBAT.md). Target-side ordering inside a tick is assumed, not measured.

Usage: python validation/combat_lab.py --bot-dir . --split dev --cases 60 --json out.json
Run once per bot directory (the baseline lives in a separate worktree) and
compare with validation/combat_compare.py.
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

DT = .05
STYLES = ('house', 'jink', 'circle', 'straight', 'stopgo', 'still')
LOADOUTS = ('gun', 'gun+laser', 'gun+mortar', 'gun+lightning')
OWN = ('still', 'strafe', 'walk')


def wrap(a):
    return (a + math.pi) % (2*math.pi) - math.pi


def clamp(x, a, b):
    return max(a, min(b, x))


class OpenField:
    """Arena stand-in. Nothing blocks sight or shots."""
    def clear(self, a, b):
        return True


def ray_cylinder(origin, u, length, feet, radius, height):
    """Distance along a ray to a vertical cylinder, or None."""
    ox, oy = origin[0]-feet[0], origin[1]-feet[1]
    a = u[0]*u[0] + u[1]*u[1]
    b = ox*u[0] + oy*u[1]
    c = ox*ox + oy*oy - radius*radius
    lo, hi = 0., length
    if a > 1e-12:
        disc = b*b - a*c
        if disc < 0:
            return None
        r = math.sqrt(disc)
        lo, hi = max(lo, (-b-r)/a), min(hi, (-b+r)/a)
    elif c > 0:
        return None
    oz = origin[2]-feet[2]
    if abs(u[2]) > 1e-12:
        z1, z2 = sorted(((0-oz)/u[2], (height-oz)/u[2]))
        lo, hi = max(lo, z1), min(hi, z2)
    elif not 0 <= oz <= height:
        return None
    return lo if lo <= hi else None


def swept_entry(a, b, feet0, feet1, radius, height):
    """Fraction of a tick at which segment a->b enters a cylinder moving feet0->feet1."""
    rel_a = [a[i]-feet0[i] for i in range(3)]
    rel_b = [b[i]-feet1[i] for i in range(3)]
    d = [rel_b[i]-rel_a[i] for i in range(3)]
    length = math.sqrt(sum(x*x for x in d))
    if length < 1e-12:
        inside = math.hypot(rel_a[0], rel_a[1]) <= radius and 0 <= rel_a[2] <= height
        return 0. if inside else None
    u = [x/length for x in d]
    hit = ray_cylinder(rel_a, u, length, (0., 0., 0.), radius, height)
    return None if hit is None else hit/length


class Mover:
    """Scripted horizontal motion with the official acceleration limit."""
    def __init__(self, rng, style, pos, top=19.5):
        self.rng, self.style = rng, style
        self.pos, self.vel = list(pos), [0., 0., 0.]
        self.top = top
        self.next = 0.
        self.sign = rng.choice((-1, 1))
        self.speed = rng.uniform(6, 17)
        self.radial = rng.uniform(-6, 4)
        self.heading = rng.uniform(-math.pi, math.pi)
        self.rate = rng.uniform(.6, 2.)*rng.choice((-1, 1))
        self.parked = False
        self.slow = False

    def desired(self, t, other, band):
        r = self.rng
        dx, dy = other[0]-self.pos[0], other[1]-self.pos[1]
        d = max(1., math.hypot(dx, dy))
        ux, uy = dx/d, dy/d
        s = self.style
        if s == 'still':
            return 0., 0.
        if t >= self.next:
            if s == 'house':
                self.sign *= -1
                self.next = t + r.uniform(.35, 1.2)
                if r.random() < .3:
                    self.radial = r.uniform(-6, 4)
                self.speed = r.uniform(6, 17)
                self.slow = r.random() < .2
            elif s == 'jink':
                self.heading = r.uniform(-math.pi, math.pi)
                self.speed = r.uniform(8, 19.5)
                self.next = t + r.uniform(.3, 1.4)
            elif s == 'stopgo':
                self.parked = not self.parked
                self.heading = r.uniform(-math.pi, math.pi)
                self.speed = r.uniform(8, 17)
                self.next = t + (r.uniform(.3, 1.) if self.parked else r.uniform(.4, 1.2))
            elif s == 'strafe':
                self.sign *= -1
                self.speed = 11.7
                self.next = t + r.uniform(.5, 1.5)
            else:
                self.next = math.inf
        if s in ('house', 'strafe'):
            lat = self.sign*self.speed*(.5 if self.slow else 1.)
            rad = self.radial if s == 'house' else 0.
            vx, vy = -uy*lat + ux*rad, ux*lat + uy*rad
        elif s == 'circle':
            h = self.heading + self.rate*t
            vx, vy = self.speed*math.cos(h), self.speed*math.sin(h)
        elif s == 'stopgo' and self.parked:
            vx, vy = 0., 0.
        else:
            vx, vy = self.speed*math.cos(self.heading), self.speed*math.sin(self.heading)
        # Keep the engagement inside the sampled distance band.
        lo, hi = band
        if d > hi:
            vx, vy = vx + ux*8, vy + uy*8
        elif d < lo:
            vx, vy = vx - ux*8, vy - uy*8
        return vx, vy

    def step(self, t, other, band, cap=None):
        tx, ty = self.desired(t, other, band)
        top = cap or self.top
        m = math.hypot(tx, ty)
        if m > top:
            tx, ty = tx*top/m, ty*top/m
        ox, oy = self.vel[:2]
        gap = math.hypot(tx-ox, ty-oy)
        f = min(1., 58.5*DT/gap) if gap > 1e-9 else 1.
        vx, vy = ox + f*(tx-ox), oy + f*(ty-oy)
        self.pos = [self.pos[0] + .5*DT*(ox+vx), self.pos[1] + .5*DT*(oy+vy), 0.]
        self.vel = [vx, vy, 0.]


class Duel:
    def __init__(self, Combat, cfg, seed, loadout, style, own, duration=15.):
        rng = random.Random(seed)
        self.rng = rng
        self.spray = random.Random(seed*7 + 3)
        self.cfg = cfg
        self.combat = Combat(cfg)
        self.arena = OpenField()
        self.duration = duration
        self.loadout = loadout
        near = loadout == 'gun+lightning'
        dist = rng.uniform(14, 38) if near else rng.uniform(25, 190)
        band = (max(8., dist*.6), dist*1.35 + 10)
        self.band = band
        angle = rng.uniform(-math.pi, math.pi)
        self.me = Mover(rng, own, (0., 0., 0.), top=11.7)
        self.foe = Mover(rng, style, (dist*math.cos(angle), dist*math.sin(angle), 0.))
        self.aim = [rng.uniform(-math.pi, math.pi), 0.]
        self.cmd = list(self.aim)
        self.foe_secondary = rng.choice(([], ['laser'], ['mortar'], ['lightning']))
        self.foe_hp = 1400.
        self.energy, self.spent_at = 100., -9.
        w = cfg['weapons']
        self.slots = [dict(kind='gun', cooldown=0., ammo=w['gun']['mag'], reload=0., charge=0., stats=dict(w['gun']))]
        second = loadout.split('+')[1] if '+' in loadout else None
        self.slots.append(dict(kind=second, cooldown=0., ammo=0, reload=0., charge=0., stats=dict(w[second]))
                          if second else None)
        self.bullets, self.shells = [], []
        self.t = 0.
        self.events = []
        self.stats = dict(gun_shots=0, gun_hits=0, laser_shots=0, laser_hits=0, laser_damage=0.,
                          mortar_shots=0, mortar_damage=0., arc_shots=0, arc_hits=0,
                          damage=0., kill_time=None, kills=0, charge_ticks=0, dist=round(dist, 1))

    def observation(self, tick):
        weapons = []
        for s in self.slots:
            weapons.append(None if s is None else {k: (round(v, 3) if isinstance(v, float) else v)
                                                   for k, v in s.items()})
        fx, fy, _ = self.foe.pos
        mx, my, _ = self.me.pos
        foe_aim = math.atan2(my-fy, mx-fx)
        charging = 'laser' in self.foe_secondary and self.foe.slow
        return {
            'type': 'obs', 'tick': tick, 't': round(self.t, 3), 'alive': 2,
            'self': dict(id=0, pos=list(self.me.pos), vel=list(self.me.vel), aim=list(self.aim), hp=1400,
                         max_hp=1400, energy=self.energy, max_energy=100, grounded=True, cubes=0,
                         upgrades=[], in_zone=True, weapons=weapons, stats=dict(self.cfg['mech'])),
            'mechs': [dict(id=5, kind='mech', pos=list(self.foe.pos), vel=list(self.foe.vel),
                           aim=[foe_aim, 0.], hp=max(1., round(self.foe_hp, 2)), max_hp=1400, cubes=0,
                           weapons=['gun'] + self.foe_secondary, charging=charging)],
            'crates': [], 'projectiles': [], 'pickups': [], 'cubes': [], 'sounds': [], 'beams': [],
            'events': self.events, 'drops': [], 'zone': {}, 'offer': None,
        }

    def damage(self, amount):
        self.stats['damage'] += amount
        self.events.append(dict(type='hit', target=5, amount=amount, weapon='gun'))
        self.foe_hp -= amount
        if self.foe_hp <= 0:
            # A fresh 1400 HP rival keeps the damage rate measurable after a kill.
            if self.stats['kill_time'] is None:
                self.stats['kill_time'] = round(self.t, 2)
            self.stats['kills'] += 1
            self.foe_hp = 1400.

    def direction(self, spread=0.):
        yaw, pitch = self.aim
        if spread:
            yaw += math.radians(self.spray.gauss(0, spread))
            pitch += math.radians(self.spray.gauss(0, spread))
        return [math.cos(yaw)*math.cos(pitch), math.sin(yaw)*math.cos(pitch), math.sin(pitch)]

    def tick(self, action, first):
        mech = self.cfg['mech']
        # 1. Torso slew.
        yaw, pitch = self.cmd
        self.aim[0] = wrap(self.aim[0] + clamp(wrap(yaw-self.aim[0]), -mech['turn_rate']*DT, mech['turn_rate']*DT))
        target_pitch = clamp(pitch, mech['min_pitch'], mech['max_pitch'])
        self.aim[1] += clamp(target_pitch-self.aim[1], -mech['pitch_rate']*DT, mech['pitch_rate']*DT)
        # 2. Movement.
        charging = any(s and s['kind'] == 'laser' and s['charge'] > 0 for s in self.slots)
        self.stats['charge_ticks'] += charging
        foe_before = list(self.foe.pos)
        self.me.step(self.t, self.foe.pos, (0, 1e9), cap=11.7*(.5 if charging else 1.))
        self.foe.step(self.t, self.me.pos, self.band, cap=19.5*(.5 if self.foe.slow and 'laser' in self.foe_secondary else 1.))
        self.t += DT
        muzzle = [self.me.pos[0], self.me.pos[1], 7.]
        fire = action.get('fire') or [False, False]
        # 3. Weapons (cooldown first, then trigger).
        for i, s in enumerate(self.slots):
            if s is None:
                continue
            st = s['stats']
            s['cooldown'] = max(0., s['cooldown']-DT)
            held = bool(fire[i]) if i < len(fire) else False
            if s['kind'] == 'gun':
                if s['reload'] > 0:
                    s['reload'] = max(0., s['reload']-DT)
                    if s['reload'] <= 1e-9:
                        s['ammo'], s['reload'] = st['mag'], 0.
                    continue
                if first and action.get('reload') and s['ammo'] < st['mag']:
                    s['reload'] = st['reload']
                    continue
                if held and s['cooldown'] <= 1e-9 and s['ammo'] > 0:
                    s['ammo'] -= 1
                    s['cooldown'] = st['cooldown']
                    if s['ammo'] == 0:
                        s['reload'] = st['reload']
                    u = self.direction(st['spread_deg'])
                    start = [muzzle[j] + 3*u[j] for j in range(3)]
                    self.bullets.append(dict(pos=start, u=u, left=st['range'], new=True))
                    self.stats['gun_shots'] += 1
            elif s['kind'] == 'laser':
                if s['cooldown'] > 1e-9:
                    continue
                full = st['charge']
                release = False
                if held or (0 < s['charge'] < st['min_charge']):
                    s['charge'] = min(full + st['hold_s'], s['charge'] + DT)
                    release = s['charge'] >= full + st['hold_s'] - 1e-9 or (not held and s['charge'] >= st['min_charge'])
                elif s['charge'] > 0:
                    release = True
                if release:
                    frac = min(1., s['charge']/full)
                    amount = st['damage']*(st['min_frac'] + (1-st['min_frac'])*frac)
                    if 'mortar' in self.foe_secondary:
                        amount *= 1 + st['cookoff']
                    self.stats['laser_shots'] += 1
                    hit = ray_cylinder(muzzle, self.direction(), st['range'], self.foe.pos, 2.5, 9)
                    if hit is not None:
                        self.stats['laser_hits'] += 1
                        self.stats['laser_damage'] += amount
                        self.damage(amount)
                    s['charge'], s['cooldown'] = 0., st['cooldown']
            elif s['kind'] == 'lightning':
                if held and s['cooldown'] <= 1e-9 and self.energy >= st['energy']:
                    self.energy -= st['energy']
                    self.spent_at = self.t
                    s['cooldown'] = st['cooldown']
                    self.stats['arc_shots'] += 1
                    fx, fy = self.foe.pos[0]-muzzle[0], self.foe.pos[1]-muzzle[1]
                    if (math.hypot(fx, fy) <= st['range'] and
                            abs(wrap(math.atan2(fy, fx)-self.aim[0])) <= math.radians(st['cone_deg'])):
                        self.stats['arc_hits'] += 1
                        self.damage(st['damage'])
            elif s['kind'] == 'mortar':
                if held and s['cooldown'] <= 1e-9:
                    s['cooldown'] = st['cooldown']
                    u = self.direction()
                    tube = [self.me.pos[0] + 3*u[0], self.me.pos[1] + 3*u[1], 9.5 + 3*u[2]]
                    self.shells.append(dict(pos=tube, vel=[st['speed']*x for x in u], age=0., new=True))
                    self.stats['mortar_shots'] += 1
        if self.t - self.spent_at >= self.cfg['mech']['energy_regen_delay']:
            self.energy = min(100., self.energy + self.cfg['mech']['energy_regen']*DT)
        # 4. Projectiles.
        kept = []
        speed = self.cfg['weapons']['gun']['speed']
        for b in self.bullets:
            travel = min(DT*speed, b['left'])
            end = [b['pos'][j] + b['u'][j]*travel for j in range(3)]
            before = self.foe.pos if b['new'] else foe_before
            entry = swept_entry(b['pos'], end, before, self.foe.pos, 2.5, 9)
            if entry is not None:
                self.stats['gun_hits'] += 1
                self.damage(self.cfg['weapons']['gun']['damage'])
                continue
            b.update(pos=end, left=b['left']-travel, new=False)
            if b['left'] > 1e-6:
                kept.append(b)
        self.bullets = kept
        mortar = self.cfg['weapons']['mortar']
        kept = []
        for s in self.shells:
            a = s['pos']
            v = s['vel']
            nv = [v[0], v[1], v[2] - mortar['gravity']*DT]
            end = [a[j] + .5*DT*(v[j]+nv[j]) for j in range(3)]
            before = self.foe.pos if s['new'] else foe_before
            entry = swept_entry(a, end, before, self.foe.pos, 2.5, 9)
            blast = None
            direct = False
            if entry is not None:
                blast, direct = [a[j] + (end[j]-a[j])*entry for j in range(3)], True
            elif end[2] <= 0:
                f = a[2]/max(1e-9, a[2]-end[2])
                blast = [a[j] + (end[j]-a[j])*f for j in range(3)]
            s['age'] += DT
            if blast is None and s['age'] < mortar['ttl']:
                s.update(pos=end, vel=nv, new=False)
                kept.append(s)
                continue
            if blast is None:
                continue
            feet = self.foe.pos
            horizontal = max(0., math.hypot(blast[0]-feet[0], blast[1]-feet[1]) - 2.5)
            vertical = max(0., feet[2]-blast[2], blast[2]-feet[2]-9)
            gap = 0. if direct else math.hypot(horizontal, vertical)
            amount = mortar['damage'] if direct else 0.
            if gap <= mortar['splash_radius']:
                amount += mortar['splash']*(1 - (1-mortar['splash_edge'])*gap/mortar['splash_radius'])
            if amount:
                self.stats['mortar_damage'] += amount
                self.damage(amount)
        self.shells = kept

    def run(self):
        tick = 0
        while self.t < self.duration - 1e-9:
            action = self.combat.act(self.observation(tick), self.arena, {})
            self.events = []
            if action.get('aim'):
                self.cmd = list(action['aim'])
            self.tick(action, True)
            self.tick(action, False)
            tick += 2
        out = dict(self.stats)
        out['damage'] = round(out['damage'], 1)
        return out


def cases(split, count, loadouts=LOADOUTS):
    base = {'dev': 1009, 'holdout': 70001, 'fresh': 523007}[split]
    rows = []
    for i in range(count):
        seed = base + 7919*i
        r = random.Random(seed)
        rows.append((seed, loadouts[i % len(loadouts)], STYLES[r.randrange(len(STYLES))], OWN[r.randrange(len(OWN))]))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot-dir', type=Path, required=True)
    p.add_argument('--split', choices=('dev', 'holdout', 'fresh'), default='dev')
    p.add_argument('--cases', type=int, default=120)
    p.add_argument('--json', type=Path)
    p.add_argument('--loadouts', nargs='+', choices=LOADOUTS, default=list(LOADOUTS))
    a = p.parse_args()
    sys.path.insert(0, str(a.bot_dir.resolve()))
    from combat import Combat
    cfg = json.loads((a.bot_dir/'defaults.json').read_text())
    out = []
    for seed, loadout, style, own in cases(a.split, a.cases, tuple(a.loadouts)):
        row = dict(seed=seed, loadout=loadout, style=style, own=own)
        row.update(Duel(Combat, cfg, seed, loadout, style, own).run())
        out.append(row)
    if a.json:
        a.json.write_text(json.dumps(out))
    total = lambda k: sum(r[k] for r in out)
    print(f"cases {len(out)} damage {total('damage'):.0f} kills {sum(r['kill_time'] is not None for r in out)} "
          f"gun {total('gun_hits')}/{total('gun_shots')} laser {total('laser_hits')}/{total('laser_shots')} "
          f"mortar {total('mortar_damage'):.0f}/{total('mortar_shots')} arc {total('arc_hits')}/{total('arc_shots')}")


if __name__ == '__main__':
    main()
