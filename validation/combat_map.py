"""Snowball lab on the real v2 map: buildings block sight, shots and movement.

Everything in combat_snowball.py (tiered rivals, escalation, withdraw-and-regenerate,
cubes, protocol vision) plus pyarena.PyArena on the official map:
- the bot plans with the same arena calls as in a match (cover, clear, waypoint, can_move);
- vision needs line of sight; rivals fire only with line of sight to our torso;
- bullets stop at walls; laser and lightning need line of sight; mortar shells arc freely;
- rivals and we cannot walk through buildings (blocked moves slide along an axis);
- hunters without sight of us follow a shortest-path field to us (shared squad knowledge).
NOT modelled: terrain relief (flattened), trees/canopy, cars, fences, water, roofs and
bridges as floors, jets, zone, loot, upgrades, drones, sound-driven house-bot behaviour.
Usage: python validation/combat_map.py --bot-dir . --split dev --cases 60 --rival-damage .5 --json out.json
"""
import argparse
import heapq
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from combat_lab import DT  # noqa: E402
from combat_snowball import Snowball, cases  # noqa: E402
from pyarena import PyArena, DIRS  # noqa: E402

_ARENA = {}


def shared_arena(cfg):
    if 'a' not in _ARENA:
        _ARENA['a'] = PyArena(HERE.parent / 'mechfight-kit' / 'arena', cfg, flat=True)
    return _ARENA['a']


class MapSnowball(Snowball):
    def __init__(self, Combat, cfg, seed, pilot, **kw):
        super().__init__(Combat, cfg, seed, pilot, fov=True, **kw)
        A = shared_arena(cfg)
        rng = random.Random(seed*29 + 7)
        l, b, r, t = A.bounds
        while True:
            c = (rng.uniform(l+150, r-150), rng.uniform(b+120, t-120))
            if A.fits(c[0], c[1], 3.2) and A.cover(c[0], c[1], 0) < .9:
                break
        A.window = (c[0]-330, c[1]-330, c[0]+330, c[1]+330)
        A._free.clear()
        A._cover.clear()
        A._routes.clear()
        self.arena = A
        pilot.arena = A
        self.me.pos = [c[0], c[1], 0.]
        for q in self.rivals:
            x, y = c[0]+q.body.pos[0], c[1]+q.body.pos[1]
            n = A._node(x, y)
            if not A._node_free(n):
                ring = [(n[0]+i, n[1]+j) for i in range(-8, 9) for j in range(-8, 9) if A._node_free((n[0]+i, n[1]+j))]
                n = min(ring, key=lambda m: abs(m[0]-n[0])+abs(m[1]-n[1])) if ring else A._node(*c)
                x, y = A._center(n)
            q.body.pos = [x, y, 0.]
            orig = q.body.step
            q.body.step = (lambda t, other, band, cap=None, _r=q, _o=orig: self.rival_step(_r, _o, t, other, band, cap))
        self.los = lambda me, p: (A.clear((me[0], me[1], 8.), (p[0], p[1], 8.)) or
                                  A.clear((me[0], me[1], 8.), (p[0], p[1], 4.5)))
        self.field, self.field_t = {}, -9.
        self.stats.update(crossfire_s=0., exposed_s=0., escape_s=0., escape_cover_s=0., escape_taken=0.,
                          cover_s=0., blocked_moves=0)
        self.last_intent = {}
        orig_plan = pilot.strategy.plan

        def plan(obs, arena, _o=orig_plan):
            out = _o(obs, arena)
            self.last_intent = out
            return out
        pilot.strategy.plan = plan

    # -- movement ---------------------------------------------------------------
    def blocked(self, before, body):
        A = self.arena
        if A.can_move(before, body.pos):
            return
        self.stats['blocked_moves'] += body is self.me
        for cand in ([body.pos[0], before[1], 0.], [before[0], body.pos[1], 0.]):
            if A.can_move(before, cand):
                if cand[0] == before[0]:
                    body.vel[0] = 0.
                else:
                    body.vel[1] = 0.
                body.pos = cand
                return
        body.pos, body.vel = list(before), [0., 0., 0.]

    def walk(self, charging):
        before = list(self.me.pos)
        super().walk(charging)
        self.blocked(before, self.me)

    def flow(self):
        if self.t - self.field_t < 1. and self.field:
            return self.field
        A = self.arena
        src = A._node(*self.me.pos[:2])
        dist = {src: 0.}
        heap = [(0., src)]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist[n] or d > 420:
                continue
            for dx, dy in DIRS:
                m = (n[0]+dx, n[1]+dy)
                if not A._node_free(m):
                    continue
                nd = d + math.hypot(dx, dy)*4.
                if nd < dist.get(m, 1e30):
                    dist[m] = nd
                    heapq.heappush(heap, (nd, m))
        self.field, self.field_t = dist, self.t
        return dist

    def rival_step(self, r, orig, t, other, band, cap):
        A = self.arena
        before = list(r.body.pos)
        me = self.me.pos
        d = math.dist(before[:2], me[:2])
        sees = A.clear((before[0], before[1], 8.), (me[0], me[1], 5.))
        if r.role == 'hunter' and (not sees or d > band[1]):
            field = self.flow()
            n = A._node(*before[:2])
            best = min(((field.get((n[0]+dx, n[1]+dy), 1e30), (n[0]+dx, n[1]+dy)) for dx, dy in DIRS),
                       default=(1e30, n))
            if best[0] < 1e29:
                tx, ty = A._center(best[1])
                ux, uy = tx-before[0], ty-before[1]
                m = max(1e-6, math.hypot(ux, uy))
                top = min(12., cap or 12.)
                r.body.vel = [ux/m*top, uy/m*top, 0.]
                r.body.pos = [before[0]+ux/m*top*DT, before[1]+uy/m*top*DT, 0.]
                self.blocked(before, r.body)
                return
        orig(t, other, band, cap)
        self.blocked(before, r.body)

    # -- sight-limited fire --------------------------------------------------------
    def rival_tick(self, r):
        me = self.me.pos
        x, y, _ = r.body.pos
        if r.role in ('idle', 'withdrawn') or not self.arena.clear((x, y, 7.), (me[0], me[1], 5.)):
            wake, r.wake = r.wake, 1e9
            super().rival_tick(r)
            r.wake = wake
            return
        super().rival_tick(r)

    def hurt_rival(self, r, amount, weapon):
        me = self.me.pos
        if weapon in ('laser', 'lightning') and not self.arena.clear((me[0], me[1], 7.), (r.body.pos[0], r.body.pos[1], 4.5)):
            return
        super().hurt_rival(r, amount, weapon)

    def hurt_me(self, r, amount, weapon, source):
        super().hurt_me(r, amount, weapon, source)
        if self.last_intent.get('escape'):
            self.stats['escape_taken'] += self.events[-1]['amount']

    def tick(self, action, first):
        A = self.arena
        speed = self.cfg['weapons']['gun']['speed']
        kept = []
        for b_ in self.bullets:
            travel = min(DT*speed, b_['left'])
            end = [b_['pos'][j] + b_['u'][j]*travel for j in range(3)]
            if A.clear(b_['pos'], end):
                kept.append(b_)
        self.bullets = kept
        super().tick(action, first)
        me = self.me.pos
        shooters = sum(1 for q in self.rivals if q.alive and q.role == 'hunter' and math.dist(q.body.pos[:2], me[:2]) < 230
                       and A.clear((q.body.pos[0], q.body.pos[1], 7.), (me[0], me[1], 5.)))
        self.stats['exposed_s'] += DT*(shooters >= 1)
        self.stats['crossfire_s'] += DT*(shooters >= 2)
        self.stats['cover_s'] += DT*(A.cover(me[0], me[1], 0.) >= .4)
        if self.last_intent.get('escape'):
            self.stats['escape_s'] += DT
            self.stats['escape_cover_s'] += DT*(shooters == 0)

    def run(self):
        out = super().run()
        out['laser_fired'], out['laser_hit'] = self.stats['laser_fired'], self.stats['laser_hit']
        for k in ('crossfire_s', 'exposed_s', 'escape_s', 'escape_cover_s', 'escape_taken', 'cover_s'):
            out[k] = round(self.stats[k], 2)
        out['blocked_moves'] = self.stats['blocked_moves']
        return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot-dir', type=Path, required=True)
    p.add_argument('--split', choices=('dev', 'holdout', 'fresh'), default='dev')
    p.add_argument('--cases', type=int, default=60)
    p.add_argument('--json', type=Path)
    p.add_argument('--rival-damage', type=float, default=1.)
    p.add_argument('--no-provoke', action='store_true')
    p.add_argument('--house-laser', action='store_true')
    a = p.parse_args()
    sys.path.insert(0, str(a.bot_dir.resolve()))
    from combat import Combat
    from main import Pilot
    cfg = json.loads((a.bot_dir/'defaults.json').read_text())
    out = []
    for seed in cases(a.split, a.cases):
        pilot = Pilot(dict(type='hello', slot=0, seed=seed, config=cfg, map=dict(dir=str(a.bot_dir/'no-map'))))
        row = dict(seed=seed)
        row.update(MapSnowball(Combat, cfg, seed, pilot, scale=a.rival_damage, provoke=not a.no_provoke,
                               house_laser=a.house_laser).run())
        out.append(row)
    if a.json:
        a.json.write_text(json.dumps(out))
    s = lambda k: sum(r[k] for r in out)
    print(f"cases {len(out)} kills {s('kills')} deaths {sum(r['death'] is not None for r in out)} "
          f"crossfire_s {s('crossfire_s'):.0f} escape_s {s('escape_s'):.0f} blocked {s('blocked_moves')}")


if __name__ == '__main__':
    main()
