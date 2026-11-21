"""Placement-oriented Mech Royale policy. Start with python3 -u main.py."""
import json
import math
from pathlib import Path

import mechfight
from arena import Arena
from combat import Combat
from motion import Motion
from strategy import Strategy


def number(value):
    return type(value) in (int, float) and abs(value) < 1e9 and math.isfinite(value)


def numeric_fields(mapping):
    return {k: v for k, v in mapping.items() if number(v)} if isinstance(mapping, dict) else {}


def vector(value, size):
    return isinstance(value, (tuple, list)) and len(value) == size and all(number(v) for v in value)


def config_values(defaults, live):
    """Preserve new server settings and fill omitted numeric balance values."""
    if not isinstance(live, dict):
        return defaults.copy()
    result = defaults | live
    for key, value in defaults.items():
        update = live.get(key)
        if isinstance(value, dict):
            result[key] = config_values(value, update)
        elif type(value) in (int, float) and not number(update):
            result[key] = value
        elif isinstance(value, list) and not isinstance(update, list):
            result[key] = value
    return result


class Pilot:
    name = "Switchback"

    def __init__(self, hello):
        with Path(__file__).with_name("defaults.json").open() as f:
            self.config = config_values(json.load(f), hello.get("config"))
        seed = hello.get("seed", 0)
        self.slot = hello.get("slot", 0)
        self.arena = Arena((hello.get("map") or {}).get("dir", "/arena"), self.config)
        self.strategy = Strategy(self.config, seed)
        self.motion = Motion(self.config, seed)
        self.combat = Combat(self.config)

    def _observation(self, source):
        obs = source.copy()
        cfg = self.config
        me = dict(source["self"])
        obs["self"] = me
        base = cfg["mech"]
        stats = base | numeric_fields(me.get("stats"))
        me["stats"] = stats
        me["vel"] = me["vel"] if vector(me.get("vel"), 3) else (0, 0, 0)
        me["aim"] = me["aim"] if vector(me.get("aim"), 2) else (0, 0)
        for key, default in (("max_hp", stats["hp"]), ("max_energy", stats["energy"]),
                             ("hp", stats["hp"]), ("energy", stats["energy"]), ("cubes", 0),
                             ("id", self.slot)):
            if not number(me.get(key)):
                me[key] = default
        me["upgrades"] = [u for u in me["upgrades"] if isinstance(u, str)] if isinstance(me.get("upgrades"), list) else []
        me.setdefault("grounded", True)
        weapons = []
        slots = me.get("weapons")
        for weapon in slots[:2] if isinstance(slots, (list, tuple)) else []:
            if not isinstance(weapon, dict) or weapon.get("kind") not in cfg["weapons"]:
                weapons.append(None)
                continue
            kind = weapon["kind"]
            w = dict(weapon)
            w["stats"] = cfg["weapons"][kind] | numeric_fields(w.get("stats"))
            for key, default in (("cooldown", 0), ("reload", 0), ("charge", 0),
                                 ("ammo", w["stats"].get("mag", 0))):
                if not number(w.get(key)):
                    w[key] = default
            weapons.append(w)
        me["weapons"] = (weapons + [None, None])[:2]
        for key in ("mechs", "pickups", "crates", "cubes", "projectiles", "drops"):
            entries = obs.get(key)
            obs[key] = [dict(obj) for obj in entries if isinstance(obj, dict) and number(obj.get("id"))
                        and vector(obj.get("pos"), 3)] if isinstance(entries, list) else []
        obs["mechs"] = [m for m in obs["mechs"] if m.get("kind") in ("mech", "npc") and m["id"] != me["id"]]
        for actor in obs["mechs"]:
            if not vector(actor.get("vel"), 3):
                actor["vel"] = (0, 0, 0)
            if not vector(actor.get("aim"), 2):
                actor["aim"] = (0, 0)
            if not isinstance(actor.get("weapons"), (list, tuple)):
                actor["weapons"] = []
            for key in ("hp", "max_hp", "cubes"):
                if key in actor and not number(actor[key]):
                    del actor[key]
            actor["charging"] = bool(actor.get("charging"))
        for crate in obs["crates"]:
            if not number(crate.get("hp")):
                crate["hp"] = cfg["crates"]["hp"]
        obs["pickups"] = [p for p in obs["pickups"] if p.get("kind") in cfg["weapons"]]
        obs["projectiles"] = [p for p in obs["projectiles"] if vector(p.get("vel"), 3)
                              and p.get("kind") in ("gun", "npc", "mortar")]
        drops = cfg["drops"]
        for item in obs["drops"]:
            for key, default in (("radius", drops["radius"]), ("capture_s", drops["capture_s"]),
                                 ("lands_in", drops["fall_s"]), ("progress", 0)):
                if not number(item.get(key)):
                    item[key] = default
            item.setdefault("holder", None)
        obs["events"] = [e for e in (obs.get("events") or []) if isinstance(e, dict) and isinstance(e.get("type"), str)]
        for e in obs["events"]:
            if e.get("bearing") is not None and not number(e["bearing"]):
                e["bearing"] = None
        obs["sounds"] = [s for s in (obs.get("sounds") or []) if isinstance(s, dict) and number(s.get("bearing"))
                         and s.get("dist") in ("near", "mid", "far") and isinstance(s.get("kind"), str)]
        for sound in obs["sounds"]:
            if not number(sound.get("age")):
                sound["age"] = 0
        obs["beams"] = [b for b in (obs.get("beams") or []) if isinstance(b, dict) and number(b.get("by"))
                        and isinstance(b.get("path"), list) and len(b["path"]) >= 2 and all(vector(p, 3) for p in b["path"])]
        offer = obs.get("offer")
        obs["offer"] = offer if isinstance(offer, dict) and isinstance(offer.get("choices"), list) and all(
            isinstance(c, dict) and isinstance(c.get("id"), str) for c in offer["choices"]) and offer["choices"] else None
        if not number(obs.get("t")):
            obs["t"] = obs["tick"] / max(1, cfg["match"]["tick_hz"])
        if not number(obs.get("alive")):
            obs["alive"] = cfg["match"]["mechs"]
        z = dict(obs.get("zone") or {})
        if not vector(z.get("center"), 2):
            z["center"] = cfg["zone"]["start_center"]
        if not vector(z.get("next_center"), 2):
            z["next_center"] = z["center"]
        for key, value in (("radius", cfg["zone"]["start_radius"]), ("next_radius", z.get("radius")),
                           ("dps", 20), ("shrink_start", obs["t"]), ("shrink_end", obs["t"] + 60)):
            if not number(z.get(key)):
                z[key] = value if number(value) else cfg["zone"]["start_radius"]
        obs["zone"] = z
        me.setdefault("in_zone", math.dist(me["pos"][:2], z["center"]) <= z["radius"])
        return obs

    def act(self, source):
        tick = source.get("tick", 0)
        if not isinstance(source.get("self"), dict) or not vector(source["self"].get("pos"), 3):
            return {"tick": tick}
        obs = self._observation(source)
        me = obs["self"]
        self.arena.set_body(me["stats"]["radius"], me["stats"]["height"])
        intent = self.strategy.plan(obs, self.arena)
        pos, goal = obs["self"]["pos"], intent["goal"]
        if intent.get("direct_escape") and self.arena.can_move(pos, goal):
            waypoint = goal[:2]
            self.arena.climb_height = None
        else:
            waypoint = self.arena.waypoint(pos, goal, intent.get("threats", ()))
        travel = self.motion.act(obs, self.arena, waypoint, intent)
        attack = self.combat.act(obs, self.arena, intent)
        return {"tick": tick, **travel, **attack, **intent.get("actions", {})}


if __name__ == "__main__":
    mechfight.run(Pilot)
