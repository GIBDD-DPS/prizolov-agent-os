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
            api_key=os.getenv("ANTHROPIC_API_KEY") or os.getenv("PRIZOLOV_API_KEY"),
            model=os.getenv("PRIZOLOV_MODEL", "claude-sonnet-5-5"),
            effort=os.getenv("PRIZOLOV_EFFORT", "medium"),
            max_tokens=int(os.getenv("PRIZOLOV_MAX_TOKENS", "16000")),
            workspace_dir=os.getenv("PRIZOLOV_WORKSPACE", "workspace"),
            db_path=os.getenv("PRIZOLOV_DB_PATH", "data/prizolov.db"),
            self_check=os.getenv("PRIZOLOV_SELF_CHECK", "complex"),
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

        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")

        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


# Глобальный экземпляр настроек
settings = Settings.from_env()
