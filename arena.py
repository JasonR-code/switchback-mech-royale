"""Static Mech Royale map and short, persistent routes through it.

geometry.so is built from geometry.cpp. Python owns JSON decoding and lifetime.
A missing/unreadable map degrades to bounded open-space steering.
"""
import ctypes as ct
import json
import math
from pathlib import Path

D, I, H, V = ct.c_double, ct.c_int, ct.c_int16, ct.c_void_p
DP, IP, HP = ct.POINTER(D), ct.POINTER(I), ct.POINTER(H)


def _library():
    lib = ct.CDLL(str(Path(__file__).with_name("geometry.so")))
    signatures = {
        "new": (V, [DP, HP, I, I]),
        "free": (None, [V]),
        "prism": (None, [V, D, D, DP, IP, I]),
        "build": (None, [V]),
        "ground": (D, [V, D, D]),
        "surface": (D, [V, D, D, D]),
        "fits": (I, [V, D, D, D]),
        "move": (I, [V, D, D, D, D, D, D]),
        "clear": (I, [V, D, D, D, D, D, D]),
        "cover": (D, [V, D, D, D]),
        "waypoint": (None, [V, DP, DP, DP, I, DP]),
    }
    for name, (result, arguments) in signatures.items():
        func = getattr(lib, "ar_" + name)
        func.restype, func.argtypes = result, arguments
    return lib


class Arena:
    def __init__(self, map_dir, config=None):
        self.handle = None
        self.climb_height = None
        self.bounds = (-512.38, -333.09, 555.08, 388.64)
        mech = (config or {}).get("mech", {})
        self.radius = float(mech.get("radius", 2.5))
        self.error = None
        try:
            self.lib = _library()
            root = Path(map_dir) / "v2"
            with (root / "world.json").open() as f:
                world = json.load(f)
            bounds = world["bounds"]
            self.bounds = tuple(bounds[key] for key in ("minX", "minY", "maxX", "maxY"))
            terrain = world["terrain"]
            nx, ny = terrain["nx"], terrain["ny"]
            if nx < 2 or ny < 2 or nx * ny > 5000000:
                raise ValueError("invalid terrain size")
            samples = (H * (nx * ny)).from_buffer_copy((root / "terrain.i16").read_bytes())
            params = (D * 11)(*self.bounds, terrain["minX"], terrain["minY"], terrain["step"],
                              self.radius, mech.get("height", 9), mech.get("step_up", 1.2),
                              mech.get("max_slope_deg", 50))
            self.handle = self.lib.ar_new(params, samples, nx, ny)
            if not self.handle:
                raise MemoryError("arena allocation failed")
            for solid in world.get("prisms", ()):
                rings = [r for r in (solid["ring"], *solid.get("holes", ())) if len(r) >= 6 and len(r) % 2 == 0]
                sizes = (I * len(rings))(*(len(r) // 2 for r in rings))
                coords = (D * (sum(sizes) * 2))(*(v for ring in rings for v in ring))
                self.lib.ar_prism(self.handle, solid["base"], solid["top"], coords, sizes, len(rings))
            self.lib.ar_build(self.handle)
        except (OSError, ValueError, TypeError, KeyError, MemoryError) as ex:
            self.close()
            self.error = str(ex)

    def close(self):
        if self.handle:
            self.lib.ar_free(self.handle)
            self.handle = None

    def __del__(self):
        self.close()

    def ground(self, x, y):
        return self.lib.ar_ground(self.handle, x, y) if self.handle else 0.0

    def surface(self, x, y, z_hint):
        return self.lib.ar_surface(self.handle, x, y, z_hint) if self.handle else 0.0

    def clear(self, a, b):
        if self.handle:
            return bool(self.lib.ar_clear(self.handle, *a[:3], *b[:3]))
        return True

    def walkable(self, x, y, z=None):
        if self.handle:
            feet = self.ground(x, y) if z is None else z
            return bool(self.lib.ar_fits(self.handle, x, y, feet))
        l, b, r, t = self.bounds
        return l + self.radius <= x <= r - self.radius and b + self.radius <= y <= t - self.radius

    def can_move(self, pos, dest, radius=None):
        if self.handle:
            return bool(self.lib.ar_move(self.handle, *pos[:3], *dest[:2], self.radius if radius is None else radius))
        return self.walkable(*dest[:2])

    def cover(self, x, y, z):
        return self.lib.ar_cover(self.handle, x, y, z) if self.handle else 0.0

    def waypoint(self, pos, goal, threats=()):
        self.climb_height = None
        if not self.handle:
            return tuple(goal[:2])
        values = [float(v) for threat in threats[:4] for v in threat[:3]]
        inputs = (D * len(values))(*values)
        result = (D * 3)()
        end = (*goal[:2], goal[2] if len(goal) > 2 else self.ground(*goal[:2]))
        self.lib.ar_waypoint(self.handle, (D * 3)(*pos[:3]), (D * 3)(*end), inputs, len(values)//3, result)
        if result[2] > -1e5:
            self.climb_height = result[2]
        return result[0], result[1]
