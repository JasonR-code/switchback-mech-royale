"""Paired comparison of two combat_squad result files.

Usage: python validation/squad_compare.py baseline.json candidate.json
"""
import json
import statistics
import sys
from collections import defaultdict

from combat_compare import bootstrap


def main():
    base, cand = (json.load(open(p)) for p in sys.argv[1:3])
    assert [r['seed'] for r in base] == [r['seed'] for r in cand], 'different case lists'
    for key, better in (('dealt', 1), ('taken', -1), ('rear', -1), ('kills', 1)):
        diffs = [c[key]-b[key] for b, c in zip(base, cand)]
        lo, hi = bootstrap(diffs)
        print(f"{key:6s} base {sum(r[key] for r in base):9.0f} cand {sum(r[key] for r in cand):9.0f} "
              f"mean diff {statistics.fmean(diffs):+8.1f} 95% CI [{lo:+.1f}, {hi:+.1f}] "
              f"better {sum(d*better > 1e-6 for d in diffs)} worse {sum(d*better < -1e-6 for d in diffs)}")
    net = [(c['dealt']-c['taken'])-(b['dealt']-b['taken']) for b, c in zip(base, cand)]
    lo, hi = bootstrap(net)
    print(f"net (dealt-taken) mean diff {statistics.fmean(net):+.1f} 95% CI [{lo:+.1f}, {hi:+.1f}]")
    if 'death' in base[0]:
        life = [(c['death'] or c['cleared'] or 20) - (b['death'] or b['cleared'] or 20) for b, c in zip(base, cand)]
        lo, hi = bootstrap(life)
        print(f"alive time mean diff {statistics.fmean(life):+.2f}s 95% CI [{lo:+.2f}, {hi:+.2f}]  "
              f"deaths base {sum(r['death'] is not None for r in base)} cand {sum(r['death'] is not None for r in cand)}  "
              f"longer {sum(x > 1e-6 for x in life)} shorter {sum(x < -1e-6 for x in life)}")
    first = [(b['first_kill'] or 21) - (c['first_kill'] or 21) for b, c in zip(base, cand)]
    print(f"first kill earlier by {statistics.fmean(first):+.2f}s on average (21 s if none)")
    for name, rows in (('base', base), ('cand', cand)):
        print(f"  {name}: gun {sum(r['gun_hits'] for r in rows)}/{sum(r['gun_shots'] for r in rows)} "
              f"laser {sum(r['laser_hits'] for r in rows)}/{sum(r['laser_shots'] for r in rows)} "
              f"cleared {sum(r['cleared'] is not None for r in rows)}")
    groups = defaultdict(list)
    for b, c in zip(base, cand):
        groups[(b['loadout'], b['rivals'])].append((b, c))
    for label in sorted(groups, key=str):
        pairs = groups[label]
        print(f"  {label}: n={len(pairs)} dealt {statistics.fmean(c['dealt']-b['dealt'] for b, c in pairs):+.0f} "
              f"taken {statistics.fmean(c['taken']-b['taken'] for b, c in pairs):+.0f} "
              f"rear {statistics.fmean(c['rear']-b['rear'] for b, c in pairs):+.0f}")


if __name__ == '__main__':
    main()
