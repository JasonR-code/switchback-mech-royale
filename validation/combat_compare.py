"""Paired comparison of two combat_lab result files (same split, same case list).

Usage: python validation/combat_compare.py baseline.json candidate.json
"""
import json
import random
import statistics
import sys
from collections import defaultdict


def bootstrap(diffs, n=4000, seed=5):
    r = random.Random(seed)
    means = sorted(statistics.fmean(r.choices(diffs, k=len(diffs))) for _ in range(n))
    return means[int(.025*n)], means[int(.975*n)]


def summary(rows, key):
    return sum(r[key] for r in rows)


def main():
    base, cand = (json.load(open(p)) for p in sys.argv[1:3])
    assert [r['seed'] for r in base] == [r['seed'] for r in cand], 'different case lists'
    diffs = [c['damage']-b['damage'] for b, c in zip(base, cand)]
    lo, hi = bootstrap(diffs)
    wins = sum(d > 1e-6 for d in diffs)
    losses = sum(d < -1e-6 for d in diffs)
    print(f"cases {len(diffs)}  damage base {summary(base,'damage'):.0f}  cand {summary(cand,'damage'):.0f}  "
          f"mean diff {statistics.fmean(diffs):+.1f}/case  95% CI [{lo:+.1f}, {hi:+.1f}]  wins {wins} losses {losses}")
    for name, rows in (('base', base), ('cand', cand)):
        print(f"  {name}: gun {summary(rows,'gun_hits')}/{summary(rows,'gun_shots')} "
              f"({100*summary(rows,'gun_hits')/max(1,summary(rows,'gun_shots')):.1f}%)  "
              f"laser {summary(rows,'laser_hits')}/{summary(rows,'laser_shots')} dmg {summary(rows,'laser_damage'):.0f}  "
              f"mortar {summary(rows,'mortar_damage'):.0f}/{summary(rows,'mortar_shots')}  "
              f"arc {summary(rows,'arc_hits')}/{summary(rows,'arc_shots')}  kills {summary(rows,'kills')}  "
              f"charge ticks {summary(rows,'charge_ticks')}")
    for field, bins in (('loadout', None), ('style', None), ('own', None),
                        ('dist', ((0, 50), (50, 100), (100, 150), (150, 400)))):
        groups = defaultdict(list)
        for b, c in zip(base, cand):
            if bins:
                label = next(f"{lo}-{hi}m" for lo, hi in bins if lo <= b['dist'] < hi)
            else:
                label = b[field]
            groups[label].append((b, c))
        parts = []
        for label in sorted(groups):
            pairs = groups[label]
            bh = sum(b['gun_hits'] for b, _ in pairs); bs = sum(b['gun_shots'] for b, _ in pairs)
            ch = sum(c['gun_hits'] for _, c in pairs); cs = sum(c['gun_shots'] for _, c in pairs)
            dd = statistics.fmean(c['damage']-b['damage'] for b, c in pairs)
            parts.append(f"{label}(n={len(pairs)}): dmg {dd:+.0f}, gun {100*bh/max(1,bs):.1f}->{100*ch/max(1,cs):.1f}%")
        print(f"  by {field}: " + "; ".join(parts))


if __name__ == '__main__':
    main()
