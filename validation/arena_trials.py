"""Closed-loop campus probes. Requires the supplied kit and Python's standard library.

Usage: python arena_trials.py --kit /path/to/mechfight-kit --bot-dir /path/to/bot
There are no house bots or scores. The oracle imports no geometry from the pilot.
"""
import argparse
import array
import collections
import gzip
import importlib.util
import json
import math
import random
import statistics
import sys
from pathlib import Path

DT = 0.05


def clamp(x, low, high):
    return max(low, min(high, x))


def delta(a, b):
    return (a - b + math.pi) % math.tau - math.pi


def circle_edge(x, y, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = clamp(((x - a[0])*dx + (y - a[1])*dy) / (dx*dx + dy*dy or 1), 0, 1)
    return (a[0]+t*dx-x)**2 + (a[1]+t*dy-y)**2


class Footprint:
    def __init__(self, data):
        self.base, self.top = data["base"], data["top"]
        self.rings = []
        for flat in [data["ring"], *data["holes"]]:
            pairs = list(zip(flat[::2], flat[1::2]))
            if pairs:
                self.rings.append(list(zip(pairs, pairs[1:] + pairs[:1])))
        self.bounds = (min(data["ring"][::2]), min(data["ring"][1::2]),
                       max(data["ring"][::2]), max(data["ring"][1::2]))

    def intersects(self, x, y, radius):
        """True if a horizontal disk touches the polygon (holes excluded)."""
        xmin, ymin, xmax, ymax = self.bounds
        if x < xmin-radius or x > xmax+radius or y < ymin-radius or y > ymax+radius:
            return False
        in_solid = False
        for ring in self.rings:
            for a, b in ring:
                if radius and circle_edge(x, y, a, b) <= radius*radius:
                    return True
                if (a[1] > y) != (b[1] > y) and x < a[0]+(b[0]-a[0])*(y-a[1])/(b[1]-a[1]):
                    in_solid = not in_solid
        return in_solid


class Campus:
    def __init__(self, kit):
        path = kit / 'arena/v2'
        world = json.loads((path / 'world.json').read_text())
        self.grid = world['terrain']
        self.heights = array.array('h')
        self.heights.frombytes((path / self.grid['file']).read_bytes())
        if sys.byteorder != 'little':
            self.heights.byteswap()
        b = world['bounds']
        self.bounds = b['minX'], b['minY'], b['maxX'], b['maxY']
        self.cells = collections.defaultdict(list)
        for data in world['prisms']:
            p = Footprint(data)
            x0, y0, x1, y1 = p.bounds
            for j in range(math.floor((y0-5)/24), math.floor((y1+5)/24)+1):
                for i in range(math.floor((x0-5)/24), math.floor((x1+5)/24)+1):
                    self.cells[i, j].append(p)

    def ground(self, x, y):
        g = self.grid
        u = clamp((x-g['minX'])/g['step'], 0, g['nx']-1.00001)
        v = clamp((y-g['minY'])/g['step'], 0, g['ny']-1.00001)
        i, j = int(u), int(v)
        ix, a, b = j*g['nx']+i, u-i, v-j
        h = self.heights
        return g['scale'] * ((1-b)*((1-a)*h[ix]+a*h[ix+1])
                             + b*((1-a)*h[ix+g['nx']]+a*h[ix+g['nx']+1]))

    def bodies(self, x, y):
        return self.cells.get((math.floor(x/24), math.floor(y/24)), ())

    def probe(self, x, y, z, height=9, radius=2.5, step=1.2):
        """Return supporting surface and headroom, or None for lateral collision."""
        x0, y0, x1, y1 = self.bounds
        if not (x0+radius < x < x1-radius and y0+radius < y < y1-radius):
            return None
        floor, ceiling = self.ground(x, y), math.inf
        for p in self.bodies(x, y):
            if not p.intersects(x, y, radius):
                continue
            if p.top <= z+step:
                # Use footprint overlap to approximate edges (no server eave ejection).
                floor = max(floor, p.top)
            elif p.base >= z+height-1e-6:
                ceiling = min(ceiling, p.base)
            else:
                return None
        return (floor, ceiling) if floor+height <= ceiling else None

    def open_ground(self, x, y, margin=2):
        floor = self.ground(x, y)
        result = self.probe(x, y, floor, radius=2.5+margin)
        return result is not None and abs(result[0]-floor) < .1

    def visible(self, a, b):
        span = max(1, math.ceil(math.dist(a, b)/2.0))
        for k in range(1, span):
            x, y, z = (s+(e-s)*k/span for s, e in zip(a, b))
            if self.ground(x, y) > z:
                return False
            if any(p.base <= z <= p.top and p.intersects(x, y, 0) for p in self.bodies(x, y)):
                return False
        return True


def make_scenario(world, family, seed, obstructed):
    rng = random.Random(seed)
    x0, y0, x1, y1 = world.bounds
    for _ in range(10000):
        start = rng.uniform(x0+45, x1-45), rng.uniform(y0+45, y1-45)
        if not world.open_ground(*start):
            continue
        angle = rng.uniform(-math.pi, math.pi)
        distance = rng.uniform(*{'zone': (138, 172), 'loot': (18, 33), 'drop': (37, 65)}[family])
        direction = math.cos(angle), math.sin(angle)
        goal = tuple(x+d*distance for x, d in zip(start, direction))
        if not world.open_ground(*goal):
            continue
        test_distance = distance - 70 if family == 'zone' else distance
        clear = all(world.open_ground(*(x+d*t for x, d in zip(start, direction)), margin=0)
                    for t in range(0, int(test_distance), 3))
        if obstructed == clear:
            continue
        start3 = (*start, world.ground(*start))
        goal3 = (*goal, world.ground(*goal))
        if family == 'loot' and not world.visible((*start, start3[2]+8), (*goal, goal3[2]+1)):
            continue
        # The entire next disk fits within the preceding disk.
        initial_center = tuple(x+d*60 for x, d in zip(goal, (-direction[0], -direction[1])))
        return start3, goal3, initial_center, angle
    raise ValueError(f"Could not draw {family}/{seed}/{obstructed}")


class Trial:
    def __init__(self, world, kit, pilot_factory, family, seed, obstructed):
        self.world, self.family = world, family
        start, self.goal, self.initial_center, self.angle = make_scenario(world, family, seed, obstructed)
        with gzip.open(kit / 'check/stream.jsonl.gz', 'rt') as lines:
            hello, self.obs = json.loads(next(lines)), json.loads(next(lines))
        hello['map']['dir'] = str((kit / 'arena').resolve())
        # A slot-specific random number independent of trial generation.
        hello['seed'] = random.Random(1799 + seed*7).getrandbits(32)
        self.cfg = hello['config']
        rng = random.Random(seed+7816001)
        theta = rng.uniform(-math.pi, math.pi)
        self.loot_circle = (start[0]+73*math.cos(theta), start[1]+73*math.sin(theta))
        self.pilot = pilot_factory(hello)
        self.me = self.obs['self']
        self.me.update(pos=list(start), vel=[0, 0, 0], aim=[self.angle, 0], hp=650 if family == 'drop' else self.me['max_hp'])
        self.time = 0.
        self.last_spent = -10.
        self.time_out = 0.
        self.crossed = None
        self.zone_damage = 0.
        self.last_damage = -10.
        self.approach = math.dist(start[:2], self.goal[:2])
        self.min_dist = self.approach
        self.captured = False
        self.collected = False
        self.progress = 0.
        self.events = []
        self.durations = {'zone': 40, 'loot': 16, 'drop': 22}
        self.start_time = {'zone': 289., 'loot': 9., 'drop': 97.}[family]
        self.stats = self.me['stats']

    def zone(self):
        if self.family == 'zone':
            ratio = clamp((self.time-6)/30, 0, 1)
            return dict(center=[(1-ratio)*a+ratio*b for a, b in zip(self.initial_center, self.goal[:2])],
                        radius=140-70*ratio, next_center=self.goal[:2], next_radius=70,
                        shrink_start=self.start_time+6, shrink_end=self.start_time+36, dps=100)
        return dict(center=self.loot_circle, radius=380, next_center=self.loot_circle, next_radius=240,
                    shrink_start=self.start_time+55, shrink_end=self.start_time+95, dps=35)

    def observation(self):
        obs = self.obs
        obs['zone'] = self.zone()
        obs['t'] = self.start_time+self.time
        obs['tick'] = round(20*obs['t'])
        obs['alive'] = 9 if self.family == 'zone' else 16
        me = self.me
        me['in_zone'] = math.dist(me['pos'][:2], obs['zone']['center']) <= obs['zone']['radius']
        obs['events'], self.events = self.events, []
        if self.family == 'loot':
            g = self.goal
            d = math.dist(g, me['pos'])
            in_cone = abs(delta(math.atan2(g[1]-me['pos'][1], g[0]-me['pos'][0]), me['aim'][0])) <= math.pi/3
            seen = (d < 45 or (d < 200 and in_cone)) and self.world.visible(
                (*me['pos'][:2], me['pos'][2]+8), (*g[:2], g[2]+1))
            obs['pickups'] = ([dict(id=8012, pos=list(g), kind='lightning')]
                              if seen and not self.collected else [])
        if self.family == 'drop':
            obs['drops'] = ([] if self.captured else
                            [dict(id=20003, pos=list(self.goal), radius=8, lands_in=0,
                                  capture_s=4, progress=self.progress,
                                  holder=me['id'] if self.progress else None)])
        return obs

    def step(self, action):
        m, s, world = self.me, self.stats, self.world
        x, y, z = m['pos']
        vx, vy, vz = m['vel']
        mx, my = action.get('move', (0, 0))
        n = max(1, math.hypot(mx, my))
        mx, my = mx/n, my/n
        on_ground = m['grounded']
        if action.get('jump') and on_ground:
            on_ground, vz = False, s['jump_speed']
        boost = action.get('boost') and m['energy'] > 0 and (mx or my or not on_ground)
        if boost:
            m['energy'] = max(0, m['energy']-DT*(s['boost_drain'] if on_ground else s['jet_drain']))
            self.last_spent = self.time
        elif self.time-self.last_spent >= s['energy_regen_delay']:
            m['energy'] = min(m['max_energy'], m['energy'] + DT*s['energy_regen'])
        speed = s['boost_speed'] if boost and on_ground else s['walk_speed']
        dx, dy = mx*speed-vx, my*speed-vy
        limit = DT*(s['ground_accel'] if on_ground else s['air_accel'])
        gain = min(1., limit/(math.hypot(dx, dy) or 1))
        vx, vy = vx+dx*gain, vy+dy*gain
        if not on_ground:
            vz += DT*((s['jet_accel'] if boost else 0)-s['gravity'])
            if boost:
                vz = min(vz, s['max_rise_speed'])
        test_z = z + DT*vz
        old_surface = world.probe(x, y, z)
        if old_surface:
            test_z = max(old_surface[0], min(test_z, old_surface[1]-s['height']))
        def accepts(nx, ny):
            candidate = world.probe(nx, ny, test_z)
            if candidate is None:
                return None
            floor, ceiling = candidate
            rise = floor - test_z
            travel = math.hypot(nx-x, ny-y)
            if rise > s['step_up'] or (on_ground and world.ground(nx,ny)-world.ground(x,y) >
                                       travel*math.tan(math.radians(s['max_slope_deg']))+.01):
                return None
            return floor, ceiling
        dests = [(x+vx*DT, y+vy*DT, vx, vy)]
        # Axis sliding is a conservative proxy for the server's polygon-normal slide.
        dests.extend(sorted([(x+vx*DT, y, vx, 0), (x, y+vy*DT, 0, vy)],
                            key=lambda q: abs(q[2])+abs(q[3]), reverse=True))
        dests.append((x, y, 0, 0))
        for nx, ny, nvx, nvy in dests:
            hit = accepts(nx, ny)
            if hit is not None:
                floor, ceiling = hit
                x, y, vx, vy = nx, ny, nvx, nvy
                test_z = min(test_z, ceiling-s['height'])
                if test_z <= floor+.05 or (on_ground and test_z-floor < s['step_up']):
                    test_z, vz, on_ground = floor, 0., True
                else:
                    on_ground = False
                break
        m.update(pos=[x,y,test_z],vel=[vx,vy,vz],grounded=on_ground)
        ay, ap = action.get('aim', m['aim'])
        m['aim'][0] = delta(m['aim'][0] + clamp(delta(ay,m['aim'][0]), -DT*s['turn_rate'], DT*s['turn_rate']), 0)
        m['aim'][1] += clamp(ap-m['aim'][1], -DT*s['pitch_rate'], DT*s['pitch_rate'])
        d = math.dist((x,y), self.goal[:2])
        self.min_dist = min(self.min_dist, d)
        if self.family == 'loot' and not self.collected and action.get('take') == 8012 and d<=4 and abs(test_z-self.goal[2])<=4:
            self.collected = True
            m['weapons'][1] = dict(kind='lightning', stats=self.cfg['weapons']['lightning'], cooldown=1)
            self.events.append(dict(type='took', id=8012, kind='lightning', slot=1))
        if self.family == 'drop' and not self.captured:
            self.progress = self.progress+DT if d<=8 else 0
            if self.progress>=4-1e-8:
                self.captured = True
                m['hp'], m['energy'] = m['max_hp'], m['max_energy']
                m['cubes'] += 3
                self.events.append(dict(type='drop', id=20003, cubes=m['cubes']))
        if self.family == 'zone' and self.crossed is None and d <= 70:
            self.crossed = self.time
        zone = self.zone()
        if math.dist((x,y), zone['center']) > zone['radius']:
            self.time_out += DT
            self.zone_damage += DT*zone['dps']
            m['hp'] -= DT*zone['dps']
            self.last_damage = self.time
            self.events.append(dict(type='damaged', weapon='zone', by=None, bearing=None, amount=DT*zone['dps']))
        elif self.time-self.last_damage >= s['regen_delay']:
            m['hp'] = min(m['max_hp'], m['hp']+s['regen_per_s']*DT)
        self.time += DT

    def run(self):
        while self.time < self.durations[self.family]-.001 and self.me['hp'] > 0:
            action = self.pilot.act(self.observation())
            self.step(action)
            self.step(action)
            if self.captured or self.collected:
                break
        goal_dist = math.dist(self.me['pos'][:2], self.goal[:2])
        if self.family == 'zone':
            success = goal_dist <= 70 and self.me['hp'] > 0
        else:
            success = self.captured or self.collected
        return dict(success=bool(success), time=round(self.time,2), zone_damage=round(self.zone_damage,1),
                    remaining_m=round(goal_dist,1), nearest_m=round(self.min_dist,1),
                    target_entry_s=None if self.crossed is None else round(self.crossed,2))


def load_starter(kit):
    sys.path.insert(0, str(kit/'python'))
    import mechfight
    registered = []
    run = mechfight.run
    try:
        mechfight.run = registered.append
        spec = importlib.util.spec_from_file_location('campus_kit_example', kit/'python/example_bot.py')
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    finally:
        mechfight.run = run
    class Starter(registered[0]):
        def act(self, obs):
            action = super().act(obs)
            mechfight.draw.take()
            return action
    return Starter


def integrated(hello, no_route=False):
    from main import Pilot
    bot = Pilot(hello)
    if no_route:
        bot.arena.waypoint = lambda pos, goal, threats=(): goal[:2]
    return bot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--bot-dir', type=Path, required=True)
    parser.add_argument('--policies', nargs='+', choices=['starter','pilot','no-route'], default=['starter','pilot'])
    parser.add_argument('--families', nargs='+', choices=['zone','loot','drop'], default=['zone','loot','drop'])
    parser.add_argument('--split', choices=['dev','holdout'], default='dev')
    parser.add_argument('--cases', type=int, default=8)
    parser.add_argument('--first', type=int, default=0)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args()
    kit = args.kit.resolve()
    sys.path.insert(0, str(args.bot_dir.resolve()))
    world = Campus(kit)
    factories = dict(starter=load_starter(kit), pilot=integrated, **{'no-route': lambda h: integrated(h,True)})
    results = []
    groups = collections.defaultdict(list)
    for family in args.families:
        for index in range(args.first, args.first+args.cases):
            blocked = family != 'loot' and index%2 == 0
            seed = (4141 if args.split=='dev' else 70951) + 1601*index
            for policy in args.policies:
                trial = Trial(world, kit, factories[policy], family, seed, blocked)
                row = dict(policy=policy,family=family,seed=seed,split=args.split,blocked=blocked,
                           start=trial.me['pos'][:],goal=trial.goal,**trial.run())
                print(json.dumps(row),flush=True)
                results.append(row)
                groups[family,policy].append(row)
    for (family,policy), rows in groups.items():
        print(f"{family} / {policy}: {sum(r['success'] for r in rows)}/{len(rows)}"
              f"  mean zone damage {statistics.mean(r['zone_damage'] for r in rows):.1f}"
              f"  median time {statistics.median(r['time'] for r in rows):.2f}s",file=sys.stderr)
    if args.json:
        args.json.write_text(json.dumps(results,indent=2)+'\n')


if __name__ == '__main__':
    main()
