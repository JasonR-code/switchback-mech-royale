# Snowball V2: duel hold (branch `claude-snowball-v2`, built on `a589f8d` = official 4.85)

Gameplay change: **`strategy.py` only**, 8 added lines. `combat.py`, `motion.py`, `main.py`, `arena.py` and `defaults.json` are byte-identical to 4.85. `DUEL_EDGE = 0` restores 4.85 behaviour exactly. **No official score exists for this candidate.**

## Weakness investigated (most frequent first)

`validation/snowball_escape_probe.py` and a per-decision trace on the dev split classify why the 4.85 bot sets `escape` in the snowball lab:

- Escape is set on 53–62% of decisions.
- **About 33% of all decisions are retreats from a single engaging rival.** No second engager is present, so the crossfire rules (`len(threats)>1`, `aimed>=2`) do not fire. The trigger is almost always the HP rule `hp < .50 and pressure > .26` (25% of all decisions on its own), or `pressure > .82 and hp < .65`. These rules look only at **our** HP fraction, never at the rival's.
- In 12–14% of those lone-rival retreats, the rival had **no more absolute HP than we did**: we were leaving a duel we were ahead in.
- Regeneration needs 5 s without dealing or taking damage. A lone hunter that pursues therefore denies it, and the retreat gains nothing. In the lab, about half of all deaths came in lone duels where we were retreating for most of the last 8 s.
- Other questions from the brief:
  - Escapes with *no* engaging rival (bystanders plus low HP) were about 4% of decisions.
  - Removing bystanders from the pressure thresholds ("Q" below) added kills but cost survival when bystanders don't retaliate, so it was rejected.
  - The 8-death / 300 s cutoff: house bots never fight each other, so deaths come almost only from us and the zone. The 8-death limit is a fair proxy for the squad escalating; 300 s is when the zone radius reaches ~70 m. It was left unchanged, since the lab ends at 120 s and cannot test it.
  - Pursuing damaged rivals and kill rewards was already tested in V1 (hunting, finishing): no gain. Not repeated.

## The change

During the snowball phase, if escape was triggered **only by HP or pressure**:
- **Conditions:**
  - exactly one rival is engaging us (aim within ~25°, within 60 m, or hit us in the last 3 s);
  - that rival's absolute HP is ≤ ours (`DUEL_EDGE = 1.0`);
  - our HP is ≥ 35% (`DUEL_FLOOR = .35`).
- **Effect:** escape is cleared and we keep fighting.
- **When it stops:** the moment a second rival engages, `len(threats) == 2` and the normal crossfire rules apply again. After 8 deaths or 300 s it is off.

## Lab evidence vs 4.85 (`combat_snowball.py`, matched seeds)

**Selection on dev (80 cases × 3 settings):**

| Variant | Result |
|---|---|
| Q (bystander-free pressure) | +0.20 to +0.25 kills; survival −3.2 s (np) |
| D0.8 | +0.06 to +0.21 kills |
| **D1.0** | +0.09 to +0.26 kills; survival neutral to positive |
| D1.2 | +0.16 to +0.35 kills; survival −3.6 s (np) |

The HP floor (.15, .25, .35) made no clear difference, so the most conservative floor was kept. Only the final variant was then run on holdout and fresh.

**Holdout and fresh, 160 cases per row** (diff [95% bootstrap CI]):

| Split / setting | Kills | Kills ≤ 60 s | Deaths < 60 s | Alive (120 s cap) | Cubes |
|---|---|---|---|---|---|
| holdout ×0.5 | 2.13 → 2.24, **+0.11** [+0.01, +0.21] | **+0.14** [+0.06, +0.23] | −0.01 [−0.06, +0.05] | +0.6 s [−1.3, +2.5] | +0.14 |
| holdout ×0.5 np | 3.11 → 3.19, +0.07 [−0.04, +0.19] | **+0.11** [+0.02, +0.20] | +0.03 [−0.03, +0.08] | +0.0 s | +0.08 |
| holdout ×0.3 | 3.17 → 3.40, **+0.23** [+0.11, +0.36] | **+0.12** | −0.02 [−0.06, +0.02] | **+2.8 s** [+0.4, +5.4] | **+0.42** |
| fresh ×0.5 | 2.01 → 2.11, **+0.11** [+0.01, +0.21] | +0.08 [+0.00, +0.16] | −0.02 [−0.07, +0.03] | +0.9 s | **+0.19** |
| fresh ×0.5 np | 3.09 → 3.19, +0.11 [−0.03, +0.24] | +0.09 [−0.01, +0.18] | −0.01 [−0.06, +0.05] | +0.3 s | **+0.28** |
| fresh ×0.3 | 3.16 → 3.26, +0.11 [−0.01, +0.23] | **+0.11** | **−0.05** [−0.09, −0.01] | **+2.3 s** [+0.2, +4.5] | **+0.24** |

- Kills rose in all 6 rows; 3 of the 6 kill CIs exclude zero.
- Early deaths: no row is significantly worse, and one is significantly better.
- Damage taken rose by +18 [+1, +38] in one row: we stay in more trades.
- **Decision change** (holdout ×0.5): escape fell from 53.3% to 50.0% of decisions; anchor (fight position) goals rose from 51.5% to 53.9%.
- **Crossfire check:** in `combat_squad.py --pilot` (holdout, 320 cases, every rival aims at us), results are **bit-identical** to 4.85.

## Observed vs assumed

- **Observed:** the lab metrics above, and the frequency of each escape trigger in the 4.85 code.
- **Assumed** (not measured on house bots):
  - a lone hunter keeps pursuing rather than letting us regenerate;
  - house-bot DPS is close enough to ours that comparing absolute HP predicts the duel. The rule ignores weapon mix, cubes and upgrades; a rival with a laser charging can out-trade a higher-HP gun mech.
- **On real maps:** retreat can break line of sight behind cover, which the open-field lab cannot reward. The lab may therefore overstate the cost of retreating.
- **Expected size:** about +3–7% lab kills. This is modest, not a step change; the gain may not show above official noise (4.63 repeated exactly, and 3849ea7 differed by 0.03).

## Validation run (Windows host)

- 76 tests: all pass except the 3 that need `geometry.so` (no compiler here; they fail the same way on every build).
- New `DuelHold` tests (6). With `DUEL_EDGE = 0`, the two hold tests fail as expected.
- Official `check.py`: PASS, 300/300 on time, p99 0.5 ms.
- `dense_timing.py`: p50 1.41 ms, p99 1.95 ms, 0 decisions over 50 ms.
- **Not run:** Docker build, Linux 1-CPU container, real-map geometry.

Raw results are in `validation/results/snowball_v2/` (`*_base` = a589f8d, `*_cand` = this commit, dev variants by name).
