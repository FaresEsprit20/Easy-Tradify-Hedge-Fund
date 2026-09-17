"""An exhausted day is penalised whichever way the trade goes.

Stored trades once the ADR was used up: fading won 12% (-0.99R), extending won
9% (-1.14R). The fade used to get a +8 bonus.
"""

import pytest

from core.adr_exhaustion import (ADR_EXHAUSTION_CONTINUATION_PENALTY,
                                 ADR_EXHAUSTION_MEANREVERSION_PENALTY,
                                 calculate_adr_exhaustion_final_score)


def adr(exhausted=True, direction="UP"):
    return {"available": True, "exhausted": exhausted, "today_net_direction": direction,
            "reason": "test"}


@pytest.mark.parametrize("side, day, expected, signal", [
    ("BUY", "UP", ADR_EXHAUSTION_CONTINUATION_PENALTY, "CONTINUATION_PENALIZED"),
    ("SELL", "DOWN", ADR_EXHAUSTION_CONTINUATION_PENALTY, "CONTINUATION_PENALIZED"),
    ("SELL", "UP", ADR_EXHAUSTION_MEANREVERSION_PENALTY, "FADE_PENALIZED"),
    ("BUY", "DOWN", ADR_EXHAUSTION_MEANREVERSION_PENALTY, "FADE_PENALIZED"),
])
def test_exhausted_day_penalised_both_ways(side, day, expected, signal):
    result = calculate_adr_exhaustion_final_score(adr(True, day), 80.0, side)
    assert result["adjustment"] == expected < 0
    assert result["signal"] == signal
    assert result["final_score"] == 80.0 + expected


def test_normal_day_untouched():
    result = calculate_adr_exhaustion_final_score(adr(False, "UP"), 80.0, "SELL")
    assert result["adjustment"] == 0.0 and result["final_score"] == 80.0
