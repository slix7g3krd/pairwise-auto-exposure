import pytest
from render import auto_exposure as mod

CASES = [
    ("lum_gray", "m.luminance_linear(0.5, 0.5, 0.5) == approx(0.5)"),
    ("lum_red", "m.luminance_linear(1.0, 0.0, 0.0) > m.luminance_linear(0.0, 1.0, 0.0)"),
    ("center_true", "m.metering_center(0.5, 0.5, 0.2) is True"),
    ("center_false", "m.metering_center(1.0, 0.0, 0.2) is False"),
    ("adapt_up", "m.adapt_rate(1.0, 3.0, 1.0, 0.1, 1.0) == approx(3.0)"),
    ("adapt_down", "m.adapt_rate(3.0, 1.0, 1.0, 0.1, 1.0) < 3.0"),
    ("time_norm", "m.normalize_time(2.0, 0.5) == approx(4.0)"),
    ("time_zero", "m.normalize_time(2.0, 0.0) == approx(0.0)"),
    ("blend_start", "m.blend_manual(1.0, 5.0, 0.0) == approx(1.0)"),
    ("blend_end", "m.blend_manual(1.0, 5.0, 1.0) == approx(5.0)"),
    ("stop_double", "m.exposure_stops(2.0, 1.0) == approx(4.0)"),
    ("stop_zero", "m.exposure_stops(2.0, 0.0) == approx(2.0)"),
    ("cut_true", "m.reset_on_cut('a', 'b') is True"),
    ("cut_false", "m.reset_on_cut('a', 'a') is False"),
    ("hdr_floor", "m.hdr_nonnegative(-1.0) == approx(0.0)")
]

@pytest.mark.parametrize("name,expr", CASES, ids=[c[0] for c in CASES])
def test_contract(name, expr):
    assert eval(expr, {"m": mod, "approx": pytest.approx})
