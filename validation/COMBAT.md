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

# Round 2 (after `aa40f9e` scored 4.63/15 in official practice)

Baseline for this round: `aa40f9e`, tagged locally as `builders-practice-4.63-baseline`. A new untouched seed split, `--split fresh`, was added to both labs, because the holdout split helped choose the round-1 rear weight.

## Interaction of the three 4.63 changes (remove one at a time; vs full 4.63)

| Removed | Duel dmg/case (holdout / fresh) | Squad net, combat only (holdout / fresh) | Full-pilot dealt (holdout / fresh) |
|---|---|---|---|
| 1 launch timing | −26 / −22 (both significant) | −5 / −66 | −23 / −19 (both significant) |
| 2 rear arc | 0 / 0 | −13 / **+51** | +2 / +3 (alive −0.03 s / −0.02 s) |
| 3 shell drift | −6 / +3 | −49 / −62 (both significant) | −8 / −8 |

Changes 1 and 3 help and don't conflict. Change 2 is neutral with the full pilot and inconsistent in the combat-only lab: it helps on holdout and hurts on fresh. It was left unchanged, since it was part of the officially scored version, but it is the first thing to drop if 4.63+ regresses.

## Weakness found: the laser was almost never fired under pressure

With the full pilot against 2–3 rivals, gun+laser was the worst loadout (636 damage dealt vs 651 for gun only), firing 0.2 beams per fight. The cause: while `intent.escape` or `intent.urgent` is set, the laser never starts a charge (charging halves walk speed) unless the target is within 48 m or the shot is lethal. While withdrawing, the existing release logic already fires at minimum charge (0.15 s), so the half-speed exposure per beam is short.

**Change 4 (`LASER_RETURN_FIRE = 1`, `LASER_TRADE_RANGE = 160`).** While withdrawing, but not while zone-urgent, allow a charge against a mech that hit us within 1.8 s, or that is aiming at us (yaw error < 0.28 rad) within 160 m. Everything else is unchanged.

Full-pilot squad lab, 320 cases per split, vs unchanged 4.63:

| Split | Damage dealt | Damage taken | Time alive | Deaths |
|---|---|---|---|---|
| dev | +190 [+150, +234] | −6 [−13, +1] | +0.23 s [+0.10, +0.39] | 301 → 295 |
| holdout | +194 [+152, +240] | −5 [−13, +2] | +0.15 s [+0.02, +0.29] | 300 → 298 |
| fresh | +188 [+147, +231] | −11 [−21, −3] | +0.11 s [−0.01, +0.25] | 297 → 288 |

The unrestricted variant (charge at any target while withdrawing) dealt slightly more damage but showed no gain in time alive (+0.09 to +0.11 s, CIs include 0), so the narrower rule was kept. The duel lab and the combat-only squad lab send no escape intent, so they are bit-identical to 4.63.

**Main risk.** The labs have no cover. On the real map, a slower retreat toward cover could cost more than these labs show. The rule only applies to a rival that is already shooting at or aiming at us, and while withdrawing the beam releases at 0.15 s.

## Checked and left alone

Target switching (`switch_probe.py`): focus changes on 1.8% of decisions, about every 5.5 s. In 622 decisions with a rival at ≤250 HP in view, the bot never aimed elsewhere. No missed-elimination pattern was found in the labs.

## Validation

67 tests pass, except the 3 that need `geometry.so` (no compiler on this host). The 4 new laser tests were confirmed to fail with the rule disabled. Official `check.py` on host: PASS, 300/300, p99 0.5 ms. Dense timing: p50 1.46 ms, 0 over 50 ms. Docker and real-map tests: **not run** (unavailable on this host).
