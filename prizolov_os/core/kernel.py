"""Ядро системы: точка входа, которая собирает Директора и специалистов."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..agent import AgentResult
from ..agents import create_specialists
from ..llm import LLMClient
from ..market import MarketData
from ..tools import Approver
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


class Kernel:
    """Ядро Prizolov OS.

    Пример:
        kernel = Kernel.create(approver=ask_user)
        print(kernel.run("Спрогнозируй курс доллара на месяц").text)
    """

    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator: Orchestrator = orchestrator
        self.mode: str = "standard"
        logger.info("Kernel initialized with orchestrator")

    @classmethod
    def create(
        cls,
        *,
        llm: Optional[LLMClient] = None,
        approver: Optional[Approver] = None,
        workspace_dir: Optional[Union[str, Path]] = None,
        market: Optional[MarketData] = None,
    ) -> "Kernel":
        """Собирает ядро со всеми специалистами по настройкам."""
        specialists = create_specialists(llm, workspace_dir, approver, market)
        return cls(Orchestrator(specialists, llm=llm, approver=approver))

    def run(self, task: str) -> AgentResult:
        """Решает задачу с чистого листа."""
        logger.info(f"Starting task execution: {str(task)[:50]}")
        return self.orchestrator.run(task)

    def chat(self, message: str) -> AgentResult:
        """Продолжает диалог."""
        return self.orchestrator.chat(message)

    def reset(self) -> None:
        self.orchestrator.reset()

    def get_status(self) -> Dict[str, Any]:
        """Текущий статус ядра."""
        return {
            "mode": self.mode,
            "orchestrator_active": self.orchestrator is not None,
            "specialists": list(self.orchestrator.specialists),
            "delegations": len(self.orchestrator.execution_log),
        }
