"""Shared helper for the map-lab probes."""
import heapq
import math

from pyarena import DIRS


def safe_node(A, pos, shooters, limit=48.):
    start = A._node(*pos[:2])
    dist = {start: 0.}
    heap = [(0., start)]
    while heap:
        d, nd = heapq.heappop(heap)
        if d > dist[nd] or d > limit:
            continue
        x, y = A._center(nd)
        if all(not A.clear((s[0], s[1], 7.), (x, y, 5.)) for s in shooters):
            return d, (x, y)
        for dx, dy in DIRS:
            m = (nd[0]+dx, nd[1]+dy)
            if A._node_free(m):
                nd2 = d + 4*math.hypot(dx, dy)
                if nd2 < dist.get(m, 1e30):
                    dist[m] = nd2
                    heapq.heappush(heap, (nd2, m))
    return None, None
