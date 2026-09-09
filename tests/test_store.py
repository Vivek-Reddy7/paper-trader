"""Store tests.

The idempotency test is the important one. Re-ingesting a range you
already have is the normal case, not an edge case, and double-counting
bars would silently corrupt every backtest that followed.
"""

from datetime import date

import pytest

from paper_trader.datasource.base import Bar
from paper_trader.storage.store import BarStore


def make_bar(day: date, close: float = 100.0, symbol: str = "TEST") -> Bar:
    return Bar(
        symbol=symbol,
        day=day,
        open=close - 1,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=1_000,
    )


@pytest.fixture
def store(tmp_path):
    return BarStore(tmp_path / "test.db")


def test_upsert_then_load_roundtrip(store):
    bars = [make_bar(date(2026, 1, 5)), make_bar(date(2026, 1, 6), close=101.0)]
    store.upsert(bars)

    loaded = store.load("TEST", date(2026, 1, 1), date(2026, 1, 31))
    assert len(loaded) == 2
    assert loaded[0].day == date(2026, 1, 5)
    assert loaded[1].close == 101.0


def test_upsert_is_idempotent(store):
    """Ingesting the same range twice must not duplicate rows."""
    bars = [make_bar(date(2026, 1, 5)), make_bar(date(2026, 1, 6))]

    store.upsert(bars)
    assert store.count("TEST") == 2

    store.upsert(bars)
    assert store.count("TEST") == 2

    store.upsert(bars)
    assert store.count("TEST") == 2


def test_upsert_updates_corrected_data(store):
    """A re-fetch with corrected values should overwrite, not duplicate."""
    store.upsert([make_bar(date(2026, 1, 5), close=100.0)])
    store.upsert([make_bar(date(2026, 1, 5), close=105.0)])

    loaded = store.load("TEST", date(2026, 1, 5), date(2026, 1, 5))
    assert len(loaded) == 1
    assert loaded[0].close == 105.0


def test_load_respects_date_range(store):
    store.upsert([make_bar(date(2026, 1, d)) for d in (5, 6, 7, 8)])

    loaded = store.load("TEST", date(2026, 1, 6), date(2026, 1, 7))
    assert [b.day.day for b in loaded] == [6, 7]


def test_load_is_ordered_ascending(store):
    # Insert deliberately out of order.
    store.upsert([make_bar(date(2026, 1, 8)), make_bar(date(2026, 1, 5)), make_bar(date(2026, 1, 6))])

    loaded = store.load("TEST", date(2026, 1, 1), date(2026, 1, 31))
    assert [b.day.day for b in loaded] == [5, 6, 8]


def test_symbols_are_isolated(store):
    store.upsert([make_bar(date(2026, 1, 5), symbol="AAA")])
    store.upsert([make_bar(date(2026, 1, 5), symbol="BBB")])

    assert store.count("AAA") == 1
    assert store.count("BBB") == 1
    assert len(store.load("AAA", date(2026, 1, 1), date(2026, 1, 31))) == 1


def test_missing_weekdays_flags_gaps(store):
    # Mon 5th and Wed 7th present, Tue 6th absent.
    store.upsert([make_bar(date(2026, 1, 5)), make_bar(date(2026, 1, 7))])

    missing = store.missing_weekdays("TEST", date(2026, 1, 5), date(2026, 1, 7))
    assert missing == [date(2026, 1, 6)]


def test_missing_weekdays_ignores_weekends(store):
    # Fri 2nd and Mon 5th Jan 2026; the 3rd and 4th are Sat/Sun.
    store.upsert([make_bar(date(2026, 1, 2)), make_bar(date(2026, 1, 5))])

    assert store.missing_weekdays("TEST", date(2026, 1, 2), date(2026, 1, 5)) == []


def test_upsert_empty_list_is_a_noop(store):
    assert store.upsert([]) == 0
    assert store.count("TEST") == 0


def test_bar_rejects_high_below_low():
    with pytest.raises(ValueError, match="high"):
        Bar(symbol="X", day=date(2026, 1, 5), open=10, high=5, low=8, close=9, volume=1)


def test_bar_rejects_close_outside_range():
    with pytest.raises(ValueError, match="close"):
        Bar(symbol="X", day=date(2026, 1, 5), open=10, high=12, low=9, close=50, volume=1)


def test_bar_rejects_negative_volume():
    with pytest.raises(ValueError, match="volume"):
        Bar(symbol="X", day=date(2026, 1, 5), open=10, high=12, low=9, close=11, volume=-5)
