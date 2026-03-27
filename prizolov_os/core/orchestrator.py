import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Оркестратор управляет выполнением задач через последовательность агентов.
    """
    
    def __init__(self) -> None:
        self.agents: List[Dict[str, Any]] = []
        self.execution_log: List[Dict[str, Any]] = []
        logger.info("Orchestrator initialized")
    
    def register_agent(self, name: str, agent: Any) -> None:
        """
        Регистрирует агента в оркестраторе.
        
        Args:
            name: Имя агента
            agent: Экземпляр агента
        """
        self.agents.append({"name": name, "agent": agent})
        logger.info(f"Agent registered: {name}")
    
    def execute(self, task: str) -> List[str]:
        """
        Выполняет задачу через зарегистрированных агентов.
        
        Args:
            task: Текст задачи
            
        Returns:
            Список результатов от каждого агента
        """
        if not task or not isinstance(task, str):
            logger.error(f"Invalid task type: {type(task)}")
            raise ValueError("Task must be a non-empty string")
        
        logger.info(f"Executing task with {len(self.agents)} agent(s)")
        results: List[str] = []
        
        for agent_info in self.agents:
            agent = agent_info["agent"]
            agent_name = agent_info["name"]
            
            logger.debug(f"Executing agent: {agent_name}")
            
            try:
                result = agent.execute(task)
                results.append(f"[{agent_name}] {result}")
                self.execution_log.append({
                    "agent": agent_name,
                    "task": task,
                    "status": "success"
                })
                logger.info(f"Agent {agent_name} completed successfully")
            except Exception as e:
                results.append(f"[{agent_name}] Ошибка: {str(e)}")
                self.execution_log.append({
                    "agent": agent_name,
                    "task": task,
                    "status": "error",
                    "error": str(e)
                })
                logger.error(f"Agent {agent_name} failed: {e}", exc_info=True)
        
        logger.info(f"Orchestration completed with {len(results)} result(s)")
        return results
    
    def get_execution_log(self) -> List[Dict[str, Any]]:
        """Возвращает журнал выполненных задач."""
        logger.debug("Getting execution log")
        return self.execution_log.copy()
    
    def clear_log(self) -> None:
        """Очищает журнал выполнения."""
        self.execution_log = []
        logger.debug("Execution log cleared")
