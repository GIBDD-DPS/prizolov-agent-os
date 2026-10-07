#!/usr/bin/env python3
"""CLI интерфейс для Prizolov Agent OS."""

import sys

from prizolov_os.config import settings
from prizolov_os.core.kernel import Kernel
from prizolov_os.logging_config import setup_logging


def main() -> None:
    """Точка входа CLI приложения."""
    # Валидируем настройки
    try:
        settings.validate()
    except ValueError as e:
        print(f"[!] Ошибка конфигурации: {e}", file=sys.stderr)
        sys.exit(1)

    # Настраиваем логгирование
    logger = setup_logging()

    logger.info("Prizolov Agent OS CLI starting")
    logger.debug(f"Settings: security_level={settings.security_level}, "
                 f"log_level={settings.log_level}")

    print("=" * 50)
    print("Prizolov Agent OS - CLI Interface")
    print("=" * 50)
    print(f"Security Level: {settings.security_level}")
    print(f"Log Level: {settings.log_level}")
    print("=" * 50)

    kernel = Kernel.create()


    task = "Исследуй тему ИИ-агентов и напиши краткий отчёт"

    logger.info(f"Task received: {task}")
    print(f"\n[>] Задача: {task}\n")

    try:
        print(kernel.run(task).text)

        logger.info("Task execution completed successfully")

    except Exception as e:
        logger.error(f"Task execution failed: {e}", exc_info=True)
        print(f"[!] Ошибка выполнения: {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Выполнение завершено")
    print("=" * 50)

    logger.info("Prizolov Agent OS CLI shutting down")


if __name__ == "__main__":
    main()
