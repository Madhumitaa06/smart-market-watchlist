"""
The core claim: a move is judged against the stock's own behaviour, not a
fixed threshold. These tests exist because that claim is the entire product -
if it silently regressed, everything else would still appear to work.
"""

import cache
import anomaly


def test_flags_a_move_that_is_large_for_a_calm_stock(steady_history):
    cache.put_history("CALM.NS", steady_history)
    verdict = anomaly.assess("CALM.NS", 2.0, 1_000_000)
    assert verdict["assessed"]
    assert verdict["unusual"], "2% should be unusual for a stock that moves ~0.2%"


def test_same_move_is_not_flagged_for_a_volatile_stock(choppy_history):
    cache.put_history("CHOPPY.NS", choppy_history)
    verdict = anomaly.assess("CHOPPY.NS", 2.0, 1_000_000)
    assert verdict["assessed"]
    assert not verdict["unusual"], "2% is routine for a stock that swings ~4%"


def test_identical_move_different_verdicts(steady_history, choppy_history):
    """The comparison that justifies the whole approach, in one assertion."""
    cache.put_history("CALM.NS", steady_history)
    cache.put_history("CHOPPY.NS", choppy_history)
    calm = anomaly.assess("CALM.NS", 2.0, 1_000_000)
    choppy = anomaly.assess("CHOPPY.NS", 2.0, 1_000_000)
    assert calm["unusual"] != choppy["unusual"]


def test_declines_without_enough_history():
    cache.put_history("NEW.NS", [("2026-07-01", 100.0, 1000),
                                 ("2026-07-02", 101.0, 1000)])
    verdict = anomaly.assess("NEW.NS", 5.0, 1000)
    assert not verdict["assessed"]
    assert verdict["reason"] == "insufficient_history"


def test_declines_when_a_stock_has_not_moved():
    """No variation means no scale to measure against - and a divide by zero."""
    flat = [(f"2026-07-{i+1:02d}", 100.0, 1000) for i in range(30)]
    cache.put_history("FLAT.NS", flat)
    verdict = anomaly.assess("FLAT.NS", 1.0, 1000)
    assert not verdict["assessed"]
    assert verdict["reason"] == "no_variation"


def test_thin_volume_gets_a_caveat(steady_history):
    cache.put_history("CALM.NS", steady_history)
    verdict = anomaly.assess("CALM.NS", 3.0, 200_000)
    assert verdict["unusual"]
    assert "single large trade" in verdict["message"]


def test_heavy_volume_reads_as_corroboration(steady_history):
    cache.put_history("CALM.NS", steady_history)
    verdict = anomaly.assess("CALM.NS", 3.0, 3_000_000)
    assert verdict["unusual"]
    assert "real event" in verdict["message"]


def test_downward_moves_are_flagged_too(steady_history):
    cache.put_history("CALM.NS", steady_history)
    verdict = anomaly.assess("CALM.NS", -2.5, 1_000_000)
    assert verdict["unusual"]
    assert "down" in verdict["message"]
