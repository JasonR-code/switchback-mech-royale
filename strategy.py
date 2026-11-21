"""Strategic decisions using observed contacts, resources, map geometry and the announced ring."""
from math import atan2, cos, exp, hypot, pi, sin
from random import Random


def distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def above(p, height):
    return (p[0], p[1], p[2] + height)


def future_circle(zone, t, horizon):
    c, r = zone["center"], zone["radius"]
    n, nr = zone.get("next_center", c), zone.get("next_radius", r)
    start = max(t, zone.get("shrink_start", t))
    end = max(start, zone.get("shrink_end", start))
    frac = clip((t + horizon - start) / max(.01, end - start))
    return (c[0] + (n[0]-c[0])*frac, c[1] + (n[1]-c[1])*frac), r + (nr-r)*frac


class Strategy:
    def __init__(self, config, seed):
        self.config = config
        self.phase = Random(seed).random() * 2 * pi
        self.items = {}
        self.tracks = {}
        self.visited = {}
        self.last_goal = None
        self.next_plan = -1
        self.last_flags = None
        self.last_attacked = -1e4
        self.last_contact = -1e4
        self.bearing = None
        self.bearing_time = -1e4
        self.swap_time = -1e4
        self.upgrades = {u["id"]: u for u in config.get("upgrades", [])}

    def _remember(self, obs):
        t, me = obs["t"], obs["self"]
        pos = me["pos"]
        cell = (round(pos[0]/35), round(pos[1]/35))
        self.visited[cell] = t
        if len(self.visited) > 256:
            self.visited = {key: when for key, when in self.visited.items() if t-when < 80}
        seen = set()
        for kind in ("pickups", "cubes", "crates"):
            for item in obs.get(kind, ()):
                ident = item["id"]
                self.items[ident] = (kind, item, t)
                seen.add(ident)
        for ident, (kind, item, when) in tuple(self.items.items()):
            # Reaching an empty pickup site invalidates the remembered item regardless of facing.
            near = distance(item["pos"], pos) < 9 and abs(item["pos"][2]-pos[2]) < 5
            if ident not in seen and (near or t-when > (80 if kind == "pickups" else 35)):
                del self.items[ident]
        for event in obs.get("events", ()):
            typ = event.get("type")
            if typ == "kill":
                self.tracks.pop(event.get("target"), None)
            elif typ in ("took", "take_failed") and (typ == "took" or event.get("reason") == "gone"):
                self.items.pop(event.get("id"), None)
                if typ == "took":
                    self.swap_time = t
            if typ in ("damaged", "hit"):
                self.last_contact = t
            if typ == "damaged" and event.get("weapon") != "zone":
                self.last_attacked = t
                if event.get("bearing") is not None:
                    self.bearing, self.bearing_time = event["bearing"], t

    def _perceive(self, obs, arena):
        t, me = obs["t"], obs["self"]
        p = me["pos"]
        eye = above(p, me["stats"].get("eye_height", 8))
        enemies = [m for m in obs.get("mechs", ()) if m.get("kind") == "mech" and m["id"] != me.get("id")]
        enemies.sort(key=lambda m: distance(p, m["pos"]))
        known = set()
        contacts = []
        for i, enemy in enumerate(enemies):
            ep = enemy["pos"]
            d = distance(p, ep)
            # The server continues to report a tracked mech's true position behind a wall.
            height = self.config.get("mech", {}).get("height", 9) * (1 + self.config.get("cubes", {}).get("size_per_cube", .05) * enemy.get("cubes", 0))
            los = i < 6 and arena.clear(above(ep, height * .77), eye)
            aim = enemy.get("aim", (0, 0))[0]
            facing = cos(aim - atan2(p[1]-ep[1], p[0]-ep[0]))
            danger = (.28 + .72 * clip(1-d/200)) * (.65+.35*clip((facing+.4)/1.4))
            if "lightning" in enemy.get("weapons", ()) and d < 47:
                danger += .24
            if enemy.get("charging") and facing > .95:
                danger += .20
            if not los:
                danger *= .27 if d < 100 else .14
            known.add(enemy["id"])
            self.tracks[enemy["id"]] = (ep, t, danger, height*.77)
            contacts.append((danger, ep, height*.77, los, enemy))
        for ident, (ep, when, danger, h) in tuple(self.tracks.items()):
            if t-when > 11:
                del self.tracks[ident]
            elif ident not in known:
                contacts.append((min(.30, danger)*exp((when-t)/4), ep, h, False, None))
        contacts.sort(key=lambda a: -a[0])
        strength = sum(a[0] for a in contacts[:4])
        damaged = clip(1 - (t-self.last_attacked)/4)
        sound = max(obs.get("sounds", ()), key=self._sound_strength, default=None)
        acoustics = self._sound_strength(sound) if sound else 0
        if acoustics > 0 and t-self.last_attacked > 1 and (acoustics >= .10 or t-self.bearing_time > 2):
            self.bearing, self.bearing_time = sound["bearing"], t - sound.get("age", 0)
        pressure = clip(.72 * strength + .26 * damaged + acoustics * (.45 if strength else 1))
        return contacts[:4], pressure

    @staticmethod
    def _sound_strength(sound):
        if sound.get("bearing") is None or sound.get("kind") in ("death", "crate", "drop", "npc_gun"):
            return 0
        return {"near": .17, "mid": .075, "far": .022}.get(sound.get("dist"), 0) * clip(1-sound.get("age", 0)/2)

    def _weapon_values(self, obs, contacts):
        me = obs["self"]
        weapons = self.config.get("weapons", {})
        ring = obs["zone"]["radius"]
        nearby = any(a[3] and distance(me["pos"], a[1]) < weapons.get("lightning", {}).get("range", 45)+10 for a in contacts)
        # Values represent the benefit of filling the secondary slot. Two weapons share a torso.
        values = {"gun": 67, "lightning": 77 + 15*nearby + 20*(ring < 65),
                  "laser": 80 + 6*(ring > 110), "mortar": 71}
        for _, ep, _, _, en in contacts[:2]:
            if en:
                kinds = en.get("weapons", ())
                if "laser" in kinds:
                    values["mortar"] -= 10
                    values["lightning"] += 4
                if "mortar" in kinds:
                    values["laser"] += 6
        for skill in me.get("upgrades", ()):
            if isinstance(skill, str) and skill.split("_")[0] in values:
                values[skill.split("_")[0]] += 3
        return values

    @staticmethod
    def _weapon_gain(kind, slots, values, may_swap):
        held = [w.get("kind") if w else None for w in slots]
        if kind not in values or kind in held:
            return 0, None
        if None in held:
            return values[kind], None
        if not may_swap:
            return 0, None
        candidates = []
        for i, current in enumerate(held):
            if current == "laser" and slots[i].get("charge", 0) > 0:
                continue
            # The arm gun can fire alongside an aimed special, has no energy cost,
            # and supplies continuous ranged fire while a special cycles.
            keep = values.get(current, 0) + (46 if current == "gun" and values["lightning"] < 95 else 20 if current == "gun" else 0)
            candidates.append((values[kind] - keep - 6, i))
        return max(candidates, default=(0, None))

    def _actions(self, obs, values, pressure):
        me, t = obs["self"], obs["t"]
        slots = (list(me.get("weapons", ())) + [None, None])[:2]
        reach = self.config.get("loot", {}).get("pickup_radius", 4)
        best = (0, None, None)
        for item in obs.get("pickups", ()):
            if distance(item["pos"], me["pos"]) <= reach and abs(item["pos"][2]-me["pos"][2]) <= 4:
                gain, slot = self._weapon_gain(item.get("kind"), slots, values, t-self.swap_time > 5)
                if gain > best[0]:
                    best = (gain, item["id"], slot)
        act = {}
        if best[1] is not None:
            act["take"] = best[1]
            if best[2] is not None:
                act["drop"] = best[2]
        offer = obs.get("offer") or {}
        choices = offer.get("choices", ())
        if choices:
            held = {s.get("kind") for s in slots if s}
            hp = me["hp"]/max(1, me["max_hp"])
            late = obs["zone"]["radius"] < 70
            # Sustained unupgraded gun DPS is limited by its 2.4 s reload.
            scores = {"plating": 87 + 4*late, "armor": 71 + 10*me["stats"].get("armor", 0),
                      "nanites": 94-24*late+5*(1-hp), "servos": 80, "gun_damage": 73,
                      "gun_mag": 85-7*late, "gun_rate": 61, "gun_velocity": 63-12*late,
                      "lightning_range": 88, "lightning_efficiency": 76, "lightning_chain": 50,
                      "laser_damage": 79, "laser_charge": 74, "laser_pierce": 36,
                      "mortar_reload": 74, "mortar_velocity": 70, "mortar_splash": 75,
                      "jets": 63, "reactor": 58, "capacitor": 55, "gyros": 43, "sensors": 45}
            def utility(choice):
                name = choice.get("id", "")
                u = self.upgrades.get(name, {})
                if u.get("requires") and u["requires"] not in held:
                    return -1
                return scores.get(name, 25)
            act["pick"] = max(range(min(3, len(choices))), key=lambda i: utility(choices[i]))
        return act, slots

    def _select(self, obs, arena, contacts, pressure, values, slots, urgent, escape, recover, center, radius):
        me, t, zone = obs["self"], obs["t"], obs["zone"]
        p, hp, count = me["pos"], me["hp"]/max(1, me["max_hp"]), me.get("cubes", 0)
        speed = max(2, me["stats"].get("walk_speed", 11.7))
        nc, nr = zone.get("next_center", center), zone.get("next_radius", radius)
        armor_cap = self.config.get("cubes", {}).get("stat_cap", 10)
        shield = me["stats"].get("height", self.config.get("mech", {}).get("height", 9)) * .6
        best, winner = -float("inf"), None
        lo_x, lo_y, hi_x, hi_y = arena.bounds
        existing = self.last_goal
        active = [(a, ep, h) for a, ep, h, _, _ in contacts[:2] if a > .08]
        scout = not contacts and not recover and count < armor_cap and nr > 35
        prefer = self.phase + round(t/9) * 2.4
        if escape and contacts:
            ep = contacts[0][1]
            prefer = atan2(p[1]-ep[1], p[0]-ep[0])
        primary = next((a for a in contacts if a[3]), None)
        open_fight = bool(primary and not escape and not recover)
        has_arc = any(w and w.get("kind") == "lightning" for w in slots)

        def consider(key, point, base, category, focus=None, ring=0):
            nonlocal best, winner
            x, y, z = point
            if not lo_x <= x <= hi_x or not lo_y <= y <= hi_y:
                return
            if not arena.walkable(x, y, z):
                return
            d = distance(point, p)
            height_change = max(0, z - max(arena.ground(x, y), p[2]) - 2)
            if height_change > min(48, 3 + me.get("energy", 100)*.49):
                return
            travel = d / speed * 1.26 + height_change / 7
            arrive = travel + (ring and self.config.get("drops", {}).get("capture_s", 4) or 0)
            c, r = future_circle(zone, t, max(5, arrive + 5))
            margin = min(18, r*.24)
            overshoot = max(0, distance(point,c) - max(0, r - margin))
            nxt_excess = max(0, distance(point, nc)-max(0, nr-min(14, nr*.2)))
            score = base - .19*d - height_change*.48
            score -= overshoot * (2.0 + zone.get("dps",20)/100)
            score -= nxt_excess * (.58 if urgent else .065)
            if urgent:
                score -= max(0, distance(point, center) - max(0, radius - min(12,radius*.2))) * 3
            cover = arena.cover(x,y,z)
            score += cover * (10 + 11*pressure + 10*recover)
            if active:
                body = above(point, shield)
                for weight, ep, h in active:
                    near = distance(point, ep)
                    exposed = arena.clear(above(ep,h), body)
                    if escape or recover or category in ("loot", "capture"):
                        score -= weight * (31*exposed + max(0,80-near)*.52 + (28*exposed if recover else 0))
                    elif open_fight:
                        # Select an angle on the isolated enemy while keeping a second
                        # enemy behind geometry. Legs can strafe independently of the aim.
                        if ep is primary[1]:
                            preferred_range = 33 if has_arc and hp > .72 else 75
                            score -= max(0, abs(near-preferred_range)-22)*.27
                            if category == "anchor" and exposed:
                                score += 7
                        else:
                            score -= weight * (16*exposed + max(0,45-near)*.42)
            if category == "anchor" and scout:
                seen = self.visited.get((round(x/35), round(y/35)), -1000)
                score += 13 * clip((t-seen)/35)
                score += 3 * cos(atan2(y-p[1],x-p[0])-prefer)
            if existing and existing[0] == key and distance(point, existing[1]) < 7:
                score += 5
            if score > best:
                best, winner = score, (key, point, category, focus, ring)

        def ground_anchor(key, x, y, base=0):
            x, y = clip(x,lo_x+1,hi_x-1), clip(y,lo_y+1,hi_y-1)
            z = arena.surface(x, y, p[2]) if hasattr(arena, "surface") else arena.ground(x,y)
            if urgent and not arena.walkable(x,y,z) and hasattr(arena, "surface"):
                # A zero-radius endpoint may be on a building. Ground and roof share x/y.
                z = arena.surface(x, y, p[2] + min(45, 3 + me.get("energy",100)*.49))
            consider(key, (x,y,z), base, "anchor")

        # At the last point the ring can deal more than one cube's heal every
        # quarter second. Stop trading meters of final-zone error for loot value.
        if nr <= .01 and (zone["radius"] < 5 or t >= zone.get("shrink_end",t+60)-2):
            ground_anchor("center", nc[0], nc[1], 0)
            if winner:
                return winner
            # If the exact point is inaccessible at this elevation, find a small
            # nearby legal refuge before considering longer-range alternatives.
            for offset in (2, 4, 7, 12):
                for j in range(8):
                    a = j*pi/4
                    ground_anchor(("final", offset, j), nc[0]+offset*cos(a), nc[1]+offset*sin(a))
                if winner:
                    return winner

        consider("here", p, 3 if recover else 0, "anchor")
        if existing and existing[2] == "anchor" and distance(p, existing[1]) > 6:
            consider("previous", existing[1], 4, "anchor")

        # Rotate each search around the most useful direction. Both short and long cover
        # options matter when the pursuer is about to round a corner.
        direction = atan2(nc[1]-p[1], nc[0]-p[0]) if urgent else prefer
        for n in (12 if escape or urgent else 8, 39 if escape or urgent else 44):
            for j in range(8):
                a = direction + j*pi/4
                ground_anchor(("local", n, j), p[0]+n*cos(a), p[1]+n*sin(a))
        if urgent or distance(p,nc) > nr*.65:
            a = atan2(p[1]-nc[1],p[0]-nc[0])
            # Nearest quiet flank in the destination ring can be much closer than its center.
            annulus = max(0, min(nr*.68, nr - 16))
            for k, off in enumerate((0, .62, -.62)):
                ground_anchor(("zone", k), nc[0]+annulus*cos(a+off), nc[1]+annulus*sin(a+off), 4 if urgent else 0)
            ground_anchor("center", nc[0], nc[1], 5 if nr < 7 else 0)
        if radius < 19:
            ground_anchor("current-center", center[0], center[1])
        threshold = self.config.get("cubes", {}).get("upgrade_thresholds", (1,3,6,10,15,21))
        next_offer = next((n for n in threshold if n > count), 10000)
        cube_value = 45 if count < armor_cap else 7
        if next_offer == count+1:
            cube_value += 12
        def item_rank(entry):
            return distance(p, entry[1]["pos"]) + max(0, t-entry[2])*.7
        # Keep planning cost independent of how many objects were seen earlier in the match.
        for group in ("pickups", "cubes", "crates"):
            choices = sorted((v for v in self.items.values() if v[0]==group), key=item_rank)
            used = 0
            for _, item, when in choices:
                ep = item["pos"]
                d = distance(p,ep)
                if group == "pickups":
                    gain, _ = self._weapon_gain(item.get("kind"), slots, values, t-self.swap_time>5)
                    if gain <= 0:
                        continue
                    base = gain*.82
                elif group == "cubes":
                    cluster = sum(distance(ep, other[1]["pos"]) < 8 for other in choices[:12])
                    base = cube_value + min(2, cluster-1)*10
                else:
                    if recover or escape or count >= armor_cap:
                        continue
                    base = 25 + (12 if None in slots else 0) + 7*(next_offer == count+1)
                base -= d*.16 + min(16, (t-when)*.40) + pressure*(27 if group == "crates" else 12)
                if escape:
                    base -= 39*min(1,d/30)
                if recover and d > 10:
                    base -= 24
                consider(item["id"], ep, base, "loot", item["id"] if group=="crates" else None)
                used += 1
                if used == 4:
                    break

        if not recover and not escape and not urgent and count < armor_cap and pressure < .4:
            drones = sorted((m for m in obs.get("mechs", ()) if m.get("kind") == "npc"),
                            key=lambda m: distance(p, m["pos"]))
            for drone in drones[:2]:
                d = distance(p,drone["pos"])
                base = 34 - .20*d - pressure*48
                if drone.get("hp",350) < 150:
                    base += 10
                consider(drone["id"], drone["pos"], base, "loot", drone["id"])
        for drop in obs.get("drops", ()):
            ep = drop["pos"]
            d = distance(p,ep)
            ring = drop.get("radius",8)
            capture = drop.get("capture_s",4)
            mine = drop.get("holder") == me.get("id", -1)
            progress = drop.get("progress",0) if mine else 0
            remaining = max(0,capture-progress)
            # A mech already inside the ring freezes the capture. A rival closer than
            # we are can reach it before the clock finishes even if it is empty now.
            if any(distance(ep,c[1]) < ring+3 and c[4] for c in contacts):
                continue
            contest = any(distance(ep,c[1]) < min(72, d+ring+remaining*6) for c in contacts)
            weight = 90 + (1-hp)*43 + (10 if count<armor_cap else -22)
            if contest:
                weight -= 67
            wait = max(0, drop.get("lands_in",0)-d/speed)
            weight += 13*progress - wait*2.9 - pressure*(14 + 25*remaining/max(.1,capture)) - .12*d
            consider(drop["id"], ep, weight, "capture", ring=ring)
        if winner is None:
            winner = ("fallback", (nc[0], nc[1], arena.ground(*nc)), "anchor", None, 0)
        return winner

    def plan(self, obs, arena):
        me, t = obs["self"], obs["t"]
        p, zone = me["pos"], obs["zone"]
        self._remember(obs)
        contacts, pressure = self._perceive(obs, arena)
        hp = me["hp"]/max(1,me["max_hp"])
        visible = [c for c in contacts if c[3]]
        # A lone exposed opponent is a reasonable fight at high HP. Escalate
        # to retreat sooner when a second firing angle or an HP deficit appears.
        escape = bool((pressure > .82 and (len(visible)>1 or hp<.65)) or
                      (hp < .50 and pressure > .26) or
                      (len(visible)>1 and hp < .7 and pressure > .55))
        recover = hp < .85 and not visible
        speed = max(2, me["stats"].get("walk_speed",11.7))
        center, radius = future_circle(zone,t,8)
        next_c = zone.get("next_center",center)
        next_r = zone.get("next_radius",radius)
        excess = max(0,distance(p,next_c) - max(0,next_r-min(15,next_r*.25)))
        available = max(0,zone.get("shrink_end",t+60)-t)
        urgent = (not me.get("in_zone",True) or
                  distance(p,center) > radius - min(11, radius*.28) or
                  (excess > 3 and excess/speed*1.5+5 > available))
        values = self._weapon_values(obs, contacts)
        actions, slots = self._actions(obs, values, pressure)
        flags = (escape, recover, urgent, len(visible)>1, tuple(s and s["kind"] for s in slots))
        invalid = False
        if self.last_goal:
            key, _, category, _, _ = self.last_goal
            if category == "capture":
                invalid = not any(d["id"] == key for d in obs.get("drops", ()))
            elif category == "loot" and key not in self.items:
                invalid = not any(m["id"] == key for m in obs.get("mechs", ()))
        if t >= self.next_plan or flags != self.last_flags or invalid or not self.last_goal:
            self.last_goal = self._select(obs, arena, contacts, pressure, values, slots,
                                          urgent, escape, recover, center, radius)
            self.next_plan = t + (.47 if contacts or urgent else .83)
            self.last_flags = flags
        _, goal, category, focus, ring = self.last_goal
        if visible and (pressure>.32 or focus is None):
            def target_score(c):
                e = c[4]
                # Prefer finishing a pursuer to spreading damage across the squad.
                return c[0] + .55*(1-e.get("hp",1000)/max(1,e.get("max_hp",1000))) - distance(p,c[1])*.0008
            focus = max(visible,key=target_score)[4]["id"]
        if contacts and t-self.bearing_time > 1:
            ep = contacts[0][1]
            scan = atan2(ep[1]-p[1], ep[0]-p[0])
        elif self.bearing is not None and t-self.bearing_time < 2.5:
            scan = self.bearing
        else:
            # A complete turn observes loot behind spawn and refreshes the FOV while holding.
            scan = self.phase + t*1.42
        return {"goal":goal, "pressure":pressure, "focus":focus, "escape":escape, "scan":atan2(sin(scan),cos(scan)),
                "urgent":urgent, "recover":recover, "hold":category == "capture" or (category=="anchor" and not visible and distance(p,goal)<4),
                "capture_radius":ring, "threats":[(ep[0],ep[1],weight) for weight,ep,_,_,_ in contacts],
                "actions":actions}
