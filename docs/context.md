# Analog AI Optimization: Version History & Context

> **STATUS (2026-09-02) — this document is a historical diary, not the current state.**
> The V1–V13 narrative below describes the *legacy* system, which now lives in
> `archive/`. All "CURRENT" markers below refer to that archived era.
>
> If you just moved this folder to a new PC, start with **`docs/HANDOFF.md`** —
> it has setup commands, current evidence, and the exact command to resume
> work in flight.
>
> The current state of the project:
> - Entry point after a machine move: `docs/HANDOFF.md`
> - Canonical code: `analog_ai/` package (see root `README.md`)
> - What was fixed and why: `docs/CORRECTION_LOG.md`
> - Audit of this diary (several claims below are corrected there):
>   `docs/PROJECT_REVIEW.md` §6
> - Frozen acceptance contract: `docs/DESIGN_CONTRACT.md`
>
> Headline changes since this diary was written: the workspace was
> reorganized and versioned with git; the physics engine now solves the DC
> operating point from the Spectre-characterized LUTs by KCL instead of
> imposing it; matched pairs, body effect, and domain validation are fixed;
> a hard-constraint verifier decides every pass/fail; and canonical
> evaluation shows the best RL model (V12) is equivalent to a constant
> design (1/5 tests) while a plain differential-evolution baseline passes
> 5/5. Training another PPO reward variant is not the path forward — see
> `docs/codex_plan.md`.

This document tracks the evolution of the Goal-Conditioned RL Agent for sizing the 65nm 5T-OTA. It documents the core problems faced in each iteration and the mathematical adjustments made to the reward function to solve them.

---

## Project Goal
Use Reinforcement Learning (PPO) to train an AI agent that can size a 5-Transistor Operational Transconductance Amplifier (5T-OTA) in a TSMC 65nm process. The agent must hit target specs for DC Gain, Gain-Bandwidth Product (GBW), Power consumption, Phase Margin (PM > 45°), and Saturation Margin, while keeping transistor sizes within physical limits.

## Brute-Force Sweep (Ground Truth)
A brute-force sweep of the entire design space proved that solutions meeting ALL specs exist for every test case:
- **Test 1 (Low Power):** 210 solutions found (best GBW=57MHz)
- **Test 2 (High Gain):** 6 solutions found (best Gain=35.4dB)
- **Test 3 (Heavy Load):** 103 solutions found (best GBW=66MHz)
- **Test 4 (Light Load):** 486 solutions found (best GBW=931MHz!)
- **Test 5 (Balanced):** 192 solutions found (best GBW=130MHz)

This proves the physics engine works correctly and the AI failures are always in the RL design, not the circuit simulator.

---

## V1 - V3: The Physics Boundary Problem
- **Problem:** The AI output nonsensical values for L and W (e.g., L=0.01nm, W=10000μm). These broke the interpolation math in the `tech_luts` lookup tables.
- **Fix:** Constrained L between 60nm and 1.5μm, restricted Itail to realistic bounds (10μA–500μA).

## V4: The Exploding Gradients Problem
- **Problem:** Unbounded quadratic penalties (e.g., `penalty += (Target - Achieved)^2`). Missing the target by a large amount generated penalties of ~10^14, causing NaN weights.
- **Fix:** Capped maximum penalty using `min()` functions.

## V5: The Balancing Problem
- **Problem:** Metrics not normalized against each other. PM/saturation penalties overshadowed Gain/GBW targets.
- **Fix:** Attempted rebalancing of penalty weights.

## V6: The "Reward Hacking" Problem
- **Problem:** "Normalized Cliffs" — breaking physical rules (NMOS width > 250μm) = 100,000 point penalty, but completely failing GBW was capped at ~62,500.
- **Result:** AI discovered the loophole: drop current to minimum (10μA), do nothing, and accept the 62,500 GBW penalty because it was "safer" than risking the 100,000 cliff.

## V7: The "Pareto Equilibrium" Problem
- **Problem:** Mathematically flawless 0–2000 scale, but AI stopped ~30% short of GBW targets consistently.
- **Root Cause:** Power penalty (1.0 point per 100μW) was equal to GBW penalty (1.0 point per 14MHz miss). AI calculated that spending 100μW more power to gain 14MHz more GBW produced zero net benefit — penalties cancelled out.

## V8: The "Physics Wall" (DISPROVEN)
- **Problem:** Initially concluded the 5T-OTA had a fundamental physics limit preventing all specs from being met simultaneously.
- **Disproof:** Brute-force sweep (see above) found hundreds of valid solutions for every test case.
- **Real Problem:** The failure was in the RL architecture, not the reward function.

---

## V9: The Architecture Fix (3 Fundamental Bugs)

### Bug 1: Blind Observation (8D → 15D)
- **Problem:** Observation was only [Gain, GBW, CL, Power] + [Targets] = 8D. The AI could NOT see its own design parameters (L1, gm/Id, Itail) or critical constraints (PM, saturation).
- **Fix:** Expanded to 15D: [L1, gmid1, L3, gmid3, Itail] + [Gain, GBW, Power, PM, sat_margin] + [Gain_t, GBW_t, CL_t, Power_t, PM_t].

### Bug 2: Delta-Based Movement Trap
- **Problem:** Action space used incremental steps (delta = action * range * 0.1). The optimal designs require specific L/gm/Id combinations, and the path from random start to optimal region passes through "death valleys."
- **Fix:** Direct parameter output. AI outputs absolute design parameters in a single step.

### Bug 3: Delta-Based Reward Hid Absolute Quality
- **Problem:** `reward = old_cost - new_cost` only rewarded improvement. Once at a local minimum, reward ≈ 0 and no gradient to escape.
- **Fix:** Absolute normalized reward: `reward = max(0, 1 - cost/500)`.

### V9 Evaluation Results
| Test | Gain Target/Achieved | GBW Target/Achieved | Power Target/Achieved |
|---|---|---|---|
| test1_low_power | 20.0/**35.8** ✅ | 20M/**4M** ❌ | 50/**12** ✅ |
| test2_high_gain | 35.0/**35.4** ✅ | 50M/**17M** ❌ | 150/**12** ✅ |
| test3_heavy_load | 25.0/**35.8** ✅ | 50M/**4M** ❌ | 350/**12** ✅ |
| test4_light_load | 20.0/**35.8** ✅ | 250M/**142M** ❌ | 200/**12** ✅ |
| test5_balanced | 30.0/**35.8** ✅ | 100M/**4M** ❌ | 250/**12** ✅ |

- **Diagnosis:** Agent collapsed to Itail=10μA, L=1.5μm ("Safe Zone"). The V8 cost function's 2000-point cliffs for PM/power/saturation were so terrifying that the agent refused to increase current (which would increase GBW) because it risked hitting those cliffs. GBW penalty was smaller than the cliff risk.

---

## V10: The Smooth Cost Function Fix

### Problem from V9
The "Hierarchy of Needs" cost function had hard 2000-point cliffs. The AI stayed in the safe zone (minimum current, maximum length) to avoid all risk, ignoring GBW.

### Fix Applied
Replaced ALL cliff penalties with a single unified formula:
```
penalty = ((Target - Achieved) / Target * 10)^2
```
- Missing any target by 10% → penalty of 1.0
- Missing any target by 50% → penalty of 25.0
- Missing any target by 100% → penalty of 100.0

No more cliffs. Every spec (Gain, GBW, Power, PM, Saturation, Area) uses the exact same normalized scale.

### V10 Evaluation Results
| Test | Gain Target/Achieved | GBW Target/Achieved | Power Target/Achieved |
|---|---|---|---|
| test1_low_power | 20.0/**35.7** ✅ | 20M/**17M** ❌ | 50/**12** ✅ |
| test2_high_gain | 35.0/**35.3** ✅ | 50M/**14M** ❌ | 150/**12** ✅ |
| test3_heavy_load | 25.0/**30.4** ✅ | 50M/**41M** ❌ | 350/**530** ❌ |
| test4_light_load | 20.0/**30.8** ✅ | 250M/**214M** ❌ | 200/**199** ✅ |
| test5_balanced | 30.0/**30.5** ✅ | 100M/**95M** ❌ | 250/**357** ❌ |

- **Progress:** Tests 3–5 got MUCH closer to GBW targets (41M/50M, 214M/250M, 95M/100M). The smooth cost function is working!
- **But:** Tests 1–2 still collapsed to minimum current (Itail=10μA, L=1.5μm).

### V10 Diagnosis: The "Survival Bonus" Bug
The reward was: `reward = max(-1.0, 1.0 - cost/100.0)` with early termination at `cost < 5.0`.

**The exploit:** A mediocre design (cost=50) gave +0.5 reward/step × 200 steps = +100 total. But a perfect design (cost<5) triggered early termination: +1.0 reward × 1 step = +1.0 total. The AI earned **100x more reward by being mediocre** than by being perfect!

---

## V11: The Survival Bonus Fix (CURRENT)

### Fix Applied (2 critical lines)
1. **Pure negative reward:** `reward = clip(-cost, -10, 0)`
   - Mediocre design (cost=50): -10/step × 200 steps = **-2000 total**
   - Perfect design (cost=0): 0/step × 200 steps = **0 total**
   - The ONLY way to maximize reward is to drive cost to absolute zero.

2. **No early termination:** `terminated = False`
   - Agent must endure all 200 steps. No exploit possible.
   - There is mathematically no way to "hide" in a mediocre state.

### Training
- **Kaggle Kernel:** https://www.kaggle.com/code/soonashahata/ota-rl-model-v11
- **Model:** `universal_ppo_agent_65nm_v11.zip`
- **Architecture:** PPO, MlpPolicy, net_arch=[256,256], lr=0.0001, batch_size=512, n_steps=2048
- **Training Steps:** 500,000

---

## Technical Details

### Design Parameters (Action Space)
| Parameter | Range | Description |
|---|---|---|
| L1 | 60nm – 1.5μm | NMOS input pair channel length |
| gmid1 | 5.0 – 25.0 | NMOS input pair gm/Id |
| L3 | 60nm – 1.5μm | PMOS load channel length |
| gmid3 | 5.0 – 25.0 | PMOS load gm/Id |
| Itail | 10μA – 500μA | Tail bias current |

### Target Specs (Sampled per episode)
| Spec | Range |
|---|---|
| Gain | 20 – 45 dB |
| GBW | 50M – 300M Hz |
| CL | 0.1 – 5.0 pF |
| Power | 50 – 400 μW |

### LUT Files
- `TSMC_fast_65nm_nch.pkl` (~1.25 GB) — NMOS lookup table
- `TSMC_fast_65nm_pch.pkl` (~1.25 GB) — PMOS lookup table
- Hosted on Google Drive, pulled into Kaggle via kernel output from V9/V10 runs.

### V11 Evaluation Results
| Test | Gain Target/Achieved | GBW Target/Achieved | Power Target/Achieved |
|---|---|---|---|
| test1_low_power | 20.0/**30.8** ✅ | 20M/**223M** ✅🔥 | 50/**267** ❌ |
| test2_high_gain | 35.0/**30.6** ❌ | 50M/**223M** ✅🔥 | 150/**263** ❌ |
| test3_heavy_load | 25.0/**30.4** ✅ | 50M/**61M** ✅ | 350/**259** ✅ |
| test4_light_load | 20.0/**30.7** ✅ | 250M/**731M** ✅🔥 | 200/**274** ❌ |
| test5_balanced | 30.0/**30.5** ✅ | 100M/**226M** ✅🔥 | 250/**265** ❌ |

- **Progress:** The survival bonus fix worked perfectly — GBW went from 4-17 MHz (V10) to 61-731 MHz. The agent broke out of the safe zone.
- **But:** The agent learned ONE fixed design (Itail≈220μA, L≈0.65μm) and applies it to ALL targets. It is not goal-conditioned.
- **Root Cause: Reward Clipping Destroyed the Gradient.** `reward = clip(-cost, -10, 0)` meant that costs of 15 and 500 both gave the same reward of -10. The agent couldn't distinguish "slightly over power budget" from "catastrophically over power budget." It converged to a single average-good design instead of adapting per-target.

---

## V12: The Reward Scaling Fix (CURRENT)

### Problem from V11
The reward clip `[-10, 0]` was too aggressive. The agent couldn't distinguish fine-grained cost differences, so it learned one average policy instead of a goal-conditioned policy.

### Fix Applied
1. **Removed aggressive clipping:** Changed from `clip(-cost, -10, 0)` to `reward = -cost / 100.0` with NO clipping.
   - cost=0 (perfect) → reward=0.0
   - cost=10 (decent) → reward=-0.1
   - cost=50 (mediocre) → reward=-0.5
   - cost=100 (bad) → reward=-1.0
   - cost=500 (very bad) → reward=-5.0
   - Now the agent can see the FULL gradient and distinguish fine-grained differences.
2. **Doubled training to 1,000,000 steps** — A goal-conditioned policy is harder to learn; more training time is needed.

### Training
- **Kaggle Kernel:** https://www.kaggle.com/code/soonashahata/ota-rl-model-v12
- **Model:** `universal_ppo_agent_65nm_v12.zip`

### V12 Evaluation Results
| Test | Gain Target/Achieved | GBW Target/Achieved | Power Target/Achieved | Verdict |
|---|---|---|---|---|
| test1_low_power | 20.0/**31.8** ✅ | 20M/**204M** ✅ | 50/**306** ❌ | Power fail |
| test2_high_gain | 35.0/**31.8** ❌ | 50M/**204M** ✅ | 150/**306** ❌ | Gain+Power fail |
| test3_heavy_load | 25.0/**31.8** ✅ | 50M/**70M** ✅ | 350/**306** ✅ | **PASS** ✅ |
| test4_light_load | 20.0/**31.8** ✅ | 250M/**576M** ✅ | 200/**306** ❌ | Power fail |
| test5_balanced | 30.0/**31.8** ✅ | 100M/**204M** ✅ | 250/**306** ❌ | Power fail |

- **Diagnosis:** The agent is still stuck on ONE fixed design (Itail≈255μA, L=0.78μm) and ignores the targets. Test 3 passes only because its targets happen to match this "average" design.
- **Root Cause: The Target Starvation Bug.** In V9, we switched the action space to output *absolute parameters* directly, but we left the episode length at `max_steps = 200`. This caused two catastrophic mathematical failures in the RL framework:
  1. **Data Starvation:** Since the target only changes at the start of an episode, the agent spends 200 steps looking at the exact same target. In a PPO rollout of 2048 steps, it only sees ~10 unique targets! You cannot train a neural network to generalize across targets if it only sees 10 targets per batch.
  2. **Advantage Collapse:** Because the agent directly outputs the absolute state, the state at step `t+1` is entirely dependent on the action at `t+1`, and independent of the action at `t`. This completely breaks PPO's Temporal Difference advantage estimation. The Advantage signal becomes pure noise, forcing the agent to collapse to a single constant action to minimize variance.

---

## V13: One-Shot Sizing (CURRENT PLAN)

### The Paradigm Shift
If the agent is outputting absolute parameters directly, it is not "navigating" an environment. It is solving a **Contextual Bandit** (or supervised learning) problem: look at the target, instantly output the design. 

### Fix Applied
1. **One-Shot Episodes:** Set `max_steps = 1` and `terminated = True`.
   - The agent will now see **2048 UNIQUE targets** in every PPO batch, completely solving the data starvation problem.
   - PPO mathematically reduces to REINFORCE (contextual bandit), perfectly matching the direct-parameter output architecture.
2. **5D Observation Space:** Remove the current state and performance from the observation. The agent only needs to see the 5 targets it is aiming for: `[Gain_t, GBW_t, CL_t, Power_t, PM_t]`. This simplifies the network's job immensely.

With 2048 unique targets per batch and a clean 5D->5D mapping, the agent will finally learn true goal-conditioned behavior.
