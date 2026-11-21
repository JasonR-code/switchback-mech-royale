"""Shared-torso fire control for the four mechfight weapons."""
from dataclasses import dataclass
from math import atan2, ceil, cos, dist, hypot, pi, radians, sin, sqrt


ZERO = (0.0, 0.0, 0.0)


def wrap(a):
    return (a + pi) % (2 * pi) - pi


def clamp(x, low, high):
    return max(low, min(high, x))


def gun_solution(delta, vel, speed, barrel):
    """First positive intersection with a moving point and a straight shot."""
    x, y, z = delta
    vx, vy, vz = vel
    # Solve |delta + vel*t| = barrel + speed*t.
    a = speed * speed - (vx * vx + vy * vy + vz * vz)
    b = barrel * speed - (x * vx + y * vy + z * vz)
    c = x * x + y * y + z * z - barrel * barrel
    if c <= 0:
        flight = 0.
    elif abs(a) < 1e-8:
        if b <= 0:
            return None
        flight = c / (2 * b)
    else:
        discriminant = b * b + a * c
        if discriminant < 0 or b + sqrt(discriminant) <= 0:
            return None
        flight = c / (b + sqrt(discriminant))
    dx, dy, dz = x + vx * flight, y + vy * flight, z + vz * flight
    return atan2(dy, dx), atan2(dz, hypot(dx, dy)), flight


def mortar_solutions(delta, vel, speed, gravity, barrel, ttl):
    """Intercept roots with gravity, tube offset, finite lifetime and moving target."""
    x, y, z = delta
    vx, vy, vz = vel
    c0 = x*x + y*y + z*z - barrel*barrel
    c1 = 2 * (x*vx + y*vy + z*vz - speed*barrel)
    c2 = vx*vx + vy*vy + vz*vz + gravity*z - speed*speed
    c3, c4 = gravity*vz, gravity*gravity*.25
    if c0 <= 0 or ttl <= 0 or c4 < 1e-8:
        return []

    def error(t):
        return (((c4*t + c3)*t + c2)*t + c1)*t + c0

    def derivative(t):
        return ((4*c4*t + 3*c3)*t + 2*c2)*t + c1

    # Roots of the second derivative delimit monotonic pieces of the first.
    # Splitting there also catches near-tangent trajectories at maximum range.
    discriminant = 36*c3*c3 - 96*c4*c2
    extrema = []
    if discriminant > 0:
        rad = sqrt(discriminant)
        extrema = [(-6*c3 - rad)/(24*c4), (-6*c3 + rad)/(24*c4)]
    bounds = [0.] + [p for p in extrema if 0 < p < ttl] + [ttl]

    def split_roots(fn, points):
        roots = []
        lo, left = points[0], fn(points[0])
        for hi in points[1:]:
            right = fn(hi)
            if left * right < 0:
                a, b = lo, hi
                for _ in range(20):
                    mid = (a + b)*.5
                    if fn(mid) * left <= 0:
                        b = mid
                    else:
                        a = mid
                roots.append((a + b)*.5)
            elif abs(right) < 1e-7:
                roots.append(hi)
            lo, left = hi, right
        return roots

    stations = split_roots(derivative, bounds)
    roots = split_roots(error, [0.] + [s for s in stations if 0 < s < ttl] + [ttl])
    result = []
    for t in roots:
        dx, dy, dz = x + vx*t, y + vy*t, z + vz*t + gravity*.5*t*t
        result.append((atan2(dy, dx), atan2(dz, hypot(dx, dy)), t))
    return result


def arc_clear(arena, origin, solution, speed, gravity, barrel):
    yaw, pitch, flight = solution
    aim = (cos(yaw)*cos(pitch), sin(yaw)*cos(pitch), sin(pitch))
    # The server shortens the muzzle displacement at a nearby obstruction.
    start = tuple(p + barrel*d for p, d in zip(origin, aim))
    if not arena.clear(origin, start):
        return False
    vx, vy, vz = (speed*d for d in aim)
    previous = start
    # Each straight chord has <0.35 m of vertical sag error at default gravity.
    divisions = max(1, min(36, ceil(flight * sqrt(max(1., gravity) / 2.8))))
    for i in range(1, divisions + 1):
        t = flight * i / divisions
        pt = (start[0] + t*vx, start[1] + t*vy, start[2] + t*(vz - gravity*.5*t))
        if not arena.clear(previous, pt):
            return False
        previous = pt
    return True


def lightning_windows(yaw, distance, cone, obstacles):
    """Yaw offsets that place this target first in the lightning cone.

    Keep a small margin on both sides for engine tick ordering and movement.
    Subtract each nearer body's cone in target-relative angles to handle +/-pi.
    """
    margin = min(.036, cone*.1)
    windows = [(-cone+margin, cone-margin)]
    for d, other_yaw, _, _, _ in obstacles:
        if d >= distance-.02:
            break
        center = wrap(other_yaw-yaw)
        left, right = center-cone-margin, center+cone+margin
        remaining = []
        for a,b in windows:
            if a < left:
                remaining.append((a, min(left,b)))
            if b > right:
                remaining.append((max(right,a), b))
        windows = remaining
        if not windows:
            break
    return [(wrap(yaw + .5*(a+b)), (b-a)*.5) for a,b in windows if b-a > .012]


@dataclass(slots=True)
class Contact:
    obj: dict
    kind: str
    center: tuple
    velocity: tuple
    radius: float
    height: float
    distance: float
    weight: float


@dataclass(slots=True)
class Shot:
    slot: int
    target: Contact
    yaw: float
    pitch: float
    yaw_tol: float
    pitch_tol: float
    value: float


class Combat:
    def __init__(self, config):
        self.cfg = config
        self.base = config.get('mech', {})
        self.weapons = config.get('weapons', {})
        match = config.get('match', {})
        self.step = 1 / max(1, match.get('tick_hz', 20))
        self.interval = self.step * match.get('decide_every', 2)
        self.previous = {}
        self.incoming = {}
        self.focus = None

    def contacts(self, obs, intent, origin):
        me = obs['self']
        pressure = intent.get('pressure', 0.)
        focus = intent.get('focus')
        recover = intent.get('recover', False)
        retreat = intent.get('escape', False)
        health_ratio = me.get('hp', 1400) / max(1., me.get('max_hp', 1400))
        now = obs.get('t', 0.)
        for event in obs.get('events', ()):
            if event.get('type') == 'damaged' and event.get('by') is not None:
                self.incoming[event['by']] = now
        attackers = {attacker for attacker,t in self.incoming.items() if now-t < 1.8}
        contacts = []
        for group in ('mechs', 'crates'):
            for obj in obs.get(group, ()):
                p = obj.get('pos')
                if not p or len(p) < 3 or obj.get('hp', 1) <= 0:
                    continue
                oid = obj.get('id')
                kind = obj.get('kind', 'crate')
                v = tuple(obj.get('vel') or ZERO)
                d = hypot(p[0] - origin[0], p[1] - origin[1])
                if kind == 'mech':
                    scale = 1 + self.cfg.get('cubes', {}).get('size_per_cube', .05)*obj.get('cubes', 0)
                    radius = self.base.get('radius', 2.5)*scale
                    height = self.base.get('height', 9)*scale
                    foe_yaw = (obj.get('aim') or [0.])[0]
                    bearing_home = atan2(origin[1] - p[1], origin[0] - p[0])
                    error = abs(wrap(foe_yaw - bearing_home))
                    aiming_at_us = error < .28
                    weapons = obj.get('weapons') or []
                    hp = obj.get('hp', self.base.get('hp', 1400))
                    immediate = d < 50 or oid in attackers or (aiming_at_us and d < 125)
                    # Breaking LOS for five seconds restores HP. Remote chip damage
                    # can reset our own recovery and attract another member of the squad.
                    if recover and not immediate and hp > 250:
                        continue
                    weight = 1.0 + 48/(30+d) + min(2.2, 260/(65+hp))
                    if aiming_at_us:
                        weight += .55 + .4 * obj.get('charging', False)
                    if 'lightning' in weapons and d < 50:
                        weight += .7
                    if oid in attackers:
                        weight += .7
                    if retreat and not immediate:
                        weight *= .68
                    if error > pi/2:
                        weight *= 1.12
                else:
                    cfg = self.cfg.get('npc' if kind == 'npc' else 'crates', {})
                    radius = cfg.get('radius', 1.8 if kind == 'npc' else 1.4)
                    height = cfg.get('height', 3.5 if kind == 'npc' else 2.4)
                    defensive = kind == 'npc' and (oid in attackers or d < 28)
                    if not defensive and (retreat or recover or pressure > .72 or intent.get('urgent')):
                        continue
                    # Distant boxes reveal us and leave upgrades for other mechs.
                    if d > (80 if oid == focus else 45) and not defensive:
                        continue
                    weight = .65 + 24/(20+d)
                    if defensive:
                        weight += .65
                    weight *= 1 - .6*clamp(pressure, 0., 1.)
                    if health_ratio < .7 and not defensive:
                        weight *= .65
                if oid == focus:
                    weight *= 1.42
                if oid == self.focus:
                    weight *= 1.1
                if d > 85:
                    weight /= 1 + (d-85)/200
                center = (p[0], p[1], p[2] + .51 * height)
                # Suppress long-range extrapolation after a sudden direction change.
                # Vertical trajectories are only trusted over short horizons.
                old = self.previous.get(oid)
                if kind != 'crate' and old and 0 < now-old[0] < .25:
                    dt = now-old[0]
                    dv = hypot(v[0]-old[1][0], v[1]-old[1][1])
                    confidence = 1 - .38*clamp((dv/dt-12)/50, 0, 1)
                    forecast = (v[0]*confidence, v[1]*confidence, v[2])
                else:
                    forecast = v
                if kind != 'crate':
                    self.previous[oid] = (now, v)
                contacts.append(Contact(obj, kind, center, forecast, radius, height, d, weight))
        contacts.sort(key=lambda c: c.weight, reverse=True)
        return contacts

    def act(self, obs, arena, intent):
        me = obs.get('self') or {}
        actual = me.get('aim') or [0., 0.]
        body = self.base | (me.get('stats') or {})
        pos = me.get('pos') or ZERO
        muzzle = (pos[0], pos[1], pos[2] + body.get('muzzle_height', 7))
        tube = (pos[0], pos[1], pos[2] + body.get('height', 9) + .5)
        barrel = body.get('radius', 2.5) + .5
        yaw_rate = body.get('turn_rate', 4)
        pitch_rate = body.get('pitch_rate', 3)
        pitch_limits = (body.get('min_pitch', -.7), body.get('max_pitch', 1.3))
        inventory = list((me.get('weapons') or [])[:2])
        inventory += [None] * (2-len(inventory))
        contacts = self.contacts(obs, intent, muzzle)
        now = obs.get('t', 0.)
        protected = intent.get('recover') or intent.get('cease_fire') or (
            intent.get('escape') and me.get('hp', 1400) < .7*me.get('max_hp',1400))
        lightning = next((w for w in inventory if w and w.get('kind') == 'lightning'), None)
        obstacles = []
        if lightning:
            lightning_range = (lightning.get('stats') or {}).get('range', self.weapons.get('lightning', {}).get('range',45))
            # Even a crate we deliberately avoid farming can intercept the first arc.
            for group in ('mechs', 'crates'):
                for obj in obs.get(group, ()):
                    p = obj.get('pos')
                    if not p or hypot(p[0]-muzzle[0],p[1]-muzzle[1]) > lightning_range+2:
                        continue
                    kind = obj.get('kind', 'crate')
                    if kind == 'mech':
                        h = self.base.get('height', 9)*(1 + self.cfg.get('cubes',{}).get('size_per_cube',.05)*obj.get('cubes',0))
                    else:
                        h = self.cfg.get('npc' if kind=='npc' else 'crates', {}).get('height', 3.5 if kind=='npc' else 2.4)
                    point = (p[0],p[1],p[2]+.51*h)
                    d = dist(point,muzzle)
                    if d <= lightning_range and arena.clear(muzzle,point):
                        obstacles.append((d, atan2(p[1]-muzzle[1],p[0]-muzzle[0]), obj['id'], kind, point))
            obstacles.sort()
        arc_risk = False
        if any(w and w.get('kind') == 'laser' for w in inventory):
            arc_stats = self.weapons.get('lightning', {})
            for target in contacts:
                if target.kind != 'mech' or 'lightning' not in (target.obj.get('weapons') or []):
                    continue
                if target.distance > arc_stats.get('range',45)+2:
                    continue
                bearing = atan2(muzzle[1]-target.center[1],muzzle[0]-target.center[0])
                facing = (target.obj.get('aim') or ZERO)[0]
                if abs(wrap(facing-bearing)) < radians(arc_stats.get('cone_deg',30))+ .36 and arena.clear(target.center,muzzle):
                    arc_risk = True
                    break
        shots = []
        stats_by_slot = []
        for slot, w in enumerate(inventory):
            kind = (w or {}).get('kind')
            stats = self.weapons.get(kind, {}) | ((w or {}).get('stats') or {})
            stats_by_slot.append(stats)
            if kind not in ('gun', 'laser', 'lightning', 'mortar'):
                continue
            cooldown = w.get('cooldown', 0)
            if kind == 'mortar' and cooldown > .32:
                continue
            if kind == 'lightning' and me.get('energy', 100) < stats.get('energy', 3):
                continue
            charge = w.get('charge', 0)
            count = 0
            for target in contacts[:(8 if kind == 'mortar' else 27)]:
                if count >= (4 if kind == 'mortar' else 9):
                    break
                c = target.center
                if protected and kind == 'mortar' and not arena.clear(muzzle,c):
                    # Firing from behind a wall resets outgoing-damage regen.
                    # The health trade is worthwhile only to finish a weak mech.
                    if target.kind != 'mech' or target.obj.get('hp', 1400) > stats.get('splash',160):
                        continue
                windows = None
                # Aim half a physics tick ahead for discrete movement/fire ordering.
                vx, vy, vz = target.velocity
                origin = tube if kind == 'mortar' else muzzle
                delay = self.step * .5
                dx = c[0] + vx*delay - origin[0]
                dy = c[1] + vy*delay - origin[1]
                dz = c[2] + vz*delay - origin[2]
                distance = max(1., hypot(dx, dy, dz))
                yaw_tolerance = atan2(target.radius*.92, max(1., hypot(dx, dy)))
                pitch_tolerance = atan2(target.height*.43, distance)
                value = target.weight
                if kind == 'mortar':
                    speed, gravity, ttl = stats.get('speed', 72), stats.get('gravity', 22), stats.get('ttl', 7)
                    if min(speed, gravity, ttl) <= 0 or distance > speed*ttl+barrel:
                        continue
                    splash = stats.get('splash_radius', 7)
                    if target.distance <= splash + barrel + 4:
                        continue
                    # Long airborne paths rarely continue at the current vertical
                    # velocity all the way to impact. Bound the assumed displacement.
                    v = (vx, vy, vz * min(1., .30 * speed / distance))
                    options = mortar_solutions((dx, dy, dz), v, speed, gravity, barrel, ttl)
                    picked = None
                    for sol in options:
                        yaw, pitch, flight = sol
                        if not pitch_limits[0] <= pitch <= pitch_limits[1]:
                            continue
                        # Compare predicted locations at the impact tick too.
                        own_v = me.get('vel') or ZERO
                        separation = hypot(dx + vx*flight-own_v[0]*min(flight,.55),
                                           dy + vy*flight-own_v[1]*min(flight,.55))
                        if separation < splash + barrel + 2:
                            continue
                        if arc_clear(arena, tube, sol, speed, gravity, barrel):
                            picked = sol
                            break
                    if picked is None:
                        continue
                    yaw, pitch, flight = picked
                    # A moving target has more time to juke a high arc.
                    value *= 3.2 / (1 + .58*max(0., flight-0.5) * min(1., hypot(vx,vy)/4))
                    yaw_tolerance = atan2(max(target.radius, splash*.52), distance)
                    pitch_tolerance = atan2(max(target.height*.37, splash*.44), distance)
                else:
                    if distance > stats.get('range', 45 if kind == 'lightning' else 230) + (0 if kind == 'lightning' else barrel):
                        continue
                    if kind == 'gun':
                        speed = stats.get('speed', 252)
                        if speed <= 0:
                            continue
                        v = (vx, vy, vz * min(1., .25*speed/distance))
                        sol = gun_solution((dx, dy, dz), v, speed, barrel)
                        if sol is None:
                            continue
                        yaw, pitch, flight = sol
                        if speed*flight > stats.get('range', 230):
                            continue
                        point = (origin[0]+dx+v[0]*flight, origin[1]+dy+v[1]*flight, origin[2]+dz+v[2]*flight)
                        if w.get('reload', 0) > self.interval or w.get('ammo', 1) <= 0:
                            value *= .08
                        value *= 1/(1 + max(0., distance-50)*radians(stats.get('spread_deg', .6))/max(1.,target.radius))
                    else:
                        yaw, pitch = atan2(dy,dx), atan2(dz,hypot(dx,dy))
                        point = (origin[0]+dx, origin[1]+dy, origin[2]+dz)
                    if not arena.clear(origin, point):
                        # Over a parapet the upper body may still be exposed.
                        lift = target.height*.35
                        point = (point[0], point[1], point[2]+lift)
                        if kind == 'lightning' or not arena.clear(origin, point):
                            continue
                        pitch = atan2(point[2]-origin[2], hypot(point[0]-origin[0], point[1]-origin[1]))
                        pitch_tolerance *= .34
                    if kind == 'lightning':
                        identity = target.obj.get('id')
                        item = next((o for o in obstacles if o[2] == identity),None)
                        if item is None:
                            continue
                        windows = lightning_windows(item[1],item[0],radians(stats.get('cone_deg',30)),obstacles)
                        if not windows:
                            continue
                        pitch_tolerance = pi
                        # Extra nearby enemy bodies can receive chain damage.
                        nearby = sum(o[2]!=identity and o[3]=='mech' and dist(o[4],c) <= stats.get('chain_range',14)
                                     for o in obstacles)
                        value *= 1.45 + .16*min(nearby,stats.get('chain',2))
                        if 'laser' in (target.obj.get('weapons') or []):
                            value *= 1.24
                    elif kind == 'laser':
                        max_charge = max(.01, stats.get('charge', .75))
                        damage = stats.get('damage', 315)
                        if 'mortar' in (target.obj.get('weapons') or []):
                            damage *= 1 + stats.get('cookoff', .6)
                        frac = clamp(charge/max_charge, 0., 1.)
                        fraction_now = stats.get('min_frac', .35) + (1-stats.get('min_frac',.35))*frac
                        lethal = target.obj.get('hp', 1e5) <= damage*fraction_now*.93
                        mobile = intent.get('escape') or intent.get('urgent')
                        if charge <= 0 and (arc_risk or (mobile and not lethal and target.distance > 48)):
                            continue
                        release = (charge >= max_charge-.005 or
                                   (charge >= stats.get('min_charge',.15) and
                                    (lethal or mobile or arc_risk)))
                        # During the charge the other slot can aim and fire.
                        value *= (3.8 if release else (.45 if charge < max_charge-.16 else 1.2))
                if kind != 'lightning' and not (pitch_limits[0]-pitch_tolerance <= pitch <= pitch_limits[1]+pitch_tolerance):
                    continue
                if cooldown > self.interval:
                    value *= .12 if cooldown > .35 else .38
                yaw_delay = abs(wrap(yaw-actual[0]))/max(.1,yaw_rate)
                value /= 1 + .42*yaw_delay
                for center_yaw, tolerance in windows or [(yaw, yaw_tolerance)]:
                    shots.append(Shot(slot, target, center_yaw, clamp(pitch,*pitch_limits), tolerance, pitch_tolerance, value))
                count += 1

        # Compatible aim lets both triggers work (notably gun + lightning).
        # Count each slot once, even when several bodies overlap its cone.
        best = None
        best_value = -1.
        for shot in shots:
            support = max((alt.value for alt in shots if alt.slot != shot.slot
                           and abs(wrap(alt.yaw-shot.yaw)) <= alt.yaw_tol
                           and abs(alt.pitch-shot.pitch) <= alt.pitch_tol), default=0.)
            total = shot.value + .85*support
            if total > best_value:
                best, best_value = shot, total
        if best:
            cmd = [best.yaw, best.pitch]
            self.focus = best.target.obj.get('id')
        else:
            cmd = [wrap(intent.get('scan', actual[0])), 0.]
            self.focus = None
        fire = [False, False]
        reload_gun = False
        for slot, w in enumerate(inventory):
            if not w:
                continue
            kind, stats = w.get('kind'), stats_by_slot[slot]
            wait = min(self.interval, max(self.step, w.get('cooldown', 0)))
            predicted_yaw = actual[0] + clamp(wrap(cmd[0]-actual[0]), -yaw_rate*wait, yaw_rate*wait)
            predicted_pitch = actual[1] + clamp(cmd[1]-actual[1], -pitch_rate*wait, pitch_rate*wait)
            potential = [s for s in shots if s.slot == slot]
            aligned = [s for s in potential if abs(wrap(s.yaw-predicted_yaw)) <= s.yaw_tol and
                       abs(s.pitch-predicted_pitch) <= s.pitch_tol and
                       abs(wrap(s.yaw-cmd[0])) <= s.yaw_tol and abs(s.pitch-cmd[1]) <= s.pitch_tol]
            if kind == 'laser':
                charge = w.get('charge', 0)
                max_charge = stats.get('charge', .75)
                # Releasing off-axis wastes the whole beam. If a target exists,
                # retain the charge while the torso catches up.
                fire[slot] = bool(potential) and w.get('cooldown', 0) <= self.interval
                if aligned and charge > 0:
                    hit = max(aligned, key=lambda s: s.value).target
                    frac = min(1., charge/max(.01,max_charge))
                    base_frac = stats.get('min_frac', .35)
                    damage = stats.get('damage', 315)*(base_frac + (1-base_frac)*frac)
                    if 'mortar' in (hit.obj.get('weapons') or []):
                        damage *= 1 + stats.get('cookoff',.6)
                    if charge >= max_charge-.005 or (charge >= stats.get('min_charge',.15)
                            and (hit.obj.get('hp',1e5) <= .93*damage or intent.get('escape') or intent.get('urgent') or arc_risk)):
                        fire[slot] = False
            elif kind in ('gun', 'mortar', 'lightning'):
                fire[slot] = bool(aligned) and w.get('cooldown', 0) <= self.interval
                if kind == 'gun':
                    ammo, mag = w.get('ammo', 1), stats.get('mag', 12)
                    reloading = w.get('reload', 0) > 0
                    fire[slot] &= ammo > 0 and not reloading
                    reload_gun = not reloading and (ammo <= 0 or
                                 (not potential and ammo <= mag*(.5 if intent.get('pressure', 0) > .4 else .85)))
        return {'aim': cmd, 'fire': fire, 'reload': reload_gun}
