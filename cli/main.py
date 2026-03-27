#!/usr/bin/env python3
"""CLI интерфейс для Prizolov Agent OS."""

import sys
from typing import List, Optional

from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.agents.research_agent import ResearchAgent
from prizolov_os.agents.writer_agent import WriterAgent


def main():
    """Точка входа CLI приложения."""
    print("=" * 50)
    print("Prizolov Agent OS - CLI Interface")
    print("=" * 50)
    
    # Инициализация компонентов
    orchestrator = Orchestrator()
    kernel = Kernel(orchestrator)
    
    # Создание агентов
    research_agent = ResearchAgent()
    writer_agent = WriterAgent()
    
    # Пример выполнения задачи
    task = "Исследуй тему ИИ-агентов и напиши краткий отчёт"
    
    print(f"\n[>] Задача: {task}\n")
    
    try:
        # Выполнение через ядро
        result = kernel.run(task)
        
        # ✅ ИСПРАВЛЕННЫЙ ВЫВОД (с обратным слэшем!)
        if isinstance(result, list):
            print("\n".join(result))
        else:
            print(result)
            
    except Exception as e:
        print(f"[!] Ошибка выполнения: {e}", file=sys.stderr)
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("Выполнение завершено")
    print("=" * 50)


if __name__ == "__main__":
    main()