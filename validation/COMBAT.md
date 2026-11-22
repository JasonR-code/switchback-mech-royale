# Combat candidate (branch `claude-combat`)

Baseline: `d6dc1c6` (tag `builders-practice-4.38-baseline`, official practice 4.38/15).
Only `combat.py` changes bot behaviour. No other bot file and no shared interface changed:
`Combat.act(obs, arena, intent)` keeps its signature and its return keys. **No official score exists for this candidate yet.**

## Facts measured on the public recording (`mechfight-kit/check/stream.jsonl.gz`)

1. **Cooldown ordering.** The recorded gun cooldown reads 0 → 0.19 → 0.09 → 0. The decrement happens before the trigger check, and a shot fires on the first tick whose cooldown reaches 0.
2. **Launch point.** Back-projecting newly seen enemy bullets onto their shooter fits best when the shooter has already moved one tick: residual 0.18–0.20 m, against 0.70 m for zero ticks and 0.44–1.0 m for two ticks. A bullet's age then equals exactly 0.100 s at the next observation. So within a tick, mechs move first, then the weapon fires from the post-move muzzle, and the new bullet also travels that tick.
3. **No velocity inheritance.** Bullet speed is exactly 252.0 m/s while the shooter moves at 5–19 m/s.
4. **House-bot motion.** House bot 10 strafes sideways at 5–19 m/s, reversing every 0.4–1.2 s at 90–150 m. It charges its laser for ~0.8–1.0 s while tracking within about 0.01 rad. Its laser did 1,260 of the 1,575 damage our recorded mech took in 30 s.

## Confirmed weaknesses in the 4.38 code

- **Launch timing (confirmed bug, small).** The code leads every target by a fixed half tick and ignores our own displacement before the shot. Against fact 2, a tick-1 shot over-leads the target by `v·0.025 s` and misses the shooter's own `v·0.05 s` shift. That's up to ~0.9 m of relative error against a 2.5 m target radius when both mechs strafe. Lasers and lightning are hitscan and strike at the post-move tick, so they need `k` ticks of target motion, where `k` is the fire tick.
- **Mortar against reversing targets (confirmed in the lab).** The mortar extrapolates linearly over 1–4 s shell flights. Against strafers and jinkers beyond 80 m it averaged 0 damage per shell (23 shells), against ~300 for straight or still targets.
- **Rear armor ignored (confirmed in the lab, impact uncertain).** Target choice never considers that hits from outside the 180° front arc deal 1.5×. In the lab against 2–3 surrounding rivals, rear hits were 36% of all damage taken.

Speculative, not changed: laser holds and releases a charge when its target leaves line of sight; lightning interrupts of enemy laser charges are only weighted ×1.24; long-range gun fire spends ammo and reveals us at hit chances below 0.3. The lab can't evaluate these honestly.

## Changes

1. **Tick-exact launch** (`act`). Fire tick `k` = 1 if `cooldown ≤ 0.05`, else 2 (a laser release is always tick 1). Origin = muzzle + own velocity × `k`·0.05. Target delay = (`k`−1)·0.05 for bullets and shells, `k`·0.05 for laser and lightning.
2. **Adaptive shell drift** (`DriftTrack`, `drifting`; `MORTAR_TAU = 0.6`, `DRIFT_TAU = 2.0`). Each rival's straight-line forecast and its mean-reverting forecast are scored against displacement actually observed 1 s and 2 s later. Each mortar root is then re-solved once with a velocity blended toward the better forecast. With no evidence it keeps the old linear lead, so straight and still targets are unchanged.
3. **Rear-arc exposure** (`threats`, `rear_exposure`; `REAR_WEIGHT = 0.25`, `REAR_MARGIN = 0.14`). A shot's value is divided by `1 + 0.25 × Σ danger` of rivals that the shot's yaw would leave outside the front arc. Danger is 1 for a rival aiming at us or that hit us within 2.5 s, ×2.2 when it's charging a laser, ×1.5 for lightning inside 50 m, lower when idle, distant, occluded or an NPC. It is scaled by the configured `rear_mult`, and line of sight is checked only for the 8 nearest rivals. The scores are internal; they could later be exposed to strategy as a facing hint.

## Evidence (paired, identical seeds, held-out split, vs unchanged 4.38)

The labs are local and open-field (no walls, loot, squad intelligence or dodging). They are **not** a full-match simulator and say nothing direct about placement.

| Lab (holdout) | Metric | Change 1 only | Final (1+2+3) |
|---|---|---|---|
| `combat_lab.py`, 320 duels, all loadouts | damage per 15 s | +24.5 [+16.1, +33.0] | **+30.2 [+18.8, +42.0]**, 119 wins / 50 losses |
| | gun hit rate | 85.9 → 87.3% | 85.9 → 87.3% |
| | mortar damage | +1.1% | **+4.2%** |
| `combat_squad.py`, 240 cases, combat only | dealt − taken | +27 [−14, +66] | **+86 [+28, +146]** |
| | rear damage taken | −7 (n.s.) | **−130 [−194, −71]** |
| `combat_squad.py --pilot`, 320 cases, full `main.Pilot` | damage dealt | +28 [+17, +40] | **+34 [+18, +49]** |
| | time alive | +0.04 s (n.s.) | +0.05 s [+0.01, +0.10] |

Brackets are 95% bootstrap CIs of the per-case mean difference.

**Development split, for transparency.** On dev, the rear weight at 0.5–2.0 reduced rear damage but lowered damage dealt and kills in the combat-only squad lab. That is why 0.25 was chosen rather than the more aggressive values. A fixed (non-adaptive) drift average gained against strafers but lost −100 to −257 per case against straight and circling targets, so it was replaced by the adaptive tracker.

**Regressions observed.** None significant on holdout. Damage taken in the full-pilot lab is unchanged (−3 [−9, +3]). Decision latency rises ~0.2 ms (p50 1.27 → 1.48 ms, dense 800-observation scenario, host, no-map arena).

## Validation actually run (Windows host)

- 55 existing tests plus 8 new tests in `test_combat_timing.py`. Everything passes except the 3 tests that need `geometry.so`; those fail identically on the baseline here because no C++ compiler is available.
- Official `check.py` on host Python: PASS, 300/300 on time, p99 0.6 ms. The arena ran in no-map fallback.
- Dense timing (`dense_timing.py`): 0 of 800 decisions over 50 ms.
- **Not run:** Docker build, `sandbox.sh`, the Linux 1-CPU container check, and anything with the real map geometry. Docker, WSL and g++ are unavailable on this machine, and MSVC lacks the Windows SDK.

## Reproduce

```sh
python validation/combat_lab.py   --bot-dir <dir> --split holdout --cases 320 --json a.json
python validation/combat_squad.py --bot-dir <dir> --split holdout --cases 240 --json b.json
python validation/combat_squad.py --bot-dir <dir> --split holdout --cases 320 --pilot --json c.json
python validation/combat_compare.py base_a.json a.json
python validation/squad_compare.py  base_b.json b.json
```

Raw result files are in `validation/results/combat/`.
