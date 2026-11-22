"""Pure-Python stand-in for arena.Arena on the real v2 map (no geometry.so needed).

Lab use only. It reads mechfight-kit/arena/v2 (terrain grid + solid prisms) and offers the
interface the bot calls: bounds, set_body, ground, surface, clear, walkable, can_move,
cover, waypoint, climb_height. Simplifications against geometry.cpp:
- the body stands on terrain; roofs and bridge decks are not walkable, nobody climbs or jets;
- slopes do not block walking; trees, cars, fences and water are ignored entirely;
- line of sight: prisms are exact polygons, terrain is sampled every 2 m;
- cover = the C++ shelter rule (solid columns within 6/12/20 m in 8 directions / 5);
- waypoint = threat-weighted A* on a 4 m grid inside a play window, cached per goal.
"""
import array
import heapq
import json
import math
from pathlib import Path

BIN = 16.
STRIDE = 4.
DIRS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


def _inside(x, y, rings):
    inside = False
    for ring in rings:
        n = len(ring)
        vx, vy = ring[-1]
        for ux, uy in ring:
            if (uy > y) != (vy > y) and x < (vx-ux)*(y-uy)/(vy-uy) + ux:
                inside = not inside
            vx, vy = ux, uy
    return inside


def _cross(ax, ay, bx, by, cx, cy):
    return (bx-ax)*(cy-ay) - (by-ay)*(cx-ax)


def _segments_meet(ax, ay, bx, by, cx, cy, dx, dy):
    if max(ax, bx) < min(cx, dx) or max(cx, dx) < min(ax, bx) or max(ay, by) < min(cy, dy) or max(cy, dy) < min(ay, by):
        return False
    return (_cross(ax, ay, bx, by, cx, cy)*_cross(ax, ay, bx, by, dx, dy) <= 0 and
            _cross(cx, cy, dx, dy, ax, ay)*_cross(cx, cy, dx, dy, bx, by) <= 0)


class Prism:
    __slots__ = ('base', 'top', 'rings', 'l', 'r', 'b', 't')

    def __init__(self, base, top, rings):
        self.base, self.top, self.rings = base, top, rings
        xs = [p[0] for ring in rings for p in ring]
        ys = [p[1] for ring in rings for p in ring]
        self.l, self.r, self.b, self.t = min(xs), max(xs), min(ys), max(ys)


class PyArena:
    def __init__(self, map_dir, config=None, window=None, flat=False):
        root = Path(map_dir) / 'v2'
        world = json.loads((root / 'world.json').read_text())
        b = world['bounds']
        self.bounds = (b['minX'], b['minY'], b['maxX'], b['maxY'])
        ter = world['terrain']
        self.ox, self.oy, self.step, self.nx, self.ny = ter['minX'], ter['minY'], ter['step'], ter['nx'], ter['ny']
        self.h = array.array('h')
        self.h.frombytes((root / 'terrain.i16').read_bytes())
        mech = (config or {}).get('mech', {})
        self.radius, self.height = float(mech.get('radius', 2.5)), float(mech.get('height', 9))
        self.climb_height = None
        self.handle = True
        self.error = None
        self.prisms = []
        for solid in world.get('prisms', ()):
            rings = []
            for coords in (solid['ring'], *solid.get('holes', ())):
                if len(coords) >= 6 and len(coords) % 2 == 0:
                    rings.append([(coords[i], coords[i+1]) for i in range(0, len(coords), 2)])
            if rings:
                base, top = solid['base'], solid['top']
                if flat:
                    # Flattened lab: each solid keeps its height above the local ground.
                    ring = rings[0]
                    floor = min(self._terrain(*q) for q in ring)
                    base, top = base-floor, top-floor
                self.prisms.append(Prism(base, top, rings))
        self.flat = flat
        self.bins = {}
        for k, p in enumerate(self.prisms):
            for j in range(int((p.b-self.bounds[1])//BIN), int((p.t-self.bounds[1])//BIN)+1):
                for i in range(int((p.l-self.bounds[0])//BIN), int((p.r-self.bounds[0])//BIN)+1):
                    self.bins.setdefault((i, j), []).append(k)
        self.window = window or self.bounds
        self._cover, self._free, self._routes = {}, {}, {}

    # -- terrain and columns ------------------------------------------------
    def ground(self, x, y):
        return 0. if self.flat else self._terrain(x, y)

    def _terrain(self, x, y):
        u = min(max((x-self.ox)/self.step, 0.), self.nx-1.)
        v = min(max((y-self.oy)/self.step, 0.), self.ny-1.)
        i, j = min(int(u), self.nx-2), min(int(v), self.ny-2)
        k = j*self.nx + i
        u, v = u-i, v-j
        h = self.h
        return .01*((1-v)*(h[k] + u*(h[k+1]-h[k])) + v*(h[k+self.nx] + u*(h[k+self.nx+1]-h[k+self.nx])))

    def surface(self, x, y, z_hint=None):
        return self.ground(x, y)

    def set_body(self, radius, height):
        if radius > 0 and height > 0:
            self.radius, self.height = radius, height

    def _blocked_column(self, x, y, feet, height=None):
        height = self.height if height is None else height
        key = (int((x-self.bounds[0])//BIN), int((y-self.bounds[1])//BIN))
        for k in self.bins.get(key, ()):
            p = self.prisms[k]
            if p.l <= x <= p.r and p.b <= y <= p.t and p.top > feet+.07 and p.base < feet+height-.03 and _inside(x, y, p.rings):
                return True
        return False

    def fits(self, x, y, radius=None):
        radius = self.radius if radius is None else radius
        l, b, r, t = self.bounds
        if not (l+radius <= x <= r-radius and b+radius <= y <= t-radius):
            return False
        feet = self.ground(x, y)
        if self._blocked_column(x, y, feet):
            return False
        for dx, dy in DIRS:
            n = math.hypot(dx, dy)
            if self._blocked_column(x + radius*dx/n, y + radius*dy/n, feet):
                return False
        return True

    def walkable(self, x, y, z=None):
        return self.fits(x, y)

    def can_move(self, pos, dest, radius=None):
        x, y = pos[0], pos[1]
        u, v = dest[0], dest[1]
        n = max(1, int(math.ceil(math.hypot(u-x, v-y)/1.)))
        for i in range(1, n+1):
            s = i/n
            if not self.fits(x+(u-x)*s, y+(v-y)*s, radius):
                return False
        return True

    # -- sight ----------------------------------------------------------------
    def clear(self, a, b):
        x, y, z = a[0], a[1], a[2]
        dx, dy, dz = b[0]-x, b[1]-y, b[2]-z
        l0, b0 = self.bounds[0], self.bounds[1]
        i0, i1 = int((min(x, b[0])-l0)//BIN), int((max(x, b[0])-l0)//BIN)
        j0, j1 = int((min(y, b[1])-b0)//BIN), int((max(y, b[1])-b0)//BIN)
        seen = set()
        for j in range(j0, j1+1):
            for i in range(i0, i1+1):
                for k in self.bins.get((i, j), ()):
                    if k in seen:
                        continue
                    seen.add(k)
                    p = self.prisms[k]
                    lo, hi = 0., 1.
                    ok = True
                    for q, d, a_, h_ in ((z, dz, p.base, p.top), (x, dx, p.l, p.r), (y, dy, p.b, p.t)):
                        if abs(d) < 1e-10:
                            if not a_ <= q <= h_:
                                ok = False
                                break
                            continue
                        m, n_ = (a_-q)/d, (h_-q)/d
                        if m > n_:
                            m, n_ = n_, m
                        lo, hi = max(lo, m), min(hi, n_)
                        if lo > hi:
                            ok = False
                            break
                    if not ok:
                        continue
                    ax, ay, ex, ey = x+dx*lo, y+dy*lo, x+dx*hi, y+dy*hi
                    if _inside(ax, ay, p.rings) or _inside(ex, ey, p.rings):
                        return False
                    for ring in p.rings:
                        cx, cy = ring[-1]
                        for ux, uy in ring:
                            if _segments_meet(ax, ay, ex, ey, cx, cy, ux, uy):
                                return False
                            cx, cy = ux, uy
        n = 0 if self.flat else max(1, int(math.ceil(max(abs(dx), abs(dy))/2.)))
        for k in range(1, n):
            s = k/n
            if z+dz*s < self.ground(x+dx*s, y+dy*s) - .015:
                return False
        return True

    # -- cover and routing ------------------------------------------------------
    def _node(self, x, y):
        return (int((x-self.bounds[0])//STRIDE), int((y-self.bounds[1])//STRIDE))

    def _center(self, n):
        return (self.bounds[0] + (n[0]+.5)*STRIDE, self.bounds[1] + (n[1]+.5)*STRIDE)

    def _node_free(self, n):
        v = self._free.get(n)
        if v is None:
            x, y = self._center(n)
            l, b, r, t = self.window
            v = self._free[n] = l <= x <= r and b <= y <= t and self.fits(x, y, self.radius+.62)
        return v

    def cover(self, x, y, z=None):
        n = self._node(x, y)
        v = self._cover.get(n)
        if v is None:
            cx, cy = self._center(n)
            feet = self.ground(cx, cy)
            walls = 0
            for dx, dy in DIRS:
                for f in (1.5, 3., 5.):
                    if self._blocked_column(cx+STRIDE*f*dx, cy+STRIDE*f*dy, feet+2., 1.):
                        walls += 1
                        break
            exits = sum(self._node_free((n[0]+dx, n[1]+dy)) for dx, dy in DIRS)
            v = self._cover[n] = min(1., walls/5.) * (.4 if exits < 3 else 1.)
        return v

    def route(self, start, goal, threats=(), limit=9000):
        """Threat-weighted A* between 4 m nodes; returns a node list or None."""
        if not self._node_free(goal):
            return None
        g = self._center(goal)
        h = lambda n: math.hypot(*(a-b for a, b in zip(self._center(n), g)))
        cost = {start: 0.}
        parent = {start: None}
        heap = [(h(start), start)]
        best = start
        expanded = 0
        while heap and expanded < limit:
            f, n = heapq.heappop(heap)
            if n == goal:
                best = n
                break
            if f > cost[n] + h(n)*1.14 + .01:
                continue
            if h(n) < h(best):
                best = n
            expanded += 1
            for dx, dy in DIRS:
                m = (n[0]+dx, n[1]+dy)
                if not self._node_free(m):
                    continue
                if dx and dy and not (self._node_free((n[0]+dx, n[1])) and self._node_free((n[0], n[1]+dy))):
                    continue
                x, y = self._center(m)
                risk = 0.
                for tx, ty, w in threats:
                    d2 = (x-tx)**2 + (y-ty)**2
                    if d2 < 170*170:
                        risk += w*1450/(700+d2)*(1-.48*self.cover(x, y))
                c = cost[n] + STRIDE*math.hypot(dx, dy)*(1+min(4., risk))
                if c < cost.get(m, 1e30):
                    cost[m] = c
                    parent[m] = n
                    heapq.heappush(heap, (c + 1.14*h(m), m))
        if best == start and start != goal:
            return None
        path = []
        while best is not None:
            path.append(best)
            best = parent[best]
        return path[::-1]

    def waypoint(self, pos, goal, threats=()):
        self.climb_height = None
        x, y = pos[0], pos[1]
        if math.hypot(goal[0]-x, goal[1]-y) < 22 and self.can_move(pos, goal):
            return goal[0], goal[1]
        start, end = self._node(x, y), self._node(goal[0], goal[1])
        if not self._node_free(end):
            for r in range(1, 4):
                ring = [(end[0]+i, end[1]+j) for i in range(-r, r+1) for j in range(-r, r+1)
                        if max(abs(i), abs(j)) == r and self._node_free((end[0]+i, end[1]+j))]
                if ring:
                    end = min(ring, key=lambda n: math.hypot(*(a-b for a, b in zip(self._center(n), goal[:2]))))
                    break
        key = id(self)
        cached = self._routes.get(key)
        tq = tuple((round(t[0]/26), round(t[1]/26)) for t in threats[:4])
        if not cached or cached[0] != end or cached[2] != tq or start not in cached[1]:
            path = self.route(start, end, [tuple(t[:3]) for t in threats[:4]])
            if not path:
                return goal[0], goal[1]
            self._routes[key] = cached = (end, path, tq)
        path = cached[1]
        k = path.index(start)
        chosen = path[min(k+1, len(path)-1)]
        for m in path[k+1:k+7]:
            if self.can_move(pos, self._center(m) + (0.,)):
                chosen = m
        if chosen == path[-1] and self.can_move(pos, goal):
            return goal[0], goal[1]
        return self._center(chosen)
