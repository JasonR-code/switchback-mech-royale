# Unseen-shooter response (branch `claude-unseen`, built on `a589f8d` = official 4.85)

Gameplay change: `strategy.py` (+35 lines) and `combat.py` (+15 lines); `main.py`, `motion.py`, `arena.py` and `defaults.json` are unchanged. `UNSEEN = False` in `strategy.py` restores 4.85 behaviour exactly. **No official score exists for this candidate.**

## Phase 1: mechanics (from `protocol.md` and the code)

- **What a hit tells us.** A `damaged` event carries `by` (the attacker's id), `bearing` (the world yaw it came from, with no noise stated, unlike sounds' σ 7°) and `rear`. We can tell a reported rival from an unseen one by checking `by` against `obs.mechs`, which also lists mechs still tracked for 5 s after they leave view.
- **Why shooters stay unseen.** Vision is a 120° wedge on our *aim* (plus 45 m proximity). Canopy blocks sight but not shots. A shooter outside the wedge is not reported, and a hit from outside ±90° deals 1.5×.
- **Sound bearings** have 7° noise and don't say who fired. The damage-event bearing is the better evidence and is what this change uses.
- **What 4.85 does after an unseen hit:**
  - `combat.py` aims only at visible targets. `intent.scan` (which strategy does point at the hit bearing) is used **only when there is no visible target**. So while we fight rival A, hidden rival B is never looked at, never revealed, and keeps hitting our side or rear.
  - Strategy records `last_attacked`, `bearing` and `hit_by`. `hit_by` only affects `_engaging` for *visible* contacts.
  - `motion.incoming_guns` dodges only when two distinct attackers hit within 1.2 s, one of them unreported.
  - Nothing remembers repeated unseen hits or breaks that shooter's lane.
- **Real recording** (`stream.jsonl.gz`): all 13 damage events came from a reported attacker, and the glance never fires on that trace. It confirms the event fields; it holds no unseen-shooter case.

## Phase 2: the change

- **Strategy (`_unseen`).** Every non-zone hit whose `by` is not in `obs.mechs` is remembered for 3 s.
  - A shooter is **credible** with ≥ 2 such hits, or ≥ 150 damage, within 3 s.
  - While a credible unreported shooter last hit us ≤ 2.5 s ago, `intent.glance` = its latest bearing, and `scan` follows it.
  - The glance ends as soon as the shooter is reported, or 2.5 s after its last hit. A single 45-damage hit triggers nothing.
- **Combat.** With a glance and a visible target, the aim yaw is clamped to within 40° of the glance bearing (the view half-wedge is 60°). This is the smallest turn that brings the shooter into view and toward front armour.
  - If the target already fits inside that window, aim and fire are unchanged.
  - **Never abandon a near-kill:** if the target has ≤ 300 HP or ≤ 22%, no turn.
- **After the reveal,** the shooter is an ordinary contact. The existing 4.85 logic decides: target choice, rear-arc weighting, the bystander-aware escape rules and the lane-cutting `_withdraw`. No escape rule was changed. A variant that counted the hidden shooter as an extra threat (GT) changed nothing measurable and was dropped.

## Phase 3: evaluation

The lab is `combat_snowball.py --fov`, which adds the protocol vision rule (120° wedge, 45 m proximity, 5 s tracking memory). There are still no buildings, canopy or cover. The rival behaviours are assumptions; "np" means rivals we shoot don't start hunting.

- **Frequency (4.85 build).** Unreported shooters deal **32–42% of all damage taken**. There are 2.2–3.4 repeated-unseen-attack episodes per case, and 79–93% of cases have at least one. With protocol vision the 4.85 bot lives 18–28 s less, and kills 30% fewer, than with full vision.

**Episode outcomes** (`unseen_episode_probe.py`, dev split, 80 cases; 4 s after the 2nd unseen hit):

| Setting | Revealed ≤ 1.5 s | Shooter dmg, next 4 s | Death ≤ 4 s | Our kill ≤ 4 s |
|---|---|---|---|---|
| ×0.5 | 12% → 83% | 190 → 152 | 0.22 → 0.14 | 0.15 → **0.04** |
| ×0.5 np | 14% → 70% | 164 → 130 | 0.15 → 0.09 | 0.15 → **0.06** |
| ×0.3 | 14% → 78% | 114 → 87 | 0.12 → 0.08 | 0.16 → **0.03** |

**Match-level, holdout / fresh, 160 cases each** (diff [95% CI]):

| Setting | Kills | Alive (120 s cap) | Deaths < 60 s | Unseen dmg | Rear dmg |
|---|---|---|---|---|---|
| ×0.5 | −0.10 [−0.21, +0.01] / **−0.11** | **+6.4 / +3.1 s** | **−0.07** / +0.01 | −62% / −66% | −57% / −54% |
| ×0.5 np | **+0.82 / +0.84** | **+22.9 / +21.3 s** | **−0.28 / −0.24** | −59% / −63% | −72% / −72% |
| ×0.3 | −0.04 / **−0.24** | **+6.6 / +6.8 s** | **−0.09 / −0.07** | −58% / −66% | −54% / −57% |

- **Cost: eliminations sacrificed.** When every rival we hit starts hunting, kills fall by 0–0.24 and the first kill comes 9–12 s later.
- **Cause, measured:** revealing the shooter makes the *existing* crossfire rule see a second engaging rival. Escape rises from 56% to 67% of decisions (dev ×0.5). In the open field a withdrawal has no cover to reach.
- **Variants that didn't help:** a larger finish guard (any target ≤ 50%) and a smaller turn (52°) both left this unchanged.
- **Regression checks:**
  - full-vision lab (holdout ×0.5): kills −0.02, alive −0.2 s; glances are rare when everything within 200 m is visible;
  - `combat_squad.py --pilot`: bit-identical.

## Observed vs assumed

- **Observed (lab, with the protocol vision rule):** unseen shooters are a large, frequent damage source for 4.85. The response reveals them within 1.5 s in 70–83% of episodes, halves rear damage, and improves survival and early deaths in every setting.
- **Not known:**
  - How often real house bots shoot from outside our view. Codex's full-map data (15 of 39 weapon deaths) suggests often.
  - Whether house bots retaliate when shot, which decides between the np row (big kill gain) and the provoke rows (small kill loss).
  - Whether withdrawing after the reveal reaches real cover. If it does, the lane-breaking retreat pays off on maps in a way this lab cannot show.
- **Model gap:** canopy can hide a shooter even after we turn. The turn still puts it in our front arc (×1 instead of ×1.5), but nothing in the lab models canopy.

## Validation run (Windows host)

- 83 tests: all pass except the 3 that need `geometry.so` (no compiler here; they fail the same way on every build).
- New `test_unseen.py` (13 tests): credibility thresholds, the window, expiry, a reported vs unreported attacker, reveal ends the glance, zone damage ignored, switch-off, the aim turn, no turn when the shooter is already in view, the near-kill guard, and looking straight at the shooter when there is no target.
- Official `check.py`: PASS, 300/300 on time, p99 0.4 ms.
- `dense_timing.py`: p50 1.42 ms, p99 2.76 ms, 0 over 50 ms.
- **Not run:** Docker, the Linux container, real-map geometry.

Raw results are in `validation/results/unseen/`. Reproduce with:

```sh
python validation/combat_snowball.py --bot-dir <dir> --split holdout --cases 160 --rival-damage .5 --fov --json out.json
python validation/unseen_compare.py base.json cand.json
python validation/unseen_episode_probe.py <dir> dev 80 .5 p
```
