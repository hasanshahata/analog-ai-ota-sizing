import numpy as np
import pytest

from analog_ai import config
from analog_ai.circuit.ota5t import InvalidDesignError
from analog_ai.envs.sizing_env import OTA5tSizingEnv


class _AlwaysInvalidOTA:
    """Stand-in engine that rejects every design (no LUTs needed)."""

    def evaluate(self, x, CL, freqs=None):
        raise InvalidDesignError("synthetic rejection")


@pytest.fixture
def invalid_env():
    return OTA5tSizingEnv(_AlwaysInvalidOTA(), max_steps=10)


def test_observation_shape_and_dtype(invalid_env):
    obs, _ = invalid_env.reset(seed=0)
    assert obs.shape == (15,)
    assert obs.dtype == np.float32


def test_seeding_is_reproducible(engine):
    """Two envs with the same seed must produce identical trajectories."""
    _, ota = engine
    a, b = OTA5tSizingEnv(ota, max_steps=5), OTA5tSizingEnv(ota, max_steps=5)
    obs_a, _ = a.reset(seed=123)
    obs_b, _ = b.reset(seed=123)
    assert np.array_equal(obs_a, obs_b)
    act = np.zeros(5, dtype=np.float32)
    for _ in range(5):
        ra = a.step(act)
        rb = b.step(act)
        assert np.array_equal(ra[0], rb[0])
        assert ra[1] == rb[1]


def test_action_maps_to_bounds(engine):
    _, ota = engine
    env = OTA5tSizingEnv(ota, max_steps=5)
    env.reset(seed=1)
    _, _, _, _, info = env.step(np.ones(5, dtype=np.float32))
    assert np.allclose(env.state, env.bounds[:, 1])
    env.step(-np.ones(5, dtype=np.float32))
    assert np.allclose(env.state, env.bounds[:, 0])


def test_invalid_design_gets_finite_reward_and_is_counted(invalid_env):
    invalid_env.reset(seed=0)
    obs, reward, terminated, truncated, info = invalid_env.step(np.zeros(5))
    expected = -config.COST_INVALID / config.REWARD_SCALE
    assert info["invalid"] is True
    assert invalid_env.invalid_count == 1
    assert reward == pytest.approx(expected)
    assert np.isfinite(reward)
    assert np.isfinite(obs).all()


def test_one_shot_mode_terminates_after_single_step(engine):
    _, ota = engine
    env = OTA5tSizingEnv(ota, max_steps=200, one_shot=True)
    env.reset(seed=3)
    _, _, terminated, truncated, _ = env.step(np.zeros(5))
    assert terminated and not truncated


def test_standard_mode_truncates_at_max_steps(engine):
    _, ota = engine
    env = OTA5tSizingEnv(ota, max_steps=3)
    env.reset(seed=3)
    for i in range(3):
        _, _, terminated, truncated, _ = env.step(np.zeros(5))
    assert truncated and not terminated


def test_custom_target_sampler_used(engine):
    _, ota = engine

    def sampler(rng):
        return {"Gain_min": 21.0, "GBW_min": 60e6, "CL_pF": 0.5,
                "Power_max": 120e-6}

    env = OTA5tSizingEnv(ota, max_steps=5, target_sampler=sampler)
    env.reset(seed=9)
    assert env.target_specs == sampler(None)
