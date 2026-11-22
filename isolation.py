"""Short lateral moves during an observed two-rival engagement."""
import math

from strategy import above, distance, future_circle

SPOKES = tuple((math.cos(i * math.tau/16), math.sin(i * math.tau/16)) for i in range(16))


class Isolation:
    def __init__(self):
        self.point = None
        self.pair = None
        self.next_scan = -1.
        self.until = -1.

    def choose(self, obs, arena, intent, focus, incoming):
        t, me = obs["t"], obs["self"]
        pos = me["pos"]
        if (intent["urgent"] or not me.get("grounded") or not arena.handle or
                not intent["escape"] or focus is None and (self.point is None or t >= self.until)):
            self.point = None
            return None
        target_id = focus if focus is not None else self.pair[0]
        rivals = [e for e in obs["mechs"] if e["kind"] == "mech" and e["id"] != me["id"]]
        primary = next((e for e in rivals if e["id"] == target_id), None)
        if primary is None or primary.get("hp", 0) <= 220 or len(rivals) < 2:
            self.point = None
            return None
        height = me["stats"]["height"]
        aim_at = above(primary["pos"], 4.5*(1+.05*primary.get("cubes", 0)))
        def can_shoot(point):
            return arena.clear(above(point, .77*height), aim_at)
        if not can_shoot(pos):
            self.point = None
            return None
        # Only class recent hitters or rivals tracking our bearing as secondary attackers.
        hit_now = {e.get("by") for e in obs["events"] if e.get("type") == "damaged"}
        threats = []
        for rival in rivals:
            if rival is primary:
                continue
            ep = rival["pos"]
            angle = math.atan2(pos[1]-ep[1], pos[0]-ep[0])
            recent = rival["id"] in hit_now or t-incoming.get(rival["id"], -100.) < 2.
            if not recent and math.cos(rival["aim"][0]-angle) < .96:
                continue
            muzzle = above(ep, 7*(1+.05*rival.get("cubes",0)))
            threats.append((rival,muzzle))
        body = above(pos, height*.55)
        def safe(point):
            center, radius = future_circle(obs["zone"], t, 3.5)
            return distance(point,center) < radius-3

        if self.point is not None and self.pair[0]==target_id and t < self.until:
            if (any(r["id"] == self.pair[1] and not arena.clear(m,above(self.point,height*.55))
                    for r,m in threats) and safe(self.point) and
                    arena.can_move(pos,self.point) and can_shoot(self.point)):
                return self.point
        self.point = None
        if t < self.next_scan or not threats:
            return None
        self.next_scan = t+.45
        screened = [m for _,m in threats if not arena.clear(m,body)]
        threats = [(r,m) for r,m in threats if m not in screened]
        if not threats:
            return None
        rival,muzzle = min(threats, key=lambda e:distance(e[1],pos))
        goal = intent["goal"]
        if (distance(pos,goal) <= 30 and arena.can_move(pos,goal) and
                not arena.clear(muzzle,above(goal,height*.55))):
            return None
        # Preserve a useful firing lane through arrival. Include some attacker movement
        # so the first corner a moving pursuer is about to clear scores poorly.
        center,radius = future_circle(obs["zone"],t,3.5)
        velocity = rival["vel"]
        bearing = math.atan2(primary["pos"][1]-pos[1],primary["pos"][0]-pos[0])
        cb,sb = math.cos(bearing),math.sin(bearing)
        others = [m for e,m in threats if e is not rival]
        for r in (5.,10.,16.,24.):
            future = tuple(v+min(1.,r/12)*w for v,w in zip(muzzle,velocity))
            for dx,dy in SPOKES:
                x,y = pos[0]+r*(cb*dx-sb*dy),pos[1]+r*(sb*dx+cb*dy)
                if math.hypot(x-center[0],y-center[1]) > radius-3:
                    continue
                p = (x,y,arena.surface(x,y,pos[2]))
                torso = above(p,height*.55)
                if (abs(p[2]-pos[2])>5 or arena.clear(muzzle,torso) or
                        arena.clear(future,torso) or not can_shoot(p) or
                        not arena.walkable(*p) or not arena.can_move(pos,p)):
                    continue
                if (any(distance(p,m)<distance(pos,m)-5 for m in others) or
                        any(arena.clear(m,torso) for m in screened)):
                    continue
                self.point,self.pair,self.until = p,(target_id,rival["id"]),t+min(1.5,.35+r/12)
                return p
        return None
