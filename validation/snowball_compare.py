"""Paired comparison of two combat_snowball result files.

Usage: python validation/snowball_compare.py baseline.json candidate.json
"""
import json
import statistics
import sys

from combat_compare import bootstrap


def main():
    base, cand = (json.load(open(p)) for p in sys.argv[1:3])
    assert [r['seed'] for r in base] == [r['seed'] for r in cand], 'different case lists'
    first = lambda r: r['first_kill'] if r['first_kill'] is not None else 121.
    life = lambda r: r['death'] if r['death'] is not None else 120.
    eff = lambda r: r['dealt']/max(1., r['taken'])
    rows = [('opponents outlasted (=kills)', lambda r: r['kills']), ('kills <=60 s', lambda r: r['kills_60']),
            ('time to first kill (121 if none)', first), ('alive s (120 cap)', life),
            ('death before 60 s', lambda r: float(r['death_60'])), ('cubes', lambda r: r['cubes']),
            ('dealt / taken', eff), ('dealt', lambda r: r['dealt']), ('taken', lambda r: r['taken']),
            ('travel m', lambda r: r['travel']), ('wounded rivals left alive', lambda r: r['abandoned'])]
    print(f"cases {len(base)}  deaths base {sum(r['death'] is not None for r in base)} "
          f"cand {sum(r['death'] is not None for r in cand)}")
    for name, f in rows:
        diffs = [f(c)-f(b) for b, c in zip(base, cand)]
        lo, hi = bootstrap(diffs)
        print(f"  {name:32s} base {statistics.fmean(map(f, base)):8.2f} cand {statistics.fmean(map(f, cand)):8.2f} "
              f"diff {statistics.fmean(diffs):+7.2f} [{lo:+.2f}, {hi:+.2f}]  up {sum(d > 1e-9 for d in diffs)} "
              f"down {sum(d < -1e-9 for d in diffs)}")


if __name__ == '__main__':
    main()
