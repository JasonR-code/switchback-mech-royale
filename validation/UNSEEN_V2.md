# Unseen-shooter V2: kill-race commitment (branch `claude-unseen-v2`, built on `11b3fd8` = official 5.07)

`11b3fd8` (deployed and scored at 5.07) has the same Git tree as candidate `d082c9f` (`3a27d4a6…`).

Gameplay change: **`strategy.py` only**, +41 lines. The unseen-shooter detection and glance, the Snowball V1 bystander rules and all of `combat.py` are unchanged. It contains no V2 duel-hold or navigation code. `RACE = False` restores 5.07 behaviour exactly. **No official score exists for this candidate.**

## Which suspected weakness is frequent?

`validation/glance_probe.py` runs combat on a deep copy *without* the glance at every glancing decision, which gives the counterfactual trigger. Snowball lab with protocol vision, 5.07 build, holdout split, 60 cases × 3 settings:

| Suspect | Measured frequency | Verdict |
|---|---|---|
| 1. Glance withholds gun fire | 45–110 shots in ~28–41k decisions, ≈ 0.8–1.8 shots (35–80 dmg) per case | rare |
| 2. Glance delays a laser release | 3–11 releases in 60 cases (0.05–0.2 per case) | rare |
| 3. Retreat after a reveal | escape on **51–86%** of decisions in the 3 s after a glance ends; these windows are 9–12% of all decisions | **frequent** |
| 5. 300 HP finish guard too narrow | an ablation that deferred the glance by the same race test changed kills by +0.01 to +0.04 | not the bottleneck |

## The change

`_race` uses only *measured* evidence from the last 2.5 s:
- our `hit` events on each visible rival give our damage rate and its time-to-kill, `ttk = hp / rate`; at least 2 hits are needed;
- all our `damaged` events give the incoming damage rate.

**Rule:** we **commit** to the rival with the smallest ttk if both hold:
- `ttk ≤ 3 s` (×1.25 for the rival already committed to, so the choice doesn't flicker);
- our HP − 1.5 × incoming × ttk ≥ 30% of max HP.

**Effect of a commit** (snowball phase only, fewer than 8 dead and before 300 s):
- the escape is cleared;
- strategy's focus is set to that rival, which combat weights ×1.42, so aim doesn't swing to the newly revealed shooter.

**When it stops:**
- as soon as the measured race stops adding up, the escape rules apply again;
- a heavy crossfire raises the incoming rate and so ends the commit by itself.

**Not blanket aggression:** without at least 2 recent hits on a target that will die within 3 s, nothing changes.

## Ablation (dev split, 80 cases × 3 settings, vs 5.07)

| Variant | Kills | Alive | Notes |
|---|---|---|---|
| race holds escape + defers glance | +0.11 to +0.16 | −1.1 to +0.9 s | |
| race defers glance only | +0.01 to +0.04 | ≈ 0 | rear +9 |
| race holds crossfire escapes only | +0.05 to +0.17 | −3.1 to +1.5 s | worse survival |
| **race holds any escape** (chosen) | **+0.15 to +0.17** | −0.3 to +1.2 s | |
| same, 40% reserve | +0.09 to +0.17 | −0.6 to +1.5 s | |
| same, 2 s ttk | −0.01 to +0.05 | −1.2 to −2.6 s | |

## Holdout and fresh (160 cases per row, vs 5.07, diff [95% CI])

| Split / setting | Kills | First kill | Alive | Deaths < 60 s | Unseen dmg | Rear dmg |
|---|---|---|---|---|---|---|
| holdout ×0.5 | +0.08 [−0.02, +0.17] | **−7.4 s** | **−1.9 s** [−3.8, −0.1] | +0.02 | −10 | **+17** |
| holdout ×0.5 np | +0.01 | **−0.4 s** | −1.6 s | +0.02 | +16 | **+20** |
| holdout ×0.3 | +0.06 | **−4.1 s** | +0.5 s | +0.00 | −14 | +2 |
| fresh ×0.5 | **+0.14** [+0.03, +0.26] | **−6.7 s** | −0.7 s | +0.03 | −4 | 0 |
| fresh ×0.5 np | +0.03 | **−0.5 s** | −0.6 s | +0.03 | +3 | 0 |
| fresh ×0.3 | +0.12 [−0.03, +0.28] | **−3.2 s** | −1.6 s | −0.01 | −4 | +7 |

**Other measurements (holdout):**
- **After unseen attacks** (`unseen_episode_probe.py`, 120 cases × 3): our kill within 4 s went 0.03 → 0.06, 0.05 → 0.05 and 0.04 → 0.08. Our death within 4 s went 0.15 → 0.15, 0.06 → 0.09 and 0.07 → 0.05. Reveal rate and shooter damage are unchanged.
- **Retreats after reveals:** in the 3 s after a glance, escape fell from 86% to 81%, 51% to 48%, and 84% to 75% of decisions.
- **Interrupted shots:** gun shots withheld by glances were unchanged or fewer (55 → 55, 45 → 45, 110 → 61). Laser releases withheld went 3 → 2, 11 → 10 and 5 → 2.
- **Full-vision lab** (holdout ×0.5): kills **+0.25** [+0.11, +0.39], alive **+3.0 s** [+0.4, +5.8].
- **Squad lab** (`combat_squad.py --pilot`, every rival aims at us): bit-identical.

## Honest reading

- **Observed:**
  - kills are higher in all 6 protocol-vision rows, but only 1 CI excludes zero;
  - the first kill comes earlier in all 6 rows, all significant;
  - survival is slightly lower in 5 of 6 rows (one significant), and rear damage is higher in two;
  - early deaths show no significant change.
- **Expected effect:** a modest kill-tempo gain (about +2–10% kills) at a small survival cost. It is **not** a step change.
- **Related history:** this is the same family as Snowball V2's duel hold, which scored 4.81 against 4.85 (within noise). It differs by using measured damage rates and kill time instead of HP comparison, and by applying after reveals.
- **Assumed:**
  - house-bot damage is steady enough over 2.5 s for the measured rates to predict the next 3 s;
  - on real maps, cover could make the retreat it replaces worth more than the lab shows.

## Validation run (Windows host)

- 91 tests: all pass except the 3 that need `geometry.so` (no compiler here; they fail the same way on every build).
- New `test_race.py` (8 tests): no evidence → retreat; a measured kill holds the fight and the focus; a single hit is not enough; a healthy target is not a race; heavy incoming damage still retreats; a crossfire commit needs the race to add up; old hits expire; late game and switch-off revert.
- Official `check.py`: PASS, 300/300 on time, p99 0.5 ms.
- `dense_timing.py`: p50 1.42 ms, 0 over 50 ms.
- **Not run:** Docker, the Linux container, real-map geometry.

Raw results are in `validation/results/unseen_v2/` (`*_base` = 11b3fd8, `*_cand` = this commit, dev ablations by name).
