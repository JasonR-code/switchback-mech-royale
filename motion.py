"""Short-horizon motion selection for the Mech Royale match protocol."""
import math
import random

HORIZON = 0.65
ANGLES = [math.radians(a) for a in (0, 28, -28, 55, -55, 85, -85, 120, -120, 155, -155, 180)]
ROTATIONS = [(math.cos(a), math.sin(a)) for a in ANGLES]


def displacement(vx, vy, ux, uy, ramp, t):
    """Integral of velocity as it accelerates to (ux,uy) over ramp seconds."""
    mix = t - ramp / 2 if t >= ramp else t * t / (2 * ramp)
    return vx * t + (ux - vx) * mix, vy * t + (uy - vy) * mix


def norm(x, y):
    d = math.hypot(x, y)
    return (x / d, y / d) if d > 1e-8 else (0.0, 0.0)


class Motion:
    def __init__(self, config, seed=0):
        self.config = config
        self.random = random.Random(seed)
        self.turn_at = -1.0
        self.side = self.random.choice((-1.0, 1.0))
        self.boosting = False
        self.climb_until = -1.0
        self.climb_z = None
        self.progress_sample = None
        self.recovery_until = -1.0
        self.next_recovery = 0.

    def _hazards(self, obs, arena, stats, speed):
        x, y, z = obs['self']['pos']
        vx, vy, _ = obs['self'].get('vel', (0, 0, 0))
        height = stats.get('height', 9)
        radius = stats.get('radius', 2.5)
        mortar = self.config.get('weapons', {}).get('mortar', {})
        g = max(1, mortar.get('gravity', 22))
        splash = mortar.get('splash_radius', 7)
        bullet_sizes = self.config.get('projectile', {})
        lines, blasts = [], []
        for p in obs.get('projectiles', ()):
            px, py, pz = p['pos']
            ux, uy, uz = p.get('vel', (0, 0, 0))
            kind = p.get('kind')
            dx, dy = px - x, py - y
            rx, ry = ux - vx, uy - vy
            v2 = rx * rx + ry * ry
            t = -(dx * rx + dy * ry) / max(v2, 0.01)
            shell = kind == 'mortar'
            if -0.03 <= t <= 0.88:
                t = max(0.0, t)
                dz = pz - z + uz * t - (0.5 * g * t * t if shell else 0)
                miss = math.hypot(dx + rx * t, dy + ry * t)
                reach = radius + 2 + (speed + math.hypot(vx, vy)) * t
                if -7 < dz < height + 8 and miss < reach:
                    body = radius + bullet_sizes.get(str(kind) + '_radius', 0.3)
                    # Keep the likeliest contacts in dense projectile observations.
                    lines.append((t + miss / max(reach, 1), t, dx, dy, pz-z, ux, uy, uz,
                                  g if shell else 0, body, 42 if shell else 11 if kind == 'npc' else 20))
            if not shell or math.hypot(dx, dy) > 120:
                continue
            # Estimate impact on the terrain/roof near the shell's expected landing point.
            floor = z
            land = None
            for _ in range(2):
                disc = uz * uz + 2 * g * (pz - floor)
                if disc < 0:
                    break
                land = (uz + math.sqrt(disc)) / g
                if not 0 <= land <= 1.05:
                    land = None
                    break
                floor = arena.surface(px + ux * land, py + uy * land, pz)
            if land is not None:
                bx, by = dx + ux * land, dy + uy * land
                if math.hypot(bx, by) < splash + radius + speed * land + 5:
                    blasts.append((land, bx, by, floor-z, splash))
        lines.sort()
        blasts.sort()
        return lines[:8], blasts[:4]

    def _shooters(self, obs, arena, stats):
        x, y, z = obs['self']['pos']
        height = stats.get('height', 9)
        sources = []
        for m in obs.get('mechs', ()):
            ex, ey, ez = m['pos']
            dx, dy = x - ex, y - ey
            d = max(0.3, math.hypot(dx, dy))
            npc = m.get('kind') == 'npc'
            if d > (80 if npc else 245):
                continue
            yaw = m.get('aim', (0, 0))[0]
            alignment = (math.cos(yaw)*dx + math.sin(yaw)*dy) / d
            weight = (0.30 if npc else 1.0) * (0.25 + 0.75 * max(0., alignment)**4)
            weight *= min(1.1, 80 / max(d, 45))
            if m.get('charging'):
                weight *= 1.55
            if 'lightning' in m.get('weapons', ()) and d < 50:
                weight *= 1.24
            muzzle = (ex, ey, ez + (2.5 if npc else self.config.get('mech', {}).get('muzzle_height', 7) *
                                    (1 + m.get('cubes', 0) * self.config.get('cubes', {}).get('size_per_cube', .05))))
            sources.append((weight, d, dx/d, dy/d, muzzle))
        sources.sort(reverse=True)
        result = []
        for w, d, nx, ny, muzzle in sources[:3]:
            exposed = arena.clear(muzzle, (x, y, z + height * .55))
            result.append((w, d, nx, ny, muzzle, exposed))
        return result

    def _jet(self, obs, arena, waypoint, stats, now):
        me = obs['self']
        x, y, z = me['pos']
        required = getattr(arena, 'climb_height', None)
        if required is not None:
            self.climb_until = now + 0.35
            self.climb_z = required
        if self.climb_z is None or now > self.climb_until:
            return None
        # Keep a little clearance over the lip until horizontal motion carries us onto it.
        gap = self.climb_z + 0.7 - z
        if gap <= 0 and me.get('grounded', True):
            return None
        rise = max(1., stats.get('max_rise_speed', 10))
        jet_cost = stats.get('jet_drain', 15) * max(0., gap - 1.5) / rise
        energy = me.get('energy', 100)
        grounded = me.get('grounded', True)
        if grounded and required is not None and energy < jet_cost + 4:
            # Wait on the launch pad for enough energy to crest in one flight.
            return {'move': [0., 0.], 'boost': False, 'jump': False}
        if not grounded and energy < 1:
            return None
        desired = norm(waypoint[0]-x, waypoint[1]-y)
        vz = me.get('vel', (0, 0, 0))[2]
        return {'move': list(desired), 'jump': grounded and gap > 0,
                'boost': gap > 0 or (not grounded and vz < -1.5 and gap > -1.0)}

    def act(self, obs, arena, waypoint, intent):
        me = obs['self']
        stats = {**self.config.get('mech', {}), **me.get('stats', {})}
        x, y, z = me['pos']
        vx, vy, vz = me.get('vel', (0, 0, 0))
        now = obs.get('t', 0.0)
        # A short jet can clear steps and steep terrain where the walk model
        # predicts progress but successive observations show the mech is stuck.
        goal = intent.get('goal', waypoint)
        needs_travel = math.dist((x,y), goal[:2]) > max(10., intent.get('capture_radius', 0) + 2)
        if self.progress_sample is None or now - self.progress_sample[0] >= 1.1:
            previous = self.progress_sample
            self.progress_sample = (now, x, y)
            if (previous and needs_travel and me.get('grounded', True) and
                    now >= self.next_recovery and me.get('energy', 0) >= 20 and
                    math.hypot(x-previous[1], y-previous[2]) < 1.25 and
                    math.hypot(waypoint[0]-x, waypoint[1]-y) > 1.5 and
                    getattr(arena, 'climb_height', None) is None):
                self.recovery_until = now + .72
                self.next_recovery = now + 2.8
        if needs_travel and now < self.recovery_until:
            return {'move': list(norm(waypoint[0]-x, waypoint[1]-y)), 'boost': True,
                    'jump': bool(me.get('grounded', True))}
        jet = self._jet(obs, arena, waypoint, stats, now)
        if jet is not None:
            self.boosting = False
            return jet
        grounded = me.get('grounded', True)
        pressure = min(1., max(0., intent.get('pressure', 0)))
        urgent = bool(intent.get('urgent')) or not me.get('in_zone', True)
        escape = bool(intent.get('escape'))
        goal = intent.get('goal', waypoint)
        gd = math.hypot(goal[0]-x, goal[1]-y)
        wd = math.hypot(waypoint[0]-x, waypoint[1]-y)
        hold = intent.get('hold', False)
        capture = intent.get('capture_radius', 0) or 0
        walk = stats.get('walk_speed', 11.7)
        run = stats.get('boost_speed', 19.5)
        lines, blasts = self._hazards(obs, arena, stats, run)
        shooters = self._shooters(obs, arena, stats)
        contact = any(s[5] and s[0] > .14 for s in shooters)
        hazard = bool(lines or blasts)
        incoming = intent.get('incoming_guns', ())
        under_fire = hazard or contact or bool(incoming)
        if now >= self.turn_at:
            self.side *= -1
            self.turn_at = now + self.random.uniform(.8, 1.65)
        energy = me.get('energy', 100)
        emax = max(1, me.get('max_energy', stats.get('energy', 100)))
        reserve = .17 if under_fire or escape else .58
        if urgent:
            reserve = .025
        reuse = min(.96, reserve + (.38 if under_fire else .32))
        can_run = grounded and (gd > 8 or under_fire) and (not capture or gd > capture + 2)
        self.boosting = can_run and energy > emax * (reserve if self.boosting else reuse)
        if hazard and energy > max(6, .13 * emax) and can_run:
            self.boosting = True
        speed = run if self.boosting else walk
        if any(w and w.get('charge', 0) > 0 for w in me.get('weapons', ())):
            speed *= stats.get('charge_move_mult', .5)
        accel = max(1, stats.get('ground_accel', 58.5) if grounded else stats.get('air_accel', 12))
        height, radius = stats.get('height', 9), stats.get('radius', 2.5)
        dx, dy = norm(waypoint[0]-x, waypoint[1]-y)
        if wd < .2:
            dx, dy = norm(goal[0]-x, goal[1]-y)
        if dx == dy == 0:
            dx = 1.0
        slowing = min(1., max(.09, wd / max(1.0, speed * .32)))
        candidates = [(dx*c-dy*s, dy*c+dx*s) for c,s in ROTATIONS]
        candidates[0] = (dx * slowing, dy * slowing)
        candidates.append((0., 0.))
        if (gd < 1.4 or (capture and gd < capture * .65)) and not under_fire:
            candidates = [(0., 0.)]
        # The forecast is recomputed from measured velocities on each observation.
        best_score, best = -math.inf, (0., 0.)
        zone = obs.get('zone', {})
        cx, cy = zone.get('center', (x,y))
        zr = zone.get('radius', 1e6)
        margin = zr - math.hypot(x-cx,y-cy)
        air_floor = arena.ground(x, y) - z if not grounded and lines else 0.
        # Three pursuers in one firing lane should not triple the incentive
        # to run sideways. Keep making headway to cover while dodging
        # individual projectiles and preserving the reward for breaking LOS.
        exposed_weights = [s[0] for s in shooters if s[5] and s[0] > .14]
        squad_retreat = escape and len(exposed_weights) >= 2
        strafe_scale = 1 / max(1., sum(exposed_weights)) if squad_retreat else 1.
        range_weight = .62 if squad_retreat else .32
        orbit = contact and gd < 9 and wd < 9 and not (hold or capture or urgent)
        for mx, my in candidates:
            ux, uy = mx * speed, my * speed
            ramp = max(1e-6, math.hypot(ux-vx, uy-vy) / accel)
            ox, oy = displacement(vx, vy, ux, uy, ramp, HORIZON)
            ex, ey = x + ox, y + oy
            # Score progress towards the local waypoint, including overshoot.
            after = math.hypot(waypoint[0]-ex, waypoint[1]-ey)
            progress = wd - after
            score = progress * (1.42 if urgent else .94 if escape else .78)
            if orbit:
                # At a quiet anchor we can stand still. Once an opponent has a
                # firing lane, move within a loose radius around the objective.
                score = .14 * progress - max(0., after - 11.)
            if not arena.can_move((x,y,z), (ex,ey,z), radius):
                # Near corners, inertia can project a blocked endpoint even when
                # the new command is parallel to the wall. Test the steering direction.
                tx, ty = x + mx * 2.4, y + my * 2.4
                score -= 9 if arena.can_move((x,y,z), (tx,ty,z), radius) else 60
            future_z = arena.surface(ex, ey, z)
            if grounded and z - future_z > 4 and (len(goal) < 3 or goal[2] >= z-3):
                score -= min(16., .8 * (z - future_z))
            if margin < speed * HORIZON + 2 and zr > .05:
                outside = max(0., math.hypot(ex-cx,ey-cy) - zr)
                score -= min(4., .8 + zone.get('dps',20) / 80.) * outside
            if hold and gd < max(8., capture + 3):
                radial = math.hypot(ex-goal[0], ey-goal[1])
                limit = max(1.1, capture-1.2) if capture else 2.0
                score -= max(0., radial-limit) * (5. if capture else 1.7)
            # Forward motion and partial sideways motion can coexist. Suppress
            # jinking against remembered enemies separated from us by a wall.
            for n, (w, dist, nx, ny, muzzle, exposed) in enumerate(shooters):
                lateral = ox * (-ny) + oy * nx
                if exposed and squad_retreat:
                    # A radial sprint gives an aimed gun an easy shot even at full speed.
                    # Incoming gun fire matters most on exposed headings. A route crossing
                    # into cover still earns its separate LOS bonus below.
                    flight = min(.7, dist / max(1., self.config.get('weapons', {}).get('gun', {}).get('speed',252.)))
                    projected_miss = abs(lateral) / HORIZON * flight
                    score += 9 * strafe_scale * w * min(1., projected_miss / max(1., radius))
                if exposed:
                    score += strafe_scale * w * (.47 * abs(lateral) + .23 * self.side * lateral)
                    if escape and dist < 95:
                        score += w * range_weight * (ox*nx + oy*ny)
                if n < 2 and w > .1:
                    target_z = (future_z if grounded and abs(future_z-z)<4 else z) + height*.55
                    visible = arena.clear(muzzle, (ex,ey,target_z))
                    if exposed and not visible:
                        score += w * (8.5 + 7*pressure)
                    elif not exposed and visible:
                        score -= w * (7 + 6*pressure)
            if incoming:
                # Only activated after distinct attackers hit, including a gun
                # missing from the current mech list. Protect the worst crossing angle.
                score += 1.6 * min(abs(ox*nx + oy*ny) for nx,ny in incoming)
            for _, t, px, py, pz, pvx, pvy, pvz, gravity, body, weight in lines:
                ox1, oy1 = displacement(vx, vy, ux, uy, ramp, t)
                # Refine the closest point once with the candidate's changed lateral speed.
                ratio = min(1., t / ramp)
                rvx, rvy = pvx - vx - (ux-vx)*ratio, pvy - vy - (uy-vy)*ratio
                ex1, ey1 = px + pvx*t - ox1, py + pvy*t - oy1
                t = max(0., min(.90, t - (ex1*rvx + ey1*rvy) / max(1., rvx*rvx+rvy*rvy)))
                ox1, oy1 = displacement(vx, vy, ux, uy, ramp, t)
                h = pz + pvz*t - .5*gravity*t*t
                if not grounded:
                    h -= max(air_floor, vz*t - .5*stats.get('gravity',22)*t*t)
                vertical = max(0., -h, h-height)
                miss = math.hypot(px + pvx*t - ox1, py + pvy*t - oy1)
                score -= weight * max(0., 1 - max(0.,miss-body*.42)/(body*.75 + .8)) * max(0.,1 - vertical/1.4)
            for t, bx, by, bz, splash in blasts:
                ox1, oy1 = displacement(vx, vy, ux, uy, ramp, t)
                miss = math.hypot(bx-ox1, by-oy1)
                dz = max(0., -bz, bz-height)
                clearance = math.hypot(max(0.,miss-radius), dz)
                score -= 40 * max(0., 1 - clearance / max(1.,splash+1.))
            if score > best_score:
                best_score, best = score, (mx,my)
        return {'move': list(best), 'boost': bool(self.boosting and best != (0.,0.)), 'jump': False}
