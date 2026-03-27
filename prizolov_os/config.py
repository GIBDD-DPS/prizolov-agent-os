"""
Модуль конфигурации для Prizolov Agent OS.
Загружает настройки из переменных окружения и .env файла.
"""

import os
from typing import Optional
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Settings:
    """
    Класс настроек приложения.
    
    Атрибуты:
        api_key: API ключ для LLM (опционально)
        memory_path: Путь к файлу памяти
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR)
        log_file: Путь к файлу логов (опционально)
        security_level: Уровень безопасности (low, medium, high)
        max_retries: Максимальное количество попыток
        timeout: Таймаут запросов в секундах
    """
    api_key: Optional[str] = None
    memory_path: str = "data/memory.json"
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
        # Путь к .env файлу
        env_file = Path(".") / ".env"
        
        # Загружаем .env если существует
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)
        
        return cls(
            api_key=os.getenv("PRIZOLOV_API_KEY"),
            memory_path=os.getenv(
                "PRIZOLOV_MEMORY_PATH", 
                "data/memory.json"
            ),
            log_level=os.getenv("PRIZOLOV_LOG_LEVEL", "INFO"),
            log_file=os.getenv("PRIZOLOV_LOG_FILE"),
            security_level=os.getenv(
                "PRIZOLOV_SECURITY_LEVEL", 
                "high"
            ),
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
        
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


# Глобальный экземпляр настроек
settings = Settings.from_env()
