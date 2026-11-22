"""Paired comparison of two combat_recovery result files.

Usage: python validation/recovery_compare.py baseline.json candidate.json
"""
import json
import statistics
import sys

from combat_compare import bootstrap


def main():
    base, cand = (json.load(open(p)) for p in sys.argv[1:3])
    assert [r['seed'] for r in base] == [r['seed'] for r in cand], 'different case lists'
    horizon = 40.
    life = lambda r: r['death'] if r['death'] is not None else horizon
    rows = [('alive s', life), ('end hp', lambda r: r['end_hp']), ('regen hp', lambda r: r['regen']),
            ('shots', lambda r: r['shots']), ('dealt', lambda r: r['dealt']), ('kills', lambda r: r['kills']),
            ('provoked', lambda r: r['provoked'])]
    print(f"cases {len(base)}  deaths base {sum(r['death'] is not None for r in base)} "
          f"cand {sum(r['death'] is not None for r in cand)}  "
          f"(hunter present in {sum(r['hunter'] for r in base)})")
    for name, f in rows:
        diffs = [f(c)-f(b) for b, c in zip(base, cand)]
        lo, hi = bootstrap(diffs)
        print(f"  {name:9s} base {statistics.fmean(map(f, base)):8.1f} cand {statistics.fmean(map(f, cand)):8.1f} "
              f"diff {statistics.fmean(diffs):+7.1f} [{lo:+.1f}, {hi:+.1f}]  up {sum(d > 1e-6 for d in diffs)} "
              f"down {sum(d < -1e-6 for d in diffs)}")


if __name__ == '__main__':
    main()
