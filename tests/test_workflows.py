"""The scheduled workflows must stay in step with the code they run.

Parsed with regular expressions rather than PyYAML so the suite keeps to the
dependencies in requirements.txt. These are cheap guards against the failure
mode that is invisible locally: a fetcher renamed, or a secret referenced that
nobody has added, discovered only when a cron run fails at 07:00 UTC.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from common.config import KNOWN_VARS

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
FETCHERS_DIR = REPO_ROOT / "fetchers"

WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))

MODULE_RE = re.compile(r"python -m fetchers\.(\w+)")
SECRET_RE = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")
CRON_RE = re.compile(r"cron:\s*\"([^\"]+)\"")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWorkflowsExist:
    def test_the_three_scheduled_workflows_are_present(self):
        names = {p.name for p in WORKFLOWS}
        assert {"calendar-sync.yml", "reminders.yml", "daily.yml"} <= names

    def test_each_has_a_schedule_or_is_the_test_workflow(self):
        for path in WORKFLOWS:
            text = read(path)
            assert "schedule:" in text or path.name == "tests.yml", path.name


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
class TestEachWorkflow:
    def test_every_module_it_runs_exists(self, path):
        for module in MODULE_RE.findall(read(path)):
            assert (FETCHERS_DIR / f"{module}.py").exists(), (
                f"{path.name} runs fetchers.{module}, which does not exist"
            )

    def test_every_module_it_runs_has_a_main(self, path):
        for module in MODULE_RE.findall(read(path)):
            source = (FETCHERS_DIR / f"{module}.py").read_text(encoding="utf-8")
            assert "def main()" in source, f"fetchers.{module} has no main()"
            assert '__name__ == "__main__"' in source, (
                f"fetchers.{module} is not runnable with python -m"
            )

    def test_every_secret_is_one_the_code_knows(self, path):
        for secret in SECRET_RE.findall(read(path)):
            assert secret in KNOWN_VARS, (
                f"{path.name} references secret {secret}, which is not in "
                f"common.config.KNOWN_VARS"
            )

    def test_it_installs_the_pinned_requirements(self, path):
        assert "pip install -r requirements.txt" in read(path), path.name

    def test_it_checks_out_and_sets_up_python(self, path):
        text = read(path)
        assert "actions/checkout@" in text
        assert "actions/setup-python@" in text

    def test_it_has_a_timeout(self, path):
        """An unbounded run can burn the free-tier minutes budget."""
        assert "timeout-minutes:" in read(path), path.name

    def test_it_can_be_run_by_hand(self, path):
        assert "workflow_dispatch:" in read(path), path.name

    def test_cron_expressions_have_five_fields(self, path):
        for expression in CRON_RE.findall(read(path)):
            assert len(expression.split()) == 5, f"{path.name}: {expression!r}"


class TestSchedules:
    def test_calendar_sync_runs_hourly(self):
        assert CRON_RE.findall(read(WORKFLOW_DIR / "calendar-sync.yml")) == ["0 * * * *"]

    def test_reminders_run_every_fifteen_minutes(self):
        assert CRON_RE.findall(read(WORKFLOW_DIR / "reminders.yml")) == ["*/15 * * * *"]

    def test_daily_runs_once_a_day(self):
        expressions = CRON_RE.findall(read(WORKFLOW_DIR / "daily.yml"))
        assert len(expressions) == 1
        minute, hour, *rest = expressions[0].split()
        assert rest == ["*", "*", "*"]
        assert minute.isdigit() and hour.isdigit()

    def test_the_daily_job_runs_all_three_of_its_steps(self):
        modules = MODULE_RE.findall(read(WORKFLOW_DIR / "daily.yml"))
        assert set(modules) == {"calendar_skeleton", "fred_actuals", "prices_daily"}

    def test_the_daily_job_loads_prices_after_the_events_it_tags(self):
        """prices_daily also tags regimes, so it must run last."""
        modules = MODULE_RE.findall(read(WORKFLOW_DIR / "daily.yml"))
        assert modules.index("calendar_skeleton") < modules.index("prices_daily")

    def test_notifying_workflows_carry_the_telegram_secrets(self):
        for name in ("calendar-sync.yml", "reminders.yml"):
            secrets = set(SECRET_RE.findall(read(WORKFLOW_DIR / name)))
            assert {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"} <= secrets, name

    def test_fred_backed_workflows_carry_the_fred_key(self):
        secrets = set(SECRET_RE.findall(read(WORKFLOW_DIR / "daily.yml")))
        assert "FRED_API_KEY" in secrets

    def test_every_workflow_that_writes_has_supabase_credentials(self):
        for path in WORKFLOWS:
            text = read(path)
            if not MODULE_RE.findall(text):
                continue
            secrets = set(SECRET_RE.findall(text))
            assert {"SUPABASE_URL", "SUPABASE_SERVICE_KEY"} <= secrets, path.name

    def test_overlapping_runs_are_prevented(self):
        """Two concurrent runs would diff the same state and double-send."""
        for name in ("calendar-sync.yml", "reminders.yml", "daily.yml"):
            assert "concurrency:" in read(WORKFLOW_DIR / name), name


class TestSecretsDocumented:
    def test_every_secret_used_is_listed_in_the_env_example(self):
        example = read(REPO_ROOT / ".env.example")
        used = set()
        for path in WORKFLOWS:
            used |= set(SECRET_RE.findall(read(path)))
        for secret in used:
            assert secret in example, f"{secret} is not in .env.example"
