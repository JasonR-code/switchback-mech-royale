"""Look for nearby cover after two identified opponents actually deal damage."""
from math import atan2, cos, dist, hypot, isfinite, pi, sin

from strategy import future_circle


class LaneCover:
    def __init__(self):
        self.hits = {}
        self.signature = ()
        self.next_search = 0.
        self.destination = None

    def _observe(self, obs):
        t = obs['t']
        for event in obs['events']:
            kind = event['type']
            if kind == 'kill':
                self.hits.pop(event.get('target'), None)
                continue
            source, angle = event.get('by'), event.get('bearing')
            if (kind != 'damaged' or event.get('weapon') not in ('gun', 'laser', 'lightning')
                    or type(source) not in (int, float) or type(angle) not in (float, int)
                    or not isfinite(angle)):
                continue
            self.hits[source] = (t, angle, tuple(obs['self']['pos'][:2]), event['weapon'])
        for source, (when, _, _, _) in tuple(self.hits.items()):
            if not 0 <= t-when <= 3.:
                del self.hits[source]

    def waypoint(self, obs, arena, intent, normal):
        self._observe(obs)
        me, t = obs['self'], obs['t']
        if (len(self.hits) < 2 or intent['urgent'] or not me['grounded']
                or arena.climb_height is not None):
            self.destination, self.signature = None, ()
            return None
        sources = tuple(sorted(self.hits))
        if sources != self.signature or t >= self.next_search:
            self.destination = self._find(obs, arena, normal)
            self.signature, self.next_search = sources, t + .45
        if self.destination and arena.can_move(me['pos'], self.destination):
            return self.destination
        return None

    def incoming_guns(self, obs):
        if len(self.hits) < 2:
            return ()
        p = obs['self']['pos']
        reported = {e['id'] for e in obs['mechs']}
        directions = []
        missing = False
        for ident, (when,yaw,hit_pos,weapon) in self.hits.items():
            if weapon == 'gun' and obs['t']-when <= 1.2 and dist(p[:2],hit_pos) <= 16:
                directions.append((-sin(yaw),cos(yaw)))
                missing |= ident not in reported
        return tuple(directions) if missing else ()

    def _find(self, obs, arena, normal):
        me, zone = obs['self'], obs['zone']
        p = me['pos']
        height = me['stats'].get('height', 9) * .55
        reported = {e['id']: e for e in obs['mechs'] if e['kind'] == 'mech'}
        eyes, bearings = [], []
        recent = sorted(self.hits, key=lambda k: self.hits[k][0], reverse=True)
        for ident in recent[:4]:
            enemy = reported.get(ident)
            if enemy:
                x,y,z = enemy['pos']
                eyes.append((x,y,z+7*(1+.05*enemy.get('cubes',0))))
            else:
                when, yaw, hit_pos, _ = self.hits[ident]
                if obs['t']-when <= 1.5 and dist(p[:2], hit_pos) <= 16:
                    # Probe nearby shielding across a small angular sector. A hit
                    # bearing supplies no range or exact unseen shooter position.
                    bearings.append([(32*cos(yaw+a),32*sin(yaw+a)) for a in (-.16,.16)])
        if len(eyes)+len(bearings) < 2:
            return None
        others = sorted((e for i,e in reported.items() if i not in self.hits),
                        key=lambda e: dist(p[:2],e['pos'][:2]))[:2]
        extra = [(*e['pos'][:2],e['pos'][2]+7*(1+.05*e.get('cubes',0))) for e in others]
        def exposure(at):
            x,y,z = at
            body = (x,y,z+height)
            count = sum(arena.clear(eye,body) for eye in eyes)
            for ends in bearings:
                count += any(arena.clear(body,(x+dx,y+dy,body[2])) for dx,dy in ends)
            return count, sum(arena.clear(eye,body) for eye in extra)

        dx, dy = normal[0]-p[0], normal[1]-p[1]
        length = hypot(dx,dy)
        heading = atan2(dy,dx)
        current, extra_here = exposure(p)
        if current < 2:
            return None
        # Credit the existing leg for shielding it already reaches within this horizon.
        standard = current
        for r in (8., 17., 30.):
            step = min(r, length)/max(.001,length)
            x,y = p[0]+step*dx, p[1]+step*dy
            point = (x,y,arena.surface(x,y,p[2]))
            if not arena.can_move(p, point):
                break
            standard = min(standard, exposure(point)[0])
            if r >= length:
                break
        if standard == 0:
            return None
        center, radius = future_circle(zone,obs['t'],4.)
        limit = max(dist(p[:2],center), radius-min(5,radius*.12))
        best, best_cost = None, float('inf')
        for j in range(16):
            angle = heading + j*pi/8
            ux,uy = cos(angle),sin(angle)
            previous = 0.
            transit = 0.
            for r in (8.,17.,30.):
                x,y = p[0]+r*ux, p[1]+r*uy
                q = (x,y,arena.surface(x,y,p[2]))
                if abs(q[2]-p[2])>4 or not arena.can_move(p,q):
                    break
                lanes, other = exposure(q)
                transit += (r-previous)*(lanes + other*.5)
                previous = r
                if lanes >= standard or other > extra_here or dist(q[:2],center) > limit:
                    continue
                # Prefer cutting more active lanes, then short, protected travel.
                cost = 42*lanes + 9*other + .36*transit + r - 3*cos(angle-heading)
                if cost < best_cost:
                    best, best_cost = q, cost
        return best
