"""Telegram delivery: it must never raise, and must always leave a record."""

from __future__ import annotations

import pytest

from fetchers import notify


@pytest.fixture
def logged(monkeypatch):
    """Capture what would go into notifications_log."""
    rows = []

    def fake_insert(channel, message, *, event_id=None, ok=True, **kwargs):
        rows.append({"channel": channel, "message": message, "event_id": event_id, "ok": ok})

    monkeypatch.setattr(notify.repo, "insert_notification", fake_insert)
    return rows


@pytest.fixture
def configured(monkeypatch):
    """Pretend the bot credentials are present."""
    monkeypatch.setattr(
        notify.config, "require",
        lambda name: {"TELEGRAM_BOT_TOKEN": "test-token", "TELEGRAM_CHAT_ID": "42"}[name],
    )


class TestSend:
    def test_a_successful_send_reports_true(self, logged, configured, monkeypatch):
        monkeypatch.setattr(notify.http, "post_json", lambda *a, **k: {"ok": True})
        assert notify.send("NEW: CPI m/m") is True

    def test_a_successful_send_is_logged_as_ok(self, logged, configured, monkeypatch):
        monkeypatch.setattr(notify.http, "post_json", lambda *a, **k: {"ok": True})
        notify.send("NEW: CPI m/m", event_id="USD|CPI m/m|2026-10-14")
        assert logged == [
            {
                "channel": "telegram",
                "message": "NEW: CPI m/m",
                "event_id": "USD|CPI m/m|2026-10-14",
                "ok": True,
            }
        ]

    def test_it_posts_to_the_configured_chat(self, logged, configured, monkeypatch):
        captured = {}

        def capture(url, payload, **kwargs):
            captured["url"] = url
            captured["payload"] = payload
            return {"ok": True}

        monkeypatch.setattr(notify.http, "post_json", capture)
        notify.send("hello")
        assert "test-token" in captured["url"]
        assert captured["payload"]["chat_id"] == "42"
        assert captured["payload"]["text"] == "hello"

    def test_missing_credentials_do_not_raise(self, logged, monkeypatch):
        """A fetcher with no bot configured must still finish its real work."""
        from common.config import MissingConfig

        def missing(name):
            raise MissingConfig(f"{name} is not set")

        monkeypatch.setattr(notify.config, "require", missing)
        assert notify.send("NEW: CPI m/m") is False

    def test_missing_credentials_still_leave_a_record(self, logged, monkeypatch):
        from common.config import MissingConfig

        monkeypatch.setattr(
            notify.config, "require",
            lambda name: (_ for _ in ()).throw(MissingConfig(f"{name} is not set")),
        )
        notify.send("NEW: CPI m/m")
        assert logged and logged[0]["ok"] is False

    def test_a_refusal_from_telegram_reports_false(self, logged, configured, monkeypatch):
        monkeypatch.setattr(
            notify.http, "post_json", lambda *a, **k: {"ok": False, "description": "chat not found"}
        )
        assert notify.send("hi") is False
        assert logged[0]["ok"] is False

    def test_a_network_failure_reports_false(self, logged, configured, monkeypatch):
        monkeypatch.setattr(notify.http, "post_json", lambda *a, **k: None)
        assert notify.send("hi") is False
        assert logged[0]["ok"] is False

    def test_an_unexpected_exception_is_contained(self, logged, configured, monkeypatch):
        def explode(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(notify.http, "post_json", explode)
        assert notify.send("hi") is False
        assert logged[0]["ok"] is False

    def test_a_failing_log_write_does_not_break_the_send(self, configured, monkeypatch):
        def explode(*a, **k):
            raise RuntimeError("database down")

        monkeypatch.setattr(notify.repo, "insert_notification", explode)
        monkeypatch.setattr(notify.http, "post_json", lambda *a, **k: {"ok": True})
        assert notify.send("hi") is True

    @pytest.mark.parametrize("message", ["", "   ", "\n"])
    def test_empty_messages_are_not_sent(self, logged, configured, message):
        assert notify.send(message) is False
        assert logged == []

    def test_a_long_message_is_truncated_not_dropped(self, logged, configured, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            notify.http, "post_json",
            lambda url, payload, **k: captured.update(payload) or {"ok": True},
        )
        notify.send("x" * 5000)
        assert len(captured["text"]) == notify.MAX_MESSAGE_CHARS
        assert captured["text"].endswith("...")

    def test_markdown_parsing_is_off(self, logged, configured, monkeypatch):
        """Titles contain characters Telegram's Markdown would reject."""
        captured = {}
        monkeypatch.setattr(
            notify.http, "post_json",
            lambda url, payload, **k: captured.update(payload) or {"ok": True},
        )
        notify.send("CPI m/m _underscored_ *starred*")
        assert "parse_mode" not in captured


class TestSendMany:
    def test_counts_deliveries(self, logged, configured, monkeypatch):
        results = iter([{"ok": True}, {"ok": False}, {"ok": True}])
        monkeypatch.setattr(notify.http, "post_json", lambda *a, **k: next(results))
        assert notify.send_many(["a", "b", "c"]) == 2
