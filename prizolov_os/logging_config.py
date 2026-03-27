import logging
import sys
from typing import Optional
from .config import settings


def setup_logging(
    level: Optional[int] = None,
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> logging.Logger:
    """
    Настраивает логгирование для всего приложения.
    
    Args:
        level: Уровень логирования (если None, берётся из config)
        log_file: Путь к файлу для записи логов (если None, берётся из config)
        format_string: Формат сообщений логов
        
    Returns:
        Настроенный logger
    """
    if level is None:
        level = settings.get_log_level_int()
    
    if log_file is None:
        log_file = settings.log_file
    
    if format_string is None:
        format_string = (
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
    
    logger = logging.getLogger("prizolov_os")
    logger.setLevel(level)
    logger.handlers.clear()
    
    formatter = logging.Formatter(format_string)
    
    # Консольный обработчик
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Файловый обработчик (если указан)
    if log_file:
        # Создаём директорию если не существует
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


logger = setup_logging()
