import numpy as np
import pytest

from analog_ai.devices.lut import DomainError, LUT


def test_forward_lookup_finite(engine):
    dm, ota = engine
    lut = dm.nch
    vals = lut.lookup("ids", [0.6e-6], [0.8], [0.6], [0.0])
    assert np.isfinite(vals[0]) and vals[0] > 0


def test_out_of_domain_raises(lut_paths):
    lut = LUT(lut_paths[0])
    with pytest.raises(DomainError):
        lut.lookup("ids", [5e-6], [0.8], [0.6], [0.0])   # L beyond grid
    with pytest.raises(DomainError):
        lut.lookup("ids", [0.6e-6], [2.0], [0.6], [0.0])  # VGS beyond grid


def test_reverse_lookup_round_trip(engine):
    dm, _ = engine
    lut = dm.nch
    target = 10.0
    vgs = lut.lookup_vgs([0.6e-6], [target], [0.6], [0.0])
    gmid_back = lut.lookup("gmid", [0.6e-6], vgs, [0.6], [0.0])
    assert np.isfinite(vgs[0])
    assert gmid_back[0] == pytest.approx(target, rel=0.10)


def test_reverse_lookup_unachievable_target_raises(engine):
    dm, _ = engine
    lut = dm.nch
    with pytest.raises(DomainError):
        lut.lookup_vgs([0.6e-6], [500.0], [0.6], [0.0])  # gm/Id far above range
    with pytest.raises(DomainError):
        lut.lookup_vgs([0.6e-6], [0.01], [0.6], [0.0])   # far below range


def test_in_domain_mask(lut_paths):
    lut = LUT(lut_paths[0])
    mask = lut.in_domain([0.6e-6, 99e-6], [0.8, 0.8], [0.6, 0.6], [0.0, 0.0])
    assert mask.tolist() == [True, False]
