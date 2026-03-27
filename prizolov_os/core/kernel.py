import logging
from typing import Any, Dict

from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class Kernel:
    """
    Ядро системы - основная точка входа для выполнения задач.
    Координирует работу оркестратора и агентов.
    """
    
    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator: Orchestrator = orchestrator
        self.mode: str = "standard"
        logger.info("Kernel initialized with orchestrator")
    
    def run(self, task: str) -> Any:
        """
        Запускает выполнение задачи.
        
        Args:
            task: Текст задачи для выполнения
            
        Returns:
            Результат выполнения (список строк или строка)
        """
        if not task or not isinstance(task, str):
            logger.error(f"Invalid task: {type(task)}")
            raise ValueError("Task must be a non-empty string")
        
        logger.info(f"Starting task execution: {task[:50]}...")
        result = self.orchestrator.execute(task)
        logger.info(f"Task completed with {len(result) if isinstance(result, list) else 1} result(s)")
        
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """Возвращает текущий статус ядра."""
        logger.debug("Getting kernel status")
        return {
            "mode": self.mode,
            "orchestrator_active": self.orchestrator is not None
        }
