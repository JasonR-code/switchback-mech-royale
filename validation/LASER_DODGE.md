# Laser release dodge (branch `claude-front-arc`, built on `11b3fd8` = official 5.07)

Gameplay change: **`motion.py` only** (leg movement). Strategy, combat targeting, the unseen-shooter glance and the snowball rules are untouched. Aim is independent of the legs, so firing is unchanged. `LASER_DODGE = False` restores 5.07 actions exactly (verified on the public recording). **No official score exists for this candidate.**

## Phase A: what the evidence says

**1. Pre-hit front-arc protection is too rare to matter.**
- In the map and open-field labs (`laser_warning_probe.py`), laser hits on our rear are 6–12% of laser hits. Hits that came with a visible charging warning *and* landed on our rear are only 1–7 per 40 cases.
- The reason: vision *is* the aim wedge. A charger we can see is almost always already within our front arc.
- In the public recording, all 4 laser hits were frontal.
- Turning to protect the front arc would save at most ~80–160 HP in about 0.1 cases per match, so it was not built.

**2. Lasers are the dominant damage source.**
- Real recording: 1,260 of 1,575 damage taken in 30 s came from house bot 10's laser.
- Map lab: lasers deal 53–61% of the damage in the 8 s before a death.

**3. The house laser's aim, fitted to the real recording** (`stream.jsonl.gz`, 27 charging observations, laser user id 10):
- Its charging aim fits **our position one observation earlier plus 0.3 s of our velocity**, with mean error 0.36° and median 0.22°.
- Alternatives fit worse: current position 0.65°, no extrapolation 0.78°, two observations earlier 0.85°.
- Releases came 0.8–0.9 s after the charge first showed (t 7.1→7.9, 9.8→10.6, 18.5→19.3); the charge at t 12.6–13.2 never fired.
- Consequence: at release, the beam points about **0.2 s × our lateral speed** beside us; our body radius is 2.5 m.

| Lateral speed at release | Beam offset | Outcome |
|---|---|---|
| walk, 11.7 m/s | ~2.3 m | marginal hit |
| boost, 19.5 m/s | ~3.9 m | miss |

**4. The recording matches this.**
- In the 4 hits, our speed just before release was 3.0, 6.7 and 2.8 m/s: the random strafe flip (`motion.side`, every 0.8–1.65 s) had us slowing or reversing.
- The 1 miss (t 24.4) came while we kept moving at about 11 m/s and changed direction.

**5. Observability.** Every input is something the bot sees: `charging: true`, the charger's `aim`, its position and LOS. No simulator knowledge is used. In 79–94% of lab laser hits the charger was reported as charging before the hit, with a median 0.9 s of warning.

## Phase B: the policy (`motion.py`, `_lasers` plus one scoring term)

- **Trigger:** a visible mech with `charging: true`, its aim within 0.1 rad of us, within laser range, and with LOS from its muzzle to our torso.
- **Release estimate:** first time seen charging + 0.8 s.
- **While triggered:**
  - the random strafe flip is suppressed (it would pass through zero speed at release);
  - boost is enabled when energy allows;
  - each movement candidate earns up to +22 for its sideways speed at the expected release, within the acceleration limit.
- **Limits:**
  - only moves the body can actually make earn the credit;
  - during urgent zone travel the weight is a third, so zone travel keeps priority;
  - LOS-breaking, hazard dodging, routing and every other term are unchanged.
- **When it ends:** the moment the rival stops charging.
- There is no retreat, no aim change and no change to target choice.

## Phase C: tests and matched comparisons vs exact 5.07

**Exact-state tests** (`test_laser_dodge.py`, 7 tests). Example: retreating straight away from a charger at 120 m, release 0.8 s after the warning.
- 5.07 runs radially at 9.7 m/s sideways: the beam lands **1.99 m** away, a hit.
- The candidate boosts sideways at 15.6 m/s: **3.83 m**, a miss.
- The other tests cover: no charger means identical output, a charger aiming elsewhere is ignored, a blocked lane is ignored, the release time counts from first sighting, and the state is cleared when charging stops.
- The existing corridor test (urgent travel in a 2.6 m corridor) caught a first version that steered into walls; it is fixed and passes.

**Real recording (open loop):** the dodge triggers in all 5 charge episodes, from the first `charging` observation, commanding a 0.78–1.00 lateral boost. Under the fitted aim model the beam would have landed about 3.9 m off in the 4 real hits. This is a counterfactual estimate, not an observed outcome.

**Labs with the fitted house-laser model** (`--house-laser`). Rival lasers aim at our position 0.1 s earlier + 0.3 s of velocity and release 0.80–0.95 s after starting. The 5.07 lab hit rate is 75–85%, against 4 of 5 in the recording.

**Map lab** (real buildings, protocol vision), **holdout and fresh** seeds (not used in design), 100 cases per row, final candidate vs exact 5.07, diff [95% CI]:

| Split / setting | Laser hit rate | Kills (= outlasted) | Alive | Deaths < 60 s | Died |
|---|---|---|---|---|---|
| holdout ×0.5 | 85% → 56% | +0.19 [−0.04, +0.42] | +5.1 s | **−0.08** [−0.15, −0.01] | −0.04 |
| holdout ×0.5 np | 79% → 53% | +0.13 | +0.9 s | **−0.04** [−0.08, −0.01] | +0.01 |
| holdout ×1.0 | 84% → 51% | +0.09 | **+6.1 s** [+2.3, +10.2] | −0.05 | −0.04 |
| fresh ×0.5 | 77% → 46% | **+0.28** [+0.04, +0.53] | **+7.4 s** | **−0.09** | **−0.09** |
| fresh ×0.5 np | 75% → 47% | **+0.20** [+0.00, +0.41] | +2.7 s | **−0.04** | **−0.06** |
| fresh ×1.0 | 77% → 52% | +0.11 | **+8.0 s** [+2.5, +13.7] | **−0.10** [−0.17, −0.04] | −0.07 |

- Kills are higher in all 6 rows (2 significant). Early deaths are lower in all 6 rows (5 significant), and time alive is up in all 6.
- **Costs:** rear damage changed by −14 to +33 and unseen-shooter damage by −10 to +34 (one row significant: fresh ×1.0, +34). Lateral boosting sometimes exposes us to a second rival.
- **Robustness:**
  - map lab with the old perfect-tracking laser (holdout ×0.5): kills +0.15, died −0.08, early deaths −0.01, none significant; no harm when the aim model is wrong;
  - open field with protocol vision, house laser (holdout, 160 cases): kills **+0.37**, alive **+11.5 s**, early deaths **−0.16**, rear +22;
  - `combat_squad.py --pilot`, every rival aims at us with the old laser: neutral (dealt +4.6, taken −0.2, alive −0.04 s, all n.s.).
- **Development history:** a first version without the feasibility and zone limits gave similar map results (alive +0.4 to +7.5 s, early deaths −0.03 to −0.08 in all 6 rows) but failed the corridor test, which is why the limits were added.

## Observed vs assumed

- **Observed:** the aim model and release timing of *one* house bot over *5* laser shots in the only public recording. The policy's trigger fires on all of them.
- **Assumed:**
  - other house bots and tiers use the same aim rule and release timing;
  - the lab's other rival behaviour;
  - the lab's flattened terrain and missing trees, zone and loot.
- **Validation run (Windows host):**
  - 90 tests: all pass except the 3 that need `geometry.so` (no compiler here; they fail the same way on every build), plus 7 new `test_laser_dodge.py` tests;
  - official `check.py`: PASS, 300/300, p99 0.6 ms;
  - `dense_timing.py`: p50 1.50 ms, 0 over 50 ms;
  - on the recording, `LASER_DODGE = False` gives actions identical to 5.07; enabled, 95 of 300 actions differ;
  - not run: Docker, the Linux container, real-map `geometry.so`.
- **Failure mode:** if a house laser aims at our true current position, sideways speed does not help. The lab shows it then costs nothing measurable (old perfect-tracking laser: neutral). It does spend boost energy and briefly overrides route progress during charges.

Raw results are in `validation/results/laser_dodge/` (`base` = 5.07, `cand` = first version, `cand2` = this commit).
