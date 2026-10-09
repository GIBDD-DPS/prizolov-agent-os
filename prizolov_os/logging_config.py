# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

import logging
import sys
from pathlib import Path
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

    # Консоль - по уровню команды; файл - по PRIZOLOV_LOG_LEVEL.
    file_level = settings.get_log_level_int()
    logger = logging.getLogger("prizolov_os")
    logger.setLevel(min(level, file_level) if log_file else level)
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
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


logger = setup_logging()
