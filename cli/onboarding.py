# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Первый запуск и диагностика.

    prizolov init     пошаговая настройка: создаёт или дополняет .env
    prizolov doctor   проверяет ключ, источники котировок, папки и модули
"""

import importlib.util
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rich.console import Console
from rich.table import Table

from prizolov_os.__about__ import HEADER
from prizolov_os.config import PLACEHOLDER_KEYS, Settings

from .render import InputFn, confirm

MODELS = [
    ("claude-sonnet-5-5", "рекомендуется: быстро и недорого"),
    ("claude-opus-5-5", "точнее на сложных задачах, примерно вдвое дороже"),
]
ENV_HEADER = (
    "# Настройки Prizolov Agent OS (создано командой prizolov init).\n"
    "# Все параметры: .env.example и docs/configuration.md. Не коммитьте этот файл.\n"
)


# --- prizolov init -----------------------------------------------------------


def run_init(
    console: Console,
    ask: InputFn,
    secret: Optional[InputFn] = None,
    env_path: Path = Path(".env"),
) -> int:
    """Спрашивает основные настройки и записывает их в .env (права 600)."""
    secret = secret or ask
    console.print(f"[bold]{HEADER}[/]\nНастройка за минуту. Enter - оставить как есть.\n")
    values = _read_env(env_path)
    if env_path.exists():
        console.print(f"Найден {env_path}: дополню его, остальные строки сохранятся.\n")

    # Ключ Claude
    current = values.get("ANTHROPIC_API_KEY", "")
    has_key = bool(current) and current not in PLACEHOLDER_KEYS
    console.print("[bold]1. Ключ Claude API[/] - https://console.anthropic.com/settings/keys")
    key = secret("Ключ (sk-ant-...)" + (" [уже задан]" if has_key else "") + ": ").strip()
    if key:
        if not key.startswith("sk-ant-"):
            console.print("[yellow]Ключ обычно начинается с sk-ant-; проверьте его командой "
                          "prizolov doctor.[/]")
        values["ANTHROPIC_API_KEY"] = key
    elif not has_key:
        console.print("[yellow]Без ключа работают отчёты и прогнозы (prizolov report), "
                      "но не агенты.[/]")

    # Модель
    console.print("\n[bold]2. Модель[/]")
    for i, (name, note) in enumerate(MODELS, 1):
        console.print(f"  {i}. {name} - {note}")
    choice = ask(f"Номер [{_model_index(values.get('PRIZOLOV_MODEL'))}]: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(MODELS):
        values["PRIZOLOV_MODEL"] = MODELS[int(choice) - 1][0]

    # Бюджет
    console.print("\n[bold]3. Лимит расходов на Claude в день, $[/]")
    day = ask(f"Сумма [{values.get('PRIZOLOV_BUDGET_DAY_USD', '10')}]: ").strip().replace(",", ".")
    if day:
        try:
            if float(day) < 0:
                raise ValueError
            values["PRIZOLOV_BUDGET_DAY_USD"] = day
        except ValueError:
            console.print("[yellow]Нужно число, оставляю прежнее значение.[/]")

    # Telegram
    console.print("\n[bold]4. Telegram-бот[/] (необязательно)")
    if confirm(ask, "Настроить бота?"):
        token = secret("Токен от @BotFather: ").strip()
        if token:
            values["TELEGRAM_BOT_TOKEN"] = token
        ids = ask("Ваш Telegram ID (узнать у @userinfobot), через запятую: ").strip()
        if ids:
            if all(part.strip().isdigit() for part in ids.replace(";", ",").split(",")
                   if part.strip()):
                values["PRIZOLOV_TELEGRAM_ALLOWED_IDS"] = ids
            else:
                console.print("[yellow]ID - это числа; пропускаю.[/]")
        if not _is_installed("telegram"):
            console.print('Установите библиотеку: pip install "prizolov-os[telegram]"')

    # HTTP API
    console.print("\n[bold]5. HTTP API и веб-интерфейс[/] (необязательно)")
    if confirm(ask, "Создать ключ доступа?"):
        api_key = secrets.token_urlsafe(32)
        existing = [k for k in values.get("PRIZOLOV_API_KEYS", "").split(",") if k.strip()]
        values["PRIZOLOV_API_KEYS"] = ",".join([*existing, api_key])
        console.print(f"Ключ API (сохраните, он нужен для входа): [bold]{api_key}[/]")
        if not _is_installed("fastapi"):
            console.print('Установите библиотеки: pip install "prizolov-os[api]"')

    _write_env(env_path, values)
    console.print(f"\n[green]Сохранено в {env_path}[/]. Дальше:")
    console.print("  prizolov doctor              проверить, что всё работает")
    console.print("  prizolov report GOLD         отчёт по золоту без Claude")
    console.print("  prizolov chat                диалог с командой агентов")
    return 0


def _model_index(model: Optional[str]) -> int:
    names = [name for name, _ in MODELS]
    return names.index(model) + 1 if model in names else 1


def _read_env(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def _write_env(path: Path, values: Dict[str, str]) -> None:
    """Обновляет значения в .env, сохраняя остальные строки и комментарии."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [ENV_HEADER]
    written = set()
    out = []
    for line in lines:
        name = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith(
            "#") else None
        if name in values:
            out.append(f"{name}={_quote(values[name])}")
            written.add(name)
        else:
            out.append(line)
    out += [f"{k}={_quote(v)}" for k, v in values.items() if k not in written]
    path.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _quote(value: str) -> str:
    return f'"{value}"' if any(c in value for c in " #'\"") else value


# --- prizolov doctor ---------------------------------------------------------


@dataclass
class Check:
    name: str
    status: str  # ok, warn, fail
    detail: str


KeyCheck = Callable[[Settings], str]


def run_doctor(
    console: Console,
    config: Settings,
    market: Any = None,
    key_check: Optional[KeyCheck] = None,
    online: bool = True,
    tenders_fetch: Any = None,
) -> int:
    """Проверяет установку. Код выхода 1, если есть критичная ошибка."""
    checks = collect_checks(config, market, key_check, online, tenders_fetch)
    table = Table(title=f"{HEADER}\nДиагностика", show_lines=False)
    table.add_column("")
    table.add_column("Проверка")
    table.add_column("Результат")
    marks = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}
    for check in checks:
        table.add_row(marks[check.status], check.name, check.detail)
    console.print(table)
    failed = [c for c in checks if c.status == "fail"]
    if failed:
        console.print(f"[red]Критичных проблем: {len(failed)}.[/] Настройка: prizolov init")
        return 1
    if any(c.status == "warn" for c in checks):
        console.print("[yellow]Работать можно; посмотрите предупреждения (!) выше.[/]")
    else:
        console.print("[green]Всё готово к работе.[/]")
    return 0


def collect_checks(
    config: Settings,
    market: Any = None,
    key_check: Optional[KeyCheck] = None,
    online: bool = True,
    tenders_fetch: Any = None,
) -> List[Check]:
    checks: List[Check] = []
    version = sys.version_info
    checks.append(Check(
        "Python", "ok" if version >= (3, 10) else "fail",
        f"{version.major}.{version.minor}.{version.micro}"
        + ("" if version >= (3, 10) else " - нужен 3.10 или новее"),
    ))
    try:
        config.validate()
        checks.append(Check("Настройки", "ok", "корректны"))
    except ValueError as e:
        checks.append(Check("Настройки", "fail", str(e)))

    if not config.api_key and not os.getenv("ANTHROPIC_AUTH_TOKEN"):
        checks.append(Check("Ключ Claude", "warn",
                            "не задан: агенты не работают, отчёты - работают (prizolov init)"))
    elif online:
        error = (key_check or check_anthropic_key)(config)
        checks.append(Check("Ключ Claude", "fail" if error else "ok",
                            error or f"принят, модель {config.model}"))
    else:
        checks.append(Check("Ключ Claude", "ok", "задан (не проверялся)"))

    checks.append(_writable("Рабочая папка", Path(config.workspace_dir)))
    checks.append(_writable("Папка базы данных", Path(config.db_path).parent))

    if online:
        checks += _sources(market)
        checks.append(_tenders(tenders_fetch))

    checks.append(_telegram(config))
    checks.append(_api(config))
    return checks


def check_anthropic_key(config: Settings) -> str:
    """Пустая строка - ключ работает; иначе описание проблемы."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.api_key, max_retries=0, timeout=15)
        client.models.retrieve(config.model)
        return ""
    except Exception as e:  # noqa: BLE001 - любую ошибку показываем пользователю
        name = type(e).__name__
        if name == "AuthenticationError":
            return "ключ не принят: проверьте его в console.anthropic.com"
        if name == "NotFoundError":
            return f"модель {config.model} недоступна для этого ключа"
        if name == "PermissionDeniedError":
            return "нет доступа: проверьте баланс и права ключа"
        return f"нет связи с API Anthropic: {e}"


def _writable(name: str, path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".prizolov-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check(name, "ok", str(path.resolve()))
    except OSError as e:
        return Check(name, "fail", f"{path}: нет записи ({e})")


def _sources(market: Any = None) -> List[Check]:
    from prizolov_os.market import MarketData

    market = market or MarketData()
    result = []
    for label, source, symbol in (
        ("ЦБ РФ", "cbr", "USD"), ("Мосбиржа", "moex", "SBER"), ("Yahoo Finance", "yahoo", "GC=F"),
    ):
        try:
            series = market.history(source, symbol, 14)
            result.append(Check(f"Котировки: {label}", "ok",
                                f"{symbol} = {series.closes[-1]:,.2f} на {series.dates[-1]}"
                                .replace(",", " ")))
        except Exception as e:  # noqa: BLE001 - любой сбой источника - предупреждение
            result.append(Check(f"Котировки: {label}", "warn", f"недоступно: {e}"))
    return result


def _tenders(fetch: Any = None) -> Check:
    from prizolov_os.tenders import TenderSearch

    try:
        found = TenderSearch(fetch=fetch).search("поставка", limit=1)
        return Check("Госзакупки (ЕИС)", "ok", f"лента отвечает, закупок в выдаче: {len(found)}")
    except Exception as e:  # noqa: BLE001 - любой сбой площадки - предупреждение
        return Check("Госзакупки (ЕИС)", "warn",
                     f"недоступно: {e}. Документацию закупок можно разбирать и без поиска")


def _telegram(config: Settings) -> Check:
    if not config.telegram_token:
        return Check("Telegram-бот", "ok", "не настроен (необязательно)")
    if not config.telegram_allowed_ids.strip():
        return Check("Telegram-бот", "fail",
                     "нет PRIZOLOV_TELEGRAM_ALLOWED_IDS: бот не запустится")
    if not _is_installed("telegram"):
        return Check("Telegram-бот", "fail", 'нет библиотеки: pip install "prizolov-os[telegram]"')
    return Check("Telegram-бот", "ok", "настроен: prizolov telegram")


def _api(config: Settings) -> Check:
    keys = [k.strip() for k in config.api_keys.replace(";", ",").split(",") if k.strip()]
    if not keys:
        return Check("HTTP API", "ok", "не настроен (необязательно)")
    if any(len(k) < 16 for k in keys):
        return Check("HTTP API", "fail", "ключи в PRIZOLOV_API_KEYS короче 16 символов")
    if not _is_installed("fastapi"):
        return Check("HTTP API", "fail", 'нет библиотек: pip install "prizolov-os[api]"')
    return Check("HTTP API", "ok",
                 f"настроен: prizolov api → http://{config.api_host}:{config.api_port}")


def _is_installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


__all__ = ["Check", "collect_checks", "run_doctor", "run_init"]
