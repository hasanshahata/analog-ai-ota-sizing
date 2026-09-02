"""Goal-conditioned OTA sizing environment (canonical, fixed).

Observation and action spaces are **bit-compatible with the V9-V12 trained
models**: 15-D observation = [design(5) | performance(5) | targets(5)] with the
same normalization constants, 5-D action in [-1, 1] mapped to the design bounds.

Fixes vs. the V12 environment (`archive/versions/V12_Trainer/optimizer/rl_environment.py`):
1. **Gymnasium seeding is honored.** `reset()` calls `super().reset(seed=seed)`
   and all sampling uses `self.np_random`. The legacy env sampled through the
   global `np.random`, so runs were unreproducible even in principle.
2. **Invalid evaluations get a finite penalty, not -1e7.** The legacy env
   returned cost 1e9 on any exception, which the V12 reward `-cost/100` turned
   into a -1e7 reward with no guard. Here invalid designs cost
   `config.COST_INVALID` (finite, worse than any valid design) and are counted
   in `info["invalid"]`.
3. **Non-finite metrics are guarded** before entering the reward.
4. **`one_shot=True`** runs 1-step episodes (contextual-bandit formulation,
   the V13 direction): the target changes every step, giving PPO 2048 unique
   goals per rollout instead of ~10.

The cost function is the V10 smooth relative-squared form (kept for
comparability). It is a *training* signal — acceptance is decided by
`analog_ai.evaluation.constraints`, never by cost magnitude.
"""

from __future__ import annotations

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover
    raise ImportError("gymnasium is required for the RL environment") from exc

from .. import config
from ..circuit.ota5t import InvalidDesignError, OTA5T
from ..devices.lut import DomainError


class OTA5tSizingEnv(gym.Env):
    """5-parameter absolute-action OTA sizing environment."""

    metadata = {"render_modes": []}

    def __init__(self, ota: OTA5T, bounds=None, max_steps: int = 200,
                 one_shot: bool = False, target_sampler=None):
        super().__init__()
        self.ota = ota
        self.bounds = np.array(bounds if bounds is not None else config.DESIGN_BOUNDS,
                               dtype=float)
        self.max_steps = 1 if one_shot else max_steps
        self.one_shot = one_shot
        self._target_sampler = target_sampler

        n = self.bounds.shape[0]
        self.action_space = spaces.Box(low=-1.0, high=1.0, shape=(n,), dtype=np.float32)
        # 15-D observation: design(n) + performance(5) + targets(5).
        # NOTE: for n != 5 this is no longer V9-V12-compatible (those models
        # require n == 5 and 15-D observations).
        obs_dim = n + 5 + 5
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf,
                                            shape=(obs_dim,), dtype=np.float32)

        self.current_step = 0
        self.invalid_count = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._sample_design()
        self.current_cost = self._evaluate_state(self.state)[0]

    # ----------------------------------------------------------- sampling --
    def _sample_target_specs(self) -> dict:
        if self._target_sampler is not None:
            return self._target_sampler(self.np_random)
        rng = self.np_random
        return {
            "Gain_min": rng.uniform(*config.TARGET_RANGES["Gain_min"]),
            "GBW_min": rng.uniform(*config.TARGET_RANGES["GBW_min"]),
            "CL_pF": rng.uniform(*config.TARGET_RANGES["CL_pF"]),
            "Power_max": rng.uniform(*config.TARGET_RANGES["Power_max"]),
        }

    def _sample_design(self) -> np.ndarray:
        return self.np_random.uniform(self.bounds[:, 0], self.bounds[:, 1])

    # ------------------------------------------------------------ cost -----
    def calc_cost(self, perf, specs: dict) -> float:
        """V10 smooth one-sided relative-squared cost (canonical copy)."""
        if perf is None:
            return config.COST_INVALID
        cost = 0.0

        def term(err):
            return (err * 10.0) ** 2

        if perf["DC_Gain_dB"] < specs["Gain_min"]:
            cost += term((specs["Gain_min"] - perf["DC_Gain_dB"]) / specs["Gain_min"])
        if perf["GBW"] < specs["GBW_min"]:
            cost += term((specs["GBW_min"] - perf["GBW"]) / specs["GBW_min"])
        if perf["Power"] > specs["Power_max"]:
            cost += term((perf["Power"] - specs["Power_max"]) / specs["Power_max"])
        if perf["PM"] < config.PM_MIN_DEFAULT:
            cost += term((config.PM_MIN_DEFAULT - perf["PM"]) / config.PM_MIN_DEFAULT)
        if perf["min_sat_margin"] < config.SAT_MARGIN_MIN_DEFAULT:
            cost += term((config.SAT_MARGIN_MIN_DEFAULT - perf["min_sat_margin"])
                         / config.SAT_MARGIN_MIN_DEFAULT)

        devices = perf.get("devices", {})
        w_nmos = max((devices[d]["W"] for d in ("M1", "M2", "M5")), default=0.0)
        if w_nmos > config.W_NMOS_MAX:
            cost += term((w_nmos - config.W_NMOS_MAX) / config.W_NMOS_MAX)
        w_pmos = max((devices[d]["W"] for d in ("M3", "M4")), default=0.0)
        if w_pmos > config.W_PMOS_MAX:
            cost += term((w_pmos - config.W_PMOS_MAX) / config.W_PMOS_MAX)

        # Gentle secondary objective.
        cost += (perf["Power"] / config.OBS_POWER_NORM) * 0.1
        cost += perf["Area"] * 1e12 * 0.01
        return float(cost)

    def _evaluate_state(self, x):
        """Returns (cost, perf-or-None). Invalid designs get a FINITE cost."""
        try:
            cl = self.target_specs["CL_pF"] * 1e-12
            perf = self.ota.evaluate(x, CL=cl)
            metrics_finite = np.isfinite([perf["DC_Gain_dB"], perf["PM"]]).all()
            if not metrics_finite or not perf.get("gbw_valid", True):
                # NaN metrics, or GBW beyond the sweep maximum (unverifiable).
                return config.COST_INVALID, None
            return self.calc_cost(perf, self.target_specs), perf
        except (InvalidDesignError, DomainError, ValueError, FloatingPointError):
            return config.COST_INVALID, None

    # -------------------------------------------------------- observation --
    def _normalize_state(self, perf) -> np.ndarray:
        design_norm = ((self.state - self.bounds[:, 0])
                       / (self.bounds[:, 1] - self.bounds[:, 0]))
        if perf is None:
            performance = np.zeros(5, dtype=np.float32)
        else:
            performance = np.array([
                perf["DC_Gain_dB"] / config.OBS_GAIN_NORM,
                perf["GBW"] / config.OBS_GBW_NORM,
                perf["Power"] / config.OBS_POWER_NORM,
                perf["PM"] / config.OBS_PM_NORM,
                max(perf["min_sat_margin"], 0.0) / config.OBS_SAT_NORM,
            ], dtype=np.float32)
        targets = np.array([
            self.target_specs["Gain_min"] / config.OBS_GAIN_NORM,
            self.target_specs["GBW_min"] / config.OBS_GBW_NORM,
            self.target_specs["CL_pF"] / config.OBS_CL_NORM,
            self.target_specs["Power_max"] / config.OBS_POWER_NORM,
            config.PM_MIN_DEFAULT / config.OBS_PM_NORM,
        ], dtype=np.float32)
        return np.concatenate([design_norm.astype(np.float32), performance, targets])

    # ----------------------------------------------------------- gym API ---
    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.target_specs = self._sample_target_specs()
        self.state = self._sample_design()
        self.current_cost, perf = self._evaluate_state(self.state)
        return self._normalize_state(perf), {}

    def step(self, action):
        self.current_step += 1
        action = np.clip(np.asarray(action, dtype=float), -1.0, 1.0)
        # Absolute parameter output: action maps onto the design bounds.
        new_state = self.bounds[:, 0] + (action + 1.0) / 2.0 * (self.bounds[:, 1] - self.bounds[:, 0])
        new_cost, perf = self._evaluate_state(new_state)

        if perf is None:
            self.invalid_count += 1
        reward = float(-new_cost / config.REWARD_SCALE)
        if not np.isfinite(reward):  # belt-and-braces guard
            reward = -float(config.COST_INVALID / config.REWARD_SCALE)

        self.state = new_state
        self.current_cost = new_cost

        terminated = bool(self.one_shot and self.current_step >= self.max_steps)
        truncated = bool(not self.one_shot and self.current_step >= self.max_steps)
        info = {"invalid": perf is None, "invalid_count": self.invalid_count,
                "cost": new_cost}
        return self._normalize_state(perf), reward, terminated, truncated, info
