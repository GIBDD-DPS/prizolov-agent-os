# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""
Модуль конфигурации для Prizolov Agent OS.
Загружает настройки из переменных окружения и .env файла.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Settings:
    """
    Класс настроек приложения.
    
    Атрибуты:
        api_key: API ключ Anthropic (если не задан, SDK ищет ANTHROPIC_API_KEY сам)
        model: Модель Claude
        effort: Глубина рассуждений модели (low, medium, high, xhigh, max)
        max_tokens: Максимальная длина одного ответа модели в токенах
        workspace_dir: Рабочая папка, в которой агенты читают и пишут файлы
        db_path: Файл SQLite с памятью: диалоги, факты, уроки, версии промптов
        self_check: Самопроверка ответов: complex (только сложные задачи), always, off
        sign_output: Подписывать авторством текстовые файлы, которые создают агенты
        budget_task_usd: Лимит расходов на одну задачу в долларах (0 - без лимита)
        budget_day_usd: Лимит расходов в день в долларах (0 - без лимита)
        trace: Писать журнал трассировки
        trace_dir: Папка журналов трассировки
        trace_content: Писать в журнал полные тексты (по умолчанию - сокращённые)
        compact_at: Сжимать историю диалога после стольких токенов (0 - не сжимать)
        parallel: Сколько поручений специалистам выполнять одновременно (1 - по очереди)
        telegram_token: Токен Telegram-бота
        telegram_allowed_ids: Telegram ID, которым разрешён доступ к боту (через запятую)
        timezone: Часовой пояс для расписания задач
        api_keys: Ключи доступа к HTTP API (через запятую)
        api_host: Адрес, на котором слушает HTTP API
        api_port: Порт HTTP API
        api_workers: Сколько задач API выполнять одновременно
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        log_file: Путь к файлу логов (опционально)
        security_level: Уровень безопасности (low, medium, high)
        max_retries: Максимальное количество попыток
        timeout: Таймаут запросов в секундах
    """
    api_key: Optional[str] = None
    model: str = "claude-sonnet-5-5"
    effort: str = "medium"
    max_tokens: int = 16000
    workspace_dir: str = "workspace"
    db_path: str = "data/prizolov.db"
    self_check: str = "complex"
    sign_output: bool = True
    budget_task_usd: float = 1.0
    budget_day_usd: float = 10.0
    trace: bool = True
    trace_dir: str = "logs"
    trace_content: bool = False
    compact_at: int = 150_000
    parallel: int = 4
    telegram_token: Optional[str] = None
    telegram_allowed_ids: str = ""
    timezone: str = "Europe/Moscow"
    api_keys: str = ""
    api_host: str = "127.0.0.1"
    api_port: int = 8800
    api_workers: int = 2
    log_level: str = "INFO"
    log_file: Optional[str] = None
    security_level: str = "high"
    max_retries: int = 3
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        """
        Загружает настройки из переменных окружения.
        
        Приоритет:
        1. Переменные окружения ОС
        2. Файл .env в корне проекта
        3. Значения по умолчанию
        """
        env_file = Path(".") / ".env"

        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)

        return cls(
            api_key=_real_key(os.getenv("ANTHROPIC_API_KEY") or os.getenv("PRIZOLOV_API_KEY")),
            model=os.getenv("PRIZOLOV_MODEL", "claude-sonnet-5-5"),
            effort=os.getenv("PRIZOLOV_EFFORT", "medium"),
            max_tokens=int(os.getenv("PRIZOLOV_MAX_TOKENS", "16000")),
            workspace_dir=os.getenv("PRIZOLOV_WORKSPACE", "workspace"),
            db_path=os.getenv("PRIZOLOV_DB_PATH", "data/prizolov.db"),
            self_check=os.getenv("PRIZOLOV_SELF_CHECK", "complex"),
            sign_output=_flag("PRIZOLOV_SIGN_OUTPUT", True),
            budget_task_usd=float(os.getenv("PRIZOLOV_BUDGET_TASK_USD", "1.0")),
            budget_day_usd=float(os.getenv("PRIZOLOV_BUDGET_DAY_USD", "10.0")),
            trace=_flag("PRIZOLOV_TRACE", True),
            trace_dir=os.getenv("PRIZOLOV_TRACE_DIR", "logs"),
            trace_content=_flag("PRIZOLOV_TRACE_CONTENT", False),
            compact_at=int(os.getenv("PRIZOLOV_COMPACT_AT", "150000")),
            parallel=int(os.getenv("PRIZOLOV_PARALLEL", "4")),
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            telegram_allowed_ids=os.getenv("PRIZOLOV_TELEGRAM_ALLOWED_IDS", ""),
            timezone=os.getenv("PRIZOLOV_TIMEZONE", "Europe/Moscow"),
            api_keys=os.getenv("PRIZOLOV_API_KEYS", ""),
            api_host=os.getenv("PRIZOLOV_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("PRIZOLOV_API_PORT", "8800")),
            api_workers=int(os.getenv("PRIZOLOV_API_WORKERS", "2")),
            log_level=os.getenv("PRIZOLOV_LOG_LEVEL", "INFO"),
            log_file=os.getenv("PRIZOLOV_LOG_FILE"),
            security_level=os.getenv("PRIZOLOV_SECURITY_LEVEL", "high"),
            max_retries=int(os.getenv("PRIZOLOV_MAX_RETRIES", "3")),
            timeout=int(os.getenv("PRIZOLOV_TIMEOUT", "30")),
        )

    def get_log_level_int(self) -> int:
        """Конвертирует строковый уровень логирования в int."""
        import logging
        levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        return levels.get(self.log_level.upper(), logging.INFO)

    def validate(self) -> None:
        """
        Валидирует настройки.
        
        Raises:
            ValueError: Если настройки некорректны
        """
        if self.security_level not in ["low", "medium", "high"]:
            raise ValueError(
                f"Invalid security_level: {self.security_level}. "
                "Must be 'low', 'medium', or 'high'"
            )

        if self.self_check not in ["complex", "always", "off"]:
            raise ValueError(
                f"Invalid self_check: {self.self_check}. Must be 'complex', 'always', or 'off'"
            )

        if self.effort not in ["low", "medium", "high", "xhigh", "max"]:
            raise ValueError(
                f"Invalid effort: {self.effort}. "
                "Must be 'low', 'medium', 'high', 'xhigh', or 'max'"
            )

        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        if not 1 <= self.parallel <= 16:
            raise ValueError("parallel: от 1 до 16")

        if not 1 <= self.api_workers <= 16:
            raise ValueError("api_workers: от 1 до 16")

        if not 1 <= self.api_port <= 65535:
            raise ValueError("api_port: от 1 до 65535")

        if self.compact_at and self.compact_at < 50_000:
            raise ValueError("compact_at: минимум 50000 токенов (или 0 - не сжимать)")

        if self.budget_task_usd < 0 or self.budget_day_usd < 0:
            raise ValueError("Лимиты расходов не могут быть отрицательными")

        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("false", "0", "no", "off", "")


PLACEHOLDER_KEYS = {"your_api_key_here", "your-api-key", "sk-ant-..."}


def _real_key(value: Optional[str]) -> Optional[str]:
    """Заглушку из .env.example не считаем ключом, иначе она перекроет настоящую
    авторизацию (например, профиль `ant auth login`)."""
    if not value or value.strip() in PLACEHOLDER_KEYS:
        return None
    return value.strip()


# Глобальный экземпляр настроек
settings = Settings.from_env()
