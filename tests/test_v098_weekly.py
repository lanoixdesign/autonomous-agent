"""v0.9.6 added weekly schedules without tests: covered here (v0.9.8)."""
import time

import pytest

from agent import schedule


def test_weekly_validation():
    s = schedule.validate({"prompt": " résume mes mails ", "weekly": {"weekday": "Friday", "at": "17:00"}})
    assert s == {"prompt": "résume mes mails", "kind": "weekly", "weekday": "fri", "at": "17:00"}
    for bad in ({"weekday": "xyz", "at": "17:00"}, {"weekday": "fri", "at": "25:00"}, "fri"):
        with pytest.raises(ValueError):
            schedule.validate({"prompt": "x", "weekly": bad})
    with pytest.raises(ValueError):
        schedule.validate({"prompt": "x", "weekly": {"weekday": "fri", "at": "17:00"}, "daily_at": "08:00"})


@pytest.mark.parametrize("day", schedule.WEEKDAYS)
def test_next_weekly_lands_on_the_day_and_time(day):
    now = time.mktime((2026, 11, 23, 12, 0, 0, 0, 0, -1))       # a Monday, noon
    nxt = schedule.next_weekly(day, "08:30", now)
    lt = time.localtime(nxt)
    assert nxt > now and lt.tm_wday == schedule.WEEKDAYS.index(day) and (lt.tm_hour, lt.tm_min) == (8, 30)
    assert nxt - now <= 7 * 86400 + 3600
    assert schedule.next_weekly(day, "08:30", nxt) - nxt >= 7 * 86400 - 3600    # then one week later


def test_weekly_schedule_is_described_and_planned():
    now = time.time()
    s = schedule.new({"prompt": "point hebdo", "weekly": {"weekday": "mon", "at": "09:00"}}, now)
    assert s["kind"] == "weekly" and s["next_run"] > now and schedule.describe(s) == "weekly on mon at 09:00"
