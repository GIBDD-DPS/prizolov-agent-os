#!/usr/bin/env python3
"""CLI интерфейс для Prizolov Agent OS."""

import sys
import logging
from typing import List, Optional

from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.agents.research_agent import ResearchAgent
from prizolov_os.agents.writer_agent import WriterAgent
from prizolov_os.logging_config import setup_logging


def main() -> None:
    """Точка входа CLI приложения."""
    # Настраиваем логгирование
    logger = setup_logging(level=logging.INFO)
    
    logger.info("Prizolov Agent OS CLI starting")
    print("=" * 50)
    print("Prizolov Agent OS - CLI Interface")
    print("=" * 50)
    
    orchestrator = Orchestrator()
    kernel = Kernel(orchestrator)
    
    research_agent = ResearchAgent()
    writer_agent = WriterAgent()
    
    task = "Исследуй тему ИИ-агентов и напиши краткий отчёт"
    
    logger.info(f"Task received: {task}")
    print(f"\n[>] Задача: {task}\n")
    
    try:
        result = kernel.run(task)
        
        if isinstance(result, list):
            print("\n".join(result))
        else:
            print(result)
        
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
