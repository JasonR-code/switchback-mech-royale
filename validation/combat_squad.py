"""Open-field fire-control lab against 2-3 scripted rivals that shoot back.

Measures damage dealt, damage taken (with the 1.5x rear-arc multiplier), kills and
time to first kill while combat.Combat alone controls our torso and triggers.
Rivals strafe like the house bot in the public recording, lead us imperfectly with
guns, and some charge lasers. They do not dodge, take cover or use other weapons.
Our legs follow a fixed script, so movement policy is not part of the comparison.

Usage: python validation/combat_squad.py --bot-dir . --split dev --cases 120 --json out.json
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

from combat_lab import DT, Mover, OpenField, clamp, ray_cylinder, swept_entry, wrap

OWN = ('still', 'strafe', 'walk')


class Rival:
    def __init__(self, rng, ident, pos, cfg, laser):
        self.id = ident
        self.body = Mover(rng, 'house', pos)
        self.hp = 1400.
        self.aim = [rng.uniform(-math.pi, math.pi), 0.]
        self.lead = rng.uniform(.4, 1.)
        self.jitter = rng.uniform(.01, .04)
        gun = cfg['weapons']['gun']
        self.gun = dict(cooldown=rng.uniform(0, .3), ammo=gun['mag'], reload=0.)
        self.laser = dict(cooldown=rng.uniform(0, 1.6), charge=0.) if laser else None
        self.charge_goal = rng.uniform(.75, 1.1)
        self.wake = rng.uniform(.2, 1.2)

    @property
    def alive(self):
        return self.hp > 0


class Squad:
    def __init__(self, Combat, cfg, seed, own, duration=20., pilot=None):
        rng = random.Random(seed)
        self.pilot = pilot
        self.move, self.boost = (0., 0.), False
        self.rng, self.cfg = rng, cfg
        self.spray = random.Random(seed*11 + 5)
        self.combat = Combat(cfg)
        self.arena = OpenField()
        self.duration = duration
        self.me = Mover(rng, own, (0., 0., 0.), top=11.7)
        self.aim = [rng.uniform(-math.pi, math.pi), 0.]
        self.cmd = list(self.aim)
        self.hp_taken = 0.
        self.rear_taken = 0.
        n = rng.choice((2, 2, 3))
        self.rivals = []
        base = rng.uniform(-math.pi, math.pi)
        for i in range(n):
            angle = base + rng.uniform(-.4, .4) + i*rng.uniform(1.2, 2.6)
            d = rng.uniform(35, 150)
            self.rivals.append(Rival(rng, 3+i, (d*math.cos(angle), d*math.sin(angle), 0.), cfg, rng.random() < .45))
        self.band = {r.id: (max(15., math.hypot(*r.body.pos[:2])*.6), math.hypot(*r.body.pos[:2])*1.3 + 10)
                     for r in self.rivals}
        w = cfg['weapons']
        second = rng.choice((None, 'laser', 'mortar', 'lightning'))
        self.slots = [dict(kind='gun', cooldown=0., ammo=w['gun']['mag'], reload=0., charge=0., stats=dict(w['gun'])),
                      dict(kind=second, cooldown=0., ammo=0, reload=0., charge=0., stats=dict(w[second])) if second else None]
        self.loadout = 'gun' + ('+'+second if second else '')
        self.energy, self.spent_at = 100., -9.
        self.bullets, self.shells = [], []
        self.t = 0.
        self.events = []
        self.stats = dict(dealt=0., taken=0., rear=0., kills=0, first_kill=None, gun_shots=0, gun_hits=0,
                          laser_shots=0, laser_hits=0, rivals=n, loadout=self.loadout)

    # -- observations -------------------------------------------------------
    def observation(self, tick):
        weapons = [None if s is None else {k: (round(v, 3) if isinstance(v, float) else v) for k, v in s.items()}
                   for s in self.slots]
        mechs = []
        for r in self.rivals:
            if not r.alive:
                continue
            mechs.append(dict(id=r.id, kind='mech', pos=list(r.body.pos), vel=list(r.body.vel), aim=list(r.aim),
                              hp=round(r.hp, 2), max_hp=1400, cubes=0,
                              weapons=['gun'] + (['laser'] if r.laser else []),
                              charging=bool(r.laser and r.laser['charge'] > 0)))
        return {'type': 'obs', 'tick': tick, 't': round(self.t, 3), 'alive': 1 + len(mechs),
                'self': dict(id=0, pos=list(self.me.pos), vel=list(self.me.vel), aim=list(self.aim),
                             hp=max(1., 1400-self.hp_taken), max_hp=1400, energy=self.energy, max_energy=100,
                             grounded=True, cubes=0, upgrades=[], in_zone=True, weapons=weapons,
                             stats=dict(self.cfg['mech'])),
                'mechs': mechs, 'crates': [], 'projectiles': [], 'pickups': [], 'cubes': [], 'sounds': [],
                'beams': [], 'events': self.events, 'drops': [], 'zone': {}, 'offer': None}

    # -- damage -------------------------------------------------------------
    def hurt_rival(self, r, amount, weapon):
        if not r.alive:
            return
        bearing = math.atan2(self.me.pos[1]-r.body.pos[1], self.me.pos[0]-r.body.pos[0])
        rear = abs(wrap(bearing - r.aim[0])) > math.pi/2
        amount *= 1.5 if rear else 1.
        self.stats['dealt'] += min(amount, r.hp)
        r.hp -= amount
        self.events.append(dict(type='hit', target=r.id, amount=amount, weapon=weapon, rear=rear))
        if r.hp <= 0:
            self.stats['kills'] += 1
            self.events.append(dict(type='kill', target=r.id))
            if self.stats['first_kill'] is None:
                self.stats['first_kill'] = round(self.t, 2)

    def hurt_me(self, r, amount, weapon, source):
        bearing = math.atan2(source[1]-self.me.pos[1], source[0]-self.me.pos[0])
        rear = abs(wrap(bearing - self.aim[0])) > math.pi/2
        amount *= 1.5 if rear else 1.
        self.hp_taken += amount
        self.stats['taken'] += amount
        if rear:
            self.stats['rear'] += amount
        self.events.append(dict(type='damaged', amount=amount, weapon=weapon, bearing=bearing, by=r.id, rear=rear))

    def direction(self, aim, spread=0.):
        yaw, pitch = aim
        if spread:
            yaw += math.radians(self.spray.gauss(0, spread))
            pitch += math.radians(self.spray.gauss(0, spread))
        return [math.cos(yaw)*math.cos(pitch), math.sin(yaw)*math.cos(pitch), math.sin(pitch)]

    # -- rivals ---------------------------------------------------------------
    def rival_tick(self, r):
        gun = self.cfg['weapons']['gun']
        laser = self.cfg['weapons']['laser']
        p, v = self.me.pos, self.me.vel
        x, y, _ = r.body.pos
        d = max(1., math.hypot(p[0]-x, p[1]-y))
        lead = d/gun['speed']*r.lead
        tx, ty = p[0] + v[0]*lead - x, p[1] + v[1]*lead - y
        if r.laser and r.laser['charge'] > 0:
            tx, ty = p[0] - x, p[1] - y
        want = math.atan2(ty, tx) + self.rng.gauss(0, r.jitter)
        r.aim[0] = wrap(r.aim[0] + clamp(wrap(want-r.aim[0]), -4*DT, 4*DT))
        r.aim[1] = math.atan2(4.5-7, d)
        if self.t < r.wake:
            return
        error = abs(wrap(want - r.aim[0]))
        muzzle = (x, y, 7.)
        g = r.gun
        g['cooldown'] = max(0., g['cooldown']-DT)
        if g['reload'] > 0:
            g['reload'] = max(0., g['reload']-DT)
            if g['reload'] <= 1e-9:
                g['ammo'] = gun['mag']
        elif error < .03 and g['cooldown'] <= 1e-9 and d < 230 and not (r.laser and r.laser['charge'] > 0):
            g['ammo'] -= 1
            g['cooldown'] = gun['cooldown']
            if g['ammo'] <= 0:
                g['reload'] = gun['reload']
            u = self.direction(r.aim, gun['spread_deg'])
            self.bullets.append(dict(owner=r, pos=[muzzle[i] + 3*u[i] for i in range(3)], u=u,
                                     left=gun['range'], new=True))
        if r.laser:
            L = r.laser
            L['cooldown'] = max(0., L['cooldown']-DT)
            if L['cooldown'] <= 1e-9 and d < laser['range']:
                L['charge'] += DT
                if L['charge'] >= r.charge_goal and error < math.atan2(2.5, d) or L['charge'] >= laser['charge'] + laser['hold_s']:
                    frac = min(1., L['charge']/laser['charge'])
                    amount = laser['damage']*(laser['min_frac'] + (1-laser['min_frac'])*frac)
                    if ray_cylinder(muzzle, self.direction(r.aim), laser['range'], self.me.pos, 2.5, 9) is not None:
                        self.hurt_me(r, amount, 'laser', muzzle)
                    L['charge'], L['cooldown'] = 0., laser['cooldown']

    # -- simulation -------------------------------------------------------------
    def tick(self, action, first):
        mech = self.cfg['mech']
        yaw, pitch = self.cmd
        self.aim[0] = wrap(self.aim[0] + clamp(wrap(yaw-self.aim[0]), -mech['turn_rate']*DT, mech['turn_rate']*DT))
        self.aim[1] += clamp(clamp(pitch, mech['min_pitch'], mech['max_pitch'])-self.aim[1],
                             -mech['pitch_rate']*DT, mech['pitch_rate']*DT)
        charging = any(s and s['kind'] == 'laser' and s['charge'] > 0 for s in self.slots)
        me_before = list(self.me.pos)
        before = {r.id: list(r.body.pos) for r in self.rivals}
        alive = [r for r in self.rivals if r.alive]
        anchor = alive[0].body.pos if alive else (1., 0., 0.)
        if self.pilot:
            self.walk(charging)
        else:
            self.me.step(self.t, anchor, (0, 1e9), cap=11.7*(.5 if charging else 1.))
        for r in alive:
            r.body.step(self.t, self.me.pos, self.band[r.id], cap=19.5*(.5 if r.laser and r.laser['charge'] > 0 else 1.))
        self.t += DT
        for r in alive:
            self.rival_tick(r)
        muzzle = [self.me.pos[0], self.me.pos[1], 7.]
        fire = action.get('fire') or [False, False]
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
                    u = self.direction(self.aim, st['spread_deg'])
                    self.bullets.append(dict(owner=None, pos=[muzzle[j] + 3*u[j] for j in range(3)], u=u,
                                             left=st['range'], new=True))
                    self.stats['gun_shots'] += 1
            elif s['kind'] == 'laser':
                if s['cooldown'] > 1e-9:
                    continue
                full = st['charge']
                release = False
                if held or 0 < s['charge'] < st['min_charge']:
                    s['charge'] = min(full + st['hold_s'], s['charge'] + DT)
                    release = s['charge'] >= full + st['hold_s'] - 1e-9 or (not held and s['charge'] >= st['min_charge'])
                elif s['charge'] > 0:
                    release = True
                if release:
                    amount = st['damage']*(st['min_frac'] + (1-st['min_frac'])*min(1., s['charge']/full))
                    self.stats['laser_shots'] += 1
                    u = self.direction(self.aim)
                    best = None
                    for r in self.rivals:
                        if r.alive:
                            h = ray_cylinder(muzzle, u, st['range'], r.body.pos, 2.5, 9)
                            if h is not None and (best is None or h < best[0]):
                                best = (h, r)
                    if best:
                        self.stats['laser_hits'] += 1
                        self.hurt_rival(best[1], amount, 'laser')
                    s['charge'], s['cooldown'] = 0., st['cooldown']
            elif s['kind'] == 'lightning':
                if held and s['cooldown'] <= 1e-9 and self.energy >= st['energy']:
                    self.energy -= st['energy']
                    self.spent_at = self.t
                    s['cooldown'] = st['cooldown']
                    near = None
                    for r in self.rivals:
                        if not r.alive:
                            continue
                        fx, fy = r.body.pos[0]-muzzle[0], r.body.pos[1]-muzzle[1]
                        dd = math.hypot(fx, fy)
                        if dd <= st['range'] and abs(wrap(math.atan2(fy, fx)-self.aim[0])) <= math.radians(st['cone_deg']):
                            if near is None or dd < near[0]:
                                near = (dd, r)
                    if near:
                        self.hurt_rival(near[1], st['damage'], 'lightning')
            elif s['kind'] == 'mortar':
                if held and s['cooldown'] <= 1e-9:
                    s['cooldown'] = st['cooldown']
                    u = self.direction(self.aim)
                    tube = [self.me.pos[0] + 3*u[0], self.me.pos[1] + 3*u[1], 9.5 + 3*u[2]]
                    self.shells.append(dict(pos=tube, vel=[st['speed']*x for x in u], age=0., new=True))
        if self.t - self.spent_at >= self.cfg['mech']['energy_regen_delay']:
            self.energy = min(100., self.energy + self.cfg['mech']['energy_regen']*DT)
        speed = self.cfg['weapons']['gun']['speed']
        kept = []
        for b in self.bullets:
            travel = min(DT*speed, b['left'])
            end = [b['pos'][j] + b['u'][j]*travel for j in range(3)]
            hit = False
            if b['owner'] is None:
                for r in self.rivals:
                    if r.alive:
                        start = r.body.pos if b['new'] else before[r.id]
                        if swept_entry(b['pos'], end, start, r.body.pos, 2.5, 9) is not None:
                            self.stats['gun_hits'] += 1
                            self.hurt_rival(r, self.cfg['weapons']['gun']['damage'], 'gun')
                            hit = True
                            break
            else:
                start = self.me.pos if b['new'] else me_before
                if swept_entry(b['pos'], end, start, self.me.pos, 2.5, 9) is not None:
                    self.hurt_me(b['owner'], self.cfg['weapons']['gun']['damage'], 'gun',
                                 [self.me.pos[0]-b['u'][0]*50, self.me.pos[1]-b['u'][1]*50])
                    hit = True
            if hit:
                continue
            b.update(pos=end, left=b['left']-travel, new=False)
            if b['left'] > 1e-6:
                kept.append(b)
        self.bullets = kept
        mortar = self.cfg['weapons']['mortar']
        kept = []
        for s in self.shells:
            a, v = s['pos'], s['vel']
            nv = [v[0], v[1], v[2] - mortar['gravity']*DT]
            end = [a[j] + .5*DT*(v[j]+nv[j]) for j in range(3)]
            blast = None
            for r in self.rivals:
                if r.alive:
                    start = r.body.pos if s['new'] else before[r.id]
                    e = swept_entry(a, end, start, r.body.pos, 2.5, 9)
                    if e is not None:
                        blast = [a[j] + (end[j]-a[j])*e for j in range(3)]
                        break
            if blast is None and end[2] <= 0:
                f = a[2]/max(1e-9, a[2]-end[2])
                blast = [a[j] + (end[j]-a[j])*f for j in range(3)]
            s['age'] += DT
            if blast is None:
                if s['age'] < mortar['ttl']:
                    s.update(pos=end, vel=nv, new=False)
                    kept.append(s)
                continue
            for r in self.rivals:
                if not r.alive:
                    continue
                feet = r.body.pos
                gap = math.hypot(max(0., math.hypot(blast[0]-feet[0], blast[1]-feet[1]) - 2.5),
                                 max(0., feet[2]-blast[2], blast[2]-feet[2]-9))
                amount = mortar['damage'] if gap < 1e-6 else 0.
                if gap <= mortar['splash_radius']:
                    amount += mortar['splash']*(1 - (1-mortar['splash_edge'])*gap/mortar['splash_radius'])
                if amount:
                    self.hurt_rival(r, amount, 'mortar')
        self.shells = kept

    def walk(self, charging):
        mech = self.cfg['mech']
        mx, my = self.move
        m = math.hypot(mx, my)
        if m > 1:
            mx, my = mx/m, my/m
        boost = self.boost and m > .05 and self.energy > 0
        speed = mech['boost_speed'] if boost else mech['walk_speed']
        if boost:
            self.energy = max(0., self.energy - mech['boost_drain']*DT)
            self.spent_at = self.t
        speed *= mech['charge_move_mult'] if charging else 1.
        tx, ty = mx*speed, my*speed
        ox, oy = self.me.vel[:2]
        gap = math.hypot(tx-ox, ty-oy)
        f = min(1., mech['ground_accel']*DT/gap) if gap > 1e-9 else 1.
        vx, vy = ox + f*(tx-ox), oy + f*(ty-oy)
        self.me.pos = [self.me.pos[0] + .5*DT*(ox+vx), self.me.pos[1] + .5*DT*(oy+vy), 0.]
        self.me.vel = [vx, vy, 0.]

    def run(self):
        tick = 0
        while (self.t < self.duration - 1e-9 and any(r.alive for r in self.rivals)
               and not (self.pilot and self.hp_taken >= 1400)):
            obs = self.observation(tick)
            if self.pilot:
                action = self.pilot.act(obs)
                move = action.get('move') or (0., 0.)
                self.move, self.boost = (float(move[0]), float(move[1])), bool(action.get('boost'))
            else:
                action = self.combat.act(obs, self.arena, {})
            self.events = []
            if action.get('aim'):
                self.cmd = list(action['aim'])
            self.tick(action, True)
            self.tick(action, False)
            tick += 2
        out = dict(self.stats)
        out['cleared'] = round(self.t, 2) if not any(r.alive for r in self.rivals) else None
        out['death'] = round(self.t, 2) if self.hp_taken >= 1400 else None
        for k in ('dealt', 'taken', 'rear'):
            out[k] = round(out[k], 1)
        return out


def cases(split, count):
    base = {'dev': 3301, 'holdout': 91003, 'fresh': 610009}[split]
    return [(base + 6271*i, OWN[i % 3]) for i in range(count)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot-dir', type=Path, required=True)
    p.add_argument('--split', choices=('dev', 'holdout', 'fresh'), default='dev')
    p.add_argument('--cases', type=int, default=120)
    p.add_argument('--json', type=Path)
    p.add_argument('--pilot', action='store_true', help='drive our mech with the full main.Pilot (no map)')
    a = p.parse_args()
    sys.path.insert(0, str(a.bot_dir.resolve()))
    from combat import Combat
    cfg = json.loads((a.bot_dir/'defaults.json').read_text())
    out = []
    for seed, own in cases(a.split, a.cases):
        row = dict(seed=seed, own=own)
        pilot = None
        if a.pilot:
            from main import Pilot
            pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir=str(a.bot_dir/'no-map'))))
            row['own'] = 'pilot'
        row.update(Squad(Combat, cfg, seed, own, pilot=pilot).run())
        out.append(row)
    if a.json:
        a.json.write_text(json.dumps(out))
    s = lambda k: sum(r[k] for r in out)
    print(f"cases {len(out)} dealt {s('dealt'):.0f} taken {s('taken'):.0f} rear {s('rear'):.0f} kills {s('kills')} "
          f"gun {s('gun_hits')}/{s('gun_shots')} laser {s('laser_hits')}/{s('laser_shots')}")


if __name__ == '__main__':
    main()
