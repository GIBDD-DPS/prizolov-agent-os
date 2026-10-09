# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Тесты prizolov init и prizolov doctor (без сети)."""

import io
import os
import stat

from dotenv import dotenv_values
from rich.console import Console

from cli.onboarding import collect_checks, run_doctor, run_init
from prizolov_os.config import Settings
from prizolov_os.market import MarketDataError
from tests.test_reports import StubMarket


def console():
    return Console(file=io.StringIO(), width=120, color_system=None)


def scripted(*answers):
    queue = list(answers)
    return lambda prompt: queue.pop(0) if queue else ""


class TestInit:
    def test_creates_env(self, tmp_path):
        env = tmp_path / ".env"
        answers = scripted("2", "5", "y", "111, 222", "y")
        secrets_ = scripted("sk-ant-test", "123:ABC")
        assert run_init(console(), answers, secrets_, env) == 0
        values = dotenv_values(env)
        assert values["ANTHROPIC_API_KEY"] == "sk-ant-test"
        assert values["PRIZOLOV_MODEL"] == "claude-opus-5-5"
        assert values["PRIZOLOV_BUDGET_DAY_USD"] == "5"
        assert values["TELEGRAM_BOT_TOKEN"] == "123:ABC"
        assert values["PRIZOLOV_TELEGRAM_ALLOWED_IDS"] == "111, 222"
        assert len(values["PRIZOLOV_API_KEYS"]) >= 32
        if os.name == "posix":
            assert stat.S_IMODE(env.stat().st_mode) == 0o600

    def test_keeps_existing_lines(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# мой комментарий\nANTHROPIC_API_KEY=sk-ant-old\nPRIZOLOV_PARALLEL=2\n")
        run_init(console(), scripted("", "", "n", "n"), scripted(""), env)
        text = env.read_text()
        assert "# мой комментарий" in text and "PRIZOLOV_PARALLEL=2" in text
        assert dotenv_values(env)["ANTHROPIC_API_KEY"] == "sk-ant-old"

    def test_rejects_bad_numbers(self, tmp_path):
        env = tmp_path / ".env"
        run_init(console(), scripted("", "много", "y", "abc", "n"), scripted("", ""), env)
        values = dotenv_values(env)
        assert "PRIZOLOV_BUDGET_DAY_USD" not in values
        assert "PRIZOLOV_TELEGRAM_ALLOWED_IDS" not in values


def settings_for(tmp_path, **kw):
    return Settings(workspace_dir=str(tmp_path / "ws"), db_path=str(tmp_path / "db" / "x.db"),
                    **kw)


class TestDoctor:
    def test_all_good(self, tmp_path):
        config = settings_for(tmp_path, api_key="sk-ant-x")
        checks = collect_checks(config, StubMarket(), key_check=lambda c: "")
        assert all(c.status == "ok" for c in checks), checks
        out = console()
        assert run_doctor(out, config, StubMarket(), key_check=lambda c: "") == 0
        assert "Всё готово" in out.file.getvalue()

    def test_bad_key_is_fatal(self, tmp_path):
        config = settings_for(tmp_path, api_key="sk-ant-x")
        assert run_doctor(console(), config, StubMarket(),
                          key_check=lambda c: "ключ не принят") == 1

    def test_missing_key_and_sources_are_warnings(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        config = settings_for(tmp_path)
        checks = {c.name: c for c in collect_checks(config, StubMarket(fail=True))}
        assert checks["Ключ Claude"].status == "warn"
        assert checks["Котировки: ЦБ РФ"].status == "warn"
        assert run_doctor(console(), config, StubMarket(fail=True)) == 0

    def test_telegram_without_whitelist_is_fatal(self, tmp_path):
        config = settings_for(tmp_path, telegram_token="1:A")
        checks = {c.name: c for c in collect_checks(config, online=False)}
        assert checks["Telegram-бот"].status == "fail"

    def test_short_api_key_is_fatal(self, tmp_path):
        config = settings_for(tmp_path, api_keys="short")
        checks = {c.name: c for c in collect_checks(config, online=False)}
        assert checks["HTTP API"].status == "fail"

    def test_offline_skips_network(self, tmp_path):
        class Exploding:
            def history(self, *a):
                raise MarketDataError("сеть")

        config = settings_for(tmp_path, api_key="sk-ant-x")
        names = [c.name for c in collect_checks(config, Exploding(), online=False)]
        assert not any(n.startswith("Котировки") for n in names)
