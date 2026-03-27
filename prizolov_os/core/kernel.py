from typing import Any, Optional, Dict
from ..core.orchestrator import Orchestrator


class Kernel:
    """
    Ядро системы - основная точка входа для выполнения задач.
    Координирует работу оркестратора и агентов.
    """
    
    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator: Orchestrator = orchestrator
        self.mode: str = "standard"
    
    def run(self, task: str) -> Any:
        """
        Запускает выполнение задачи.
        
        Args:
            task: Текст задачи для выполнения
            
        Returns:
            Результат выполнения (список строк или строка)
        """
        if not task or not isinstance(task, str):
            raise ValueError("Task must be a non-empty string")
        
        return self.orchestrator.execute(task)
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус ядра."""
        return {
            "mode": self.mode,
            "orchestrator_active": self.orchestrator is not None
        }
