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
SETUP_ACTION = REPO_ROOT / ".github" / "actions" / "python-env" / "action.yml"

MODULE_RE = re.compile(r"python -m fetchers\.(\w+)")
SECRET_RE = re.compile(r"\$\{\{\s*secrets\.(\w+)\s*\}\}")
CRON_RE = re.compile(r"cron:\s*\"([^\"]+)\"")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestWorkflowsExist:
    def test_the_scheduled_workflows_are_present(self):
        names = {p.name for p in WORKFLOWS}
        assert {
            "actuals-hot.yml", "actuals-fomc.yml", "actuals-catchup.yml",
            "ff-sync.yml", "reminders.yml", "prices-daily.yml",
            "calendar-skeleton.yml", "headlines.yml",
        } <= names

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

    def test_it_checks_out_and_uses_the_shared_setup(self, path):
        """Install and Python version live in one composite action.

        checkout stays in the workflow: a local composite action cannot be
        resolved until the repository it lives in has been checked out.
        """
        text = read(path)
        assert "actions/checkout@" in text, path.name
        assert "./.github/actions/python-env" in text, path.name

    def test_it_cannot_run_for_an_hour(self, path):
        assert "timeout-minutes: 5" in read(path), path.name

    def test_overlapping_runs_are_prevented(self, path):
        assert "concurrency:" in read(path), path.name

    def test_it_has_a_timeout(self, path):
        """An unbounded run can burn the free-tier minutes budget."""
        assert "timeout-minutes:" in read(path), path.name

    def test_it_can_be_run_by_hand(self, path):
        assert "workflow_dispatch:" in read(path), path.name

    def test_cron_expressions_have_five_fields(self, path):
        for expression in CRON_RE.findall(read(path)):
            assert len(expression.split()) == 5, f"{path.name}: {expression!r}"


class TestTheSharedSetup:
    def test_it_installs_the_pinned_requirements(self):
        assert "pip install -r requirements.txt" in read(SETUP_ACTION)

    def test_it_sets_up_python(self):
        assert "actions/setup-python@" in read(SETUP_ACTION)

    def test_it_caches_pip_keyed_on_requirements(self):
        """An uncached install is the slowest part of a 30-second run."""
        text = read(SETUP_ACTION)
        assert "actions/cache@" in text
        assert "hashFiles('requirements.txt')" in text

    def test_it_does_not_check_out(self):
        """A local composite action cannot run before checkout has happened."""
        assert "actions/checkout@" not in read(SETUP_ACTION)


class TestSchedules:
    EXPECTED = {
        "actuals-hot.yml": "*/5 12,13,14,15 * * 1-5",
        "actuals-fomc.yml": "*/5 17,18,19 * * 1-5",
        "actuals-catchup.yml": "0 * * * *",
        "ff-sync.yml": "*/30 * * * *",
        "reminders.yml": "*/5 * * * *",
        "prices-daily.yml": "30 21 * * 1-5",
        "calendar-skeleton.yml": "0 6 * * *",
        "headlines.yml": "*/15 * * * *",
    }

    @pytest.mark.parametrize("name,cron", sorted(EXPECTED.items()))
    def test_each_workflow_keeps_its_schedule(self, name, cron):
        assert CRON_RE.findall(read(WORKFLOW_DIR / name)) == [cron], name

    def test_the_hot_window_covers_the_us_release_times(self):
        """BLS and BEA publish at 12:30 UTC, ISM and JOLTS at 14:00."""
        cron = self.EXPECTED["actuals-hot.yml"].split()
        hours = {int(h) for h in cron[1].split(",")}
        assert {12, 14} <= hours, "the 12:30 and 14:00 UTC releases must be covered"

    def test_the_fomc_window_covers_the_statement_and_the_presser(self):
        """18:00 UTC under EDT, 19:00 under EST, press conference 30m later."""
        hours = {int(h) for h in self.EXPECTED["actuals-fomc.yml"].split()[1].split(",")}
        assert {18, 19} <= hours

    def test_the_fomc_workflow_uses_the_cheap_early_exit(self):
        """Without --fomc-only it would query FRED on 250 idle days a year."""
        assert "--fomc-only" in read(WORKFLOW_DIR / "actuals-fomc.yml")

    def test_catchup_looks_further_back_than_the_hot_path(self):
        hot = read(WORKFLOW_DIR / "actuals-hot.yml")
        catchup = read(WORKFLOW_DIR / "actuals-catchup.yml")
        assert "--days 1" in hot
        assert "--days 7" in catchup

    def test_notifying_workflows_carry_the_telegram_secrets(self):
        for name in ("ff-sync.yml", "reminders.yml"):
            secrets = set(SECRET_RE.findall(read(WORKFLOW_DIR / name)))
            assert {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"} <= secrets, name

    def test_fred_backed_workflows_carry_the_fred_key(self):
        for name in ("actuals-hot.yml", "actuals-fomc.yml", "actuals-catchup.yml",
                     "prices-daily.yml", "calendar-skeleton.yml"):
            assert "FRED_API_KEY" in set(SECRET_RE.findall(read(WORKFLOW_DIR / name))), name

    def test_every_workflow_that_writes_has_supabase_credentials(self):
        for path in WORKFLOWS:
            text = read(path)
            if not MODULE_RE.findall(text):
                continue
            secrets = set(SECRET_RE.findall(text))
            assert {"SUPABASE_URL", "SUPABASE_SERVICE_KEY"} <= secrets, path.name


class TestSecretsDocumented:
    def test_every_secret_used_is_listed_in_the_env_example(self):
        example = read(REPO_ROOT / ".env.example")
        used = set()
        for path in WORKFLOWS:
            used |= set(SECRET_RE.findall(read(path)))
        for secret in used:
            assert secret in example, f"{secret} is not in .env.example"
