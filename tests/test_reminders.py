"""Reminder tiers: sent once, at the right moment, for the right events."""

from __future__ import annotations

from datetime import timedelta

import pytest

from common.timeutil import now_utc, parse_iso
from fetchers import reminders


@pytest.fixture
def fake_repo(monkeypatch):
    """A repo stub that records reads and writes, with no database behind it."""

    state = {"events": [], "queries": [], "flagged": []}

    def fetch_reminder_candidates(now, horizon, *, flag_column, min_weight=4):
        state["queries"].append(
            {"now": now, "horizon": horizon, "flag": flag_column, "min_weight": min_weight}
        )
        return [
            e
            for e in state["events"]
            if now < e["ts_utc"] <= horizon
            and e["weight"] >= min_weight
            and not e.get(flag_column)
        ]

    def mark_reminded(event_id, flag_column):
        state["flagged"].append((event_id, flag_column))
        for event in state["events"]:
            if event["id"] == event_id:
                event[flag_column] = True

    monkeypatch.setattr(reminders.repo, "fetch_reminder_candidates", fetch_reminder_candidates)
    monkeypatch.setattr(reminders.repo, "mark_reminded", mark_reminded)
    return state


@pytest.fixture
def sent(monkeypatch, telegram_on):
    messages = []
    monkeypatch.setattr(
        reminders.notify, "send", lambda m, **kw: messages.append(m) or True
    )
    return messages


def event(minutes_ahead, *, weight=5, title="CPI m/m", **flags):
    row = {
        "id": f"USD|{title}|{minutes_ahead}",
        "title": title,
        "ts_utc": now_utc() + timedelta(minutes=minutes_ahead),
        "weight": weight,
        "forecast": 0.3,
        "reminded_24h": False,
        "reminded_1h": False,
    }
    row.update(flags)
    return row


class TestTierConfiguration:
    def test_the_two_tiers_do_not_overlap(self):
        one_hour, twenty_four = reminders.TIERS
        assert one_hour.lead_minutes == 60
        assert twenty_four.floor_minutes == 60, (
            "the 24h tier must ignore events the 1h tier owns"
        )

    def test_the_one_hour_tier_runs_first(self):
        assert reminders.TIERS[0].label == "1h"

    def test_sending_the_one_hour_reminder_closes_the_24h_one(self):
        """An event discovered inside the 24h window must not fire both."""
        assert set(reminders.TIERS[0].sets) == {"reminded_1h", "reminded_24h"}

    def test_the_weight_bar_is_four(self):
        assert reminders.MIN_WEIGHT == 4


class TestRunTier:
    def test_an_event_in_the_window_is_reminded(self, fake_repo, sent):
        fake_repo["events"] = [event(30)]
        reminders.run(dry_run=False)
        assert len(sent) == 1
        assert sent[0].startswith("REMINDER 1h: CPI m/m")

    def test_the_24h_tier_catches_a_day_out_event(self, fake_repo, sent):
        fake_repo["events"] = [event(600)]
        reminders.run(dry_run=False)
        assert len(sent) == 1
        assert sent[0].startswith("REMINDER 24h:")

    def test_a_low_weight_event_is_ignored(self, fake_repo, sent):
        fake_repo["events"] = [event(30, weight=3)]
        reminders.run(dry_run=False)
        assert sent == []

    def test_a_past_event_is_ignored(self, fake_repo, sent):
        fake_repo["events"] = [event(-30)]
        reminders.run(dry_run=False)
        assert sent == []

    def test_an_event_beyond_24h_is_ignored(self, fake_repo, sent):
        fake_repo["events"] = [event(60 * 30)]
        reminders.run(dry_run=False)
        assert sent == []

    def test_a_reminder_is_sent_only_once(self, fake_repo, sent):
        """The workflow runs every 15 minutes; the flag must stop repeats."""
        fake_repo["events"] = [event(600)]
        reminders.run(dry_run=False)
        reminders.run(dry_run=False)
        reminders.run(dry_run=False)
        assert len(sent) == 1

    def test_an_event_close_by_gets_one_message_not_two(self, fake_repo, sent):
        """40 minutes out and never reminded: the 1h tier owns it alone."""
        fake_repo["events"] = [event(40)]
        reminders.run(dry_run=False)
        assert len(sent) == 1
        assert "REMINDER 1h" in sent[0]

    def test_both_tiers_fire_across_a_day(self, fake_repo, sent):
        """One event, reminded at 24h and again at 1h as time passes."""
        row = event(600)
        fake_repo["events"] = [row]
        reminders.run(dry_run=False)
        assert [m.split(":")[0] for m in sent] == ["REMINDER 24h"]

        row["ts_utc"] = now_utc() + timedelta(minutes=30)
        reminders.run(dry_run=False)
        assert [m.split(":")[0] for m in sent] == ["REMINDER 24h", "REMINDER 1h"]

    def test_flags_are_set_before_sending(self, fake_repo, sent):
        fake_repo["events"] = [event(30)]
        reminders.run(dry_run=False)
        assert ("USD|CPI m/m|30", "reminded_1h") in fake_repo["flagged"]
        assert ("USD|CPI m/m|30", "reminded_24h") in fake_repo["flagged"]

    def test_a_failed_flag_write_stops_the_send(self, fake_repo, sent, monkeypatch):
        """Better a missed reminder than one re-sent every 15 minutes."""
        def explode(event_id, flag_column):
            raise RuntimeError("database down")

        monkeypatch.setattr(reminders.repo, "mark_reminded", explode)
        fake_repo["events"] = [event(30)]
        stats = reminders.run(dry_run=False)
        assert sent == []
        assert stats.errors == 1

    def test_dry_run_sends_nothing_and_flags_nothing(self, fake_repo, sent):
        fake_repo["events"] = [event(30)]
        reminders.run(dry_run=True)
        assert sent == []
        assert fake_repo["flagged"] == []

    def test_one_failing_tier_does_not_stop_the_other(self, fake_repo, sent, monkeypatch):
        calls = {"n": 0}
        original = reminders.repo.fetch_reminder_candidates

        def flaky(now, horizon, *, flag_column, min_weight=4):
            calls["n"] += 1
            if flag_column == "reminded_1h":
                raise RuntimeError("boom")
            return original(now, horizon, flag_column=flag_column, min_weight=min_weight)

        monkeypatch.setattr(reminders.repo, "fetch_reminder_candidates", flaky)
        fake_repo["events"] = [event(600)]
        stats = reminders.run(dry_run=False)
        assert len(sent) == 1
        assert stats.errors == 1

    def test_an_undelivered_reminder_is_counted(self, fake_repo, monkeypatch, telegram_on):
        monkeypatch.setattr(reminders.notify, "send", lambda m, **kw: False)
        fake_repo["events"] = [event(30)]
        stats = reminders.run(dry_run=False)
        assert stats.errors == 1


class TestNoTelegram:
    """With no bot configured the run must change nothing.

    Flags are flipped before sending, so running for real without a token would
    mark every due event as reminded and lose the reminder permanently.
    """

    def test_it_flags_nothing(self, fake_repo, monkeypatch):
        monkeypatch.setattr(reminders.notify, "send", lambda m, **kw: True)
        fake_repo["events"] = [event(30)]
        reminders.run(dry_run=False)
        assert fake_repo["flagged"] == [], "a reminder would have been lost"

    def test_the_event_stays_due_for_a_later_run(self, fake_repo, monkeypatch):
        monkeypatch.setattr(reminders.notify, "send", lambda m, **kw: True)
        row = event(30)
        fake_repo["events"] = [row]
        reminders.run(dry_run=False)
        assert row["reminded_1h"] is False

    def test_it_still_reports_what_is_due(self, fake_repo, monkeypatch):
        monkeypatch.setattr(reminders.notify, "send", lambda m, **kw: True)
        fake_repo["events"] = [event(30)]
        stats = reminders.run(dry_run=False)
        assert stats.fetched == 1
        assert any("telegram not configured" in n for n in stats.notes)

    def test_it_is_not_counted_as_an_error(self, fake_repo, monkeypatch):
        monkeypatch.setattr(reminders.notify, "send", lambda m, **kw: True)
        fake_repo["events"] = [event(30)]
        assert reminders.run(dry_run=False).errors == 0


class TestMessageFormat:
    def test_shape(self):
        row = {
            "title": "CPI m/m",
            "ts_utc": parse_iso("2026-10-14T12:30:00Z"),
            "weight": 5,
            "forecast": 0.3,
        }
        message = reminders.format_reminder(row, reminders.TIERS[0])
        assert message == (
            "REMINDER 1h: CPI m/m - 2026-10-14T12:30:00+00:00 - weight 5 - forecast 0.3"
        )

    def test_missing_forecast_reads_n_a(self):
        row = {
            "title": "FOMC Statement",
            "ts_utc": parse_iso("2026-10-14T18:00:00Z"),
            "weight": 5,
            "forecast": None,
        }
        assert reminders.format_reminder(row, reminders.TIERS[1]).endswith("forecast n/a")

    def test_large_numbers_are_readable(self):
        row = {
            "title": "Non-Farm Employment Change",
            "ts_utc": parse_iso("2026-10-02T12:30:00Z"),
            "weight": 4,
            "forecast": 165_000.0,
        }
        message = reminders.format_reminder(row, reminders.TIERS[1])
        assert "165000" in message and "e+" not in message
