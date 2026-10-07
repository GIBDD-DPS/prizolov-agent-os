"""Ядро системы: Директор, специалисты, память и самосовершенствование."""

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from ..agent import Agent, AgentResult, add_usage
from ..agents import create_specialists
from ..config import settings
from ..improvement import (
    Critic,
    LessonExtractor,
    PromptImprover,
    PromptProposal,
    Review,
    build_tool,
    format_lessons,
    propose_tool_tool,
    revision_request,
)
from ..llm import LLMClient, create_client
from ..market import MarketData
from ..memory import APPROVED, PENDING, REJECTED, CustomToolRecord, Lesson, PromptVersion, Store
from ..tools import Approver, memory_tools
from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)

SELF_CHECK_MODES = ("complex", "always", "off")
# Сколько новых уроков должно накопиться, чтобы предложить улучшить промпт.
PROMPT_IMPROVEMENT_THRESHOLD = 5


class Kernel:
    """Ядро Prizolov OS.

    Пример:
        kernel = Kernel.create(approver=ask_user)
        print(kernel.chat("Спрогнозируй курс доллара на месяц").text)
        kernel.feedback(positive=False, comment="Не указал источник данных")
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        store: Optional[Store] = None,
        llm: Optional[LLMClient] = None,
        self_check: str = "off",
        session_id: Optional[str] = None,
    ) -> None:
        if self_check not in SELF_CHECK_MODES:
            raise ValueError(f"self_check должен быть одним из {SELF_CHECK_MODES}")
        self.orchestrator: Orchestrator = orchestrator
        self.store: Store = store or Store()
        self.mode: str = "standard"
        self.self_check = self_check
        self.session_id: str = session_id or _new_session_id()
        self.last_review: Optional[Review] = None
        self._llm = llm
        self._last: Optional[Tuple[str, str]] = None
        # Исходные промпты из кода: к ним возвращает откат версий.
        self._default_prompts = {name: a.system_prompt for name, a in self.agents.items()}
        self._setup_agents()
        logger.info("Kernel initialized with orchestrator")

    @classmethod
    def create(
        cls,
        *,
        llm: Optional[LLMClient] = None,
        approver: Optional[Approver] = None,
        workspace_dir: Optional[Union[str, Path]] = None,
        market: Optional[MarketData] = None,
        store: Optional[Store] = None,
        self_check: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "Kernel":
        """Собирает ядро со всеми специалистами по настройкам."""
        specialists = create_specialists(llm, workspace_dir, approver, market)
        return cls(
            Orchestrator(specialists, llm=llm, approver=approver),
            store=store or Store(settings.db_path),
            llm=llm,
            self_check=self_check or settings.self_check,
            session_id=session_id,
        )

    @property
    def agents(self) -> Dict[str, Agent]:
        """Все агенты: Директор и специалисты."""
        return {"director": self.orchestrator.director, **self.orchestrator.specialists}

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = create_client()
        return self._llm

    # --- Задачи и диалог -----------------------------------------------------

    def run(self, task: str) -> AgentResult:
        """Решает задачу с чистого листа (без сохранения диалога)."""
        logger.info(f"Starting task execution: {str(task)[:50]}")
        result = self.orchestrator.run(task)
        return self._after_answer(task, result)

    def chat(self, message: str) -> AgentResult:
        """Продолжает диалог и сохраняет его в памяти."""
        result = self.orchestrator.chat(message)
        result = self._after_answer(message, result)
        history = self.orchestrator.director.history
        if history:
            self.store.save_session(self.session_id, history, title=message[:80])
        return result

    def reset(self) -> None:
        """Начинает новый диалог (старый остаётся в памяти)."""
        self.orchestrator.reset()
        self.session_id = _new_session_id()
        self._last = None

    def resume(self, session_id: str) -> int:
        """Продолжает сохранённый диалог. Возвращает число сообщений в нём."""
        messages = self.store.load_session(session_id)
        if messages is None:
            raise ValueError(f"Диалог '{session_id}' не найден")
        self.orchestrator.director.history = messages
        self.session_id = session_id
        return len(messages)

    def get_status(self) -> Dict[str, Any]:
        """Текущий статус ядра."""
        return {
            "mode": self.mode,
            "orchestrator_active": self.orchestrator is not None,
            "specialists": list(self.orchestrator.specialists),
            "delegations": len(self.orchestrator.execution_log),
            "session_id": self.session_id,
            "self_check": self.self_check,
            "facts": len(self.store.list_facts()),
            "lessons": len(self.store.list_lessons()),
            "pending_tools": len(self.store.list_custom_tools(PENDING)),
        }

    # --- Самопроверка и уроки ------------------------------------------------

    def _after_answer(self, task: str, result: AgentResult) -> AgentResult:
        self.last_review = None
        if self._should_check(result):
            result = self._self_check(task, result)
        self._last = (task, result.text)
        return result

    def _should_check(self, result: AgentResult) -> bool:
        if not result.completed or self.self_check == "off":
            return False
        return self.self_check == "always" or bool(self.orchestrator.last_run_delegations)

    def _self_check(self, task: str, result: AgentResult) -> AgentResult:
        critic = Critic(self.llm)
        evidence = [
            f"[{d.agent}] Поручение: {d.task}\nРезультат: {d.result or d.error}"
            for d in self.orchestrator.last_run_delegations
        ]
        review = critic.review(task, result.text, evidence)
        self.last_review = review
        add_usage(result.usage, review.usage)
        logger.info(f"Self-check score: {review.score}")
        if not critic.needs_revision(review):
            return result

        if review.lesson:
            self.store.add_lesson("director", review.lesson, source="critic")
        revised = self.orchestrator.followup(result.messages, revision_request(review))
        add_usage(revised.usage, result.usage)
        revised.tool_results = result.tool_results + revised.tool_results
        revised.iterations += result.iterations
        return revised

    def feedback(self, positive: bool, comment: str = "") -> Optional[Lesson]:
        """Оценка последнего ответа. Из замечания формируется урок для агента."""
        if self._last is None:
            raise ValueError("Ещё нет ответа, который можно оценить")
        if positive and not comment.strip():
            return None
        task, answer = self._last
        extracted = LessonExtractor(self.llm).from_feedback(
            task, answer, positive, comment, list(self.agents)
        )
        if extracted is None:
            return None
        source = "feedback+" if positive else "feedback-"
        lesson_id = self.store.add_lesson(extracted.agent, extracted.text, source)
        return next(item for item in self.store.list_lessons() if item.id == lesson_id)

    # --- Версии промптов -----------------------------------------------------

    def improvement_candidates(self) -> List[Tuple[str, int]]:
        """Агенты, у которых накопилось достаточно новых уроков для улучшения промпта."""
        counts = [(name, self.store.lessons_since_last_prompt(name)) for name in self.agents]
        return [(name, n) for name, n in counts if n >= PROMPT_IMPROVEMENT_THRESHOLD]

    def propose_prompt(self, agent: str) -> Tuple[PromptVersion, PromptProposal]:
        """Просит модель встроить уроки в промпт агента. Промпт меняется только после
        approve_prompt()."""
        target = self._agent(agent)
        proposal = PromptImprover(self.llm).propose(
            agent, target.system_prompt, self.store.list_lessons(agent)
        )
        if proposal is None:
            raise RuntimeError("Модель не смогла предложить новую версию промпта")
        note = "; ".join(proposal.changes)
        version_id = self.store.propose_prompt(agent, proposal.prompt, note)
        return self.store.get_prompt_version(version_id), proposal  # type: ignore[return-value]

    def approve_prompt(self, version_id: int) -> PromptVersion:
        version = self.store.activate_prompt(version_id)
        self._agent(version.agent).system_prompt = version.prompt
        return version

    def reject_prompt(self, version_id: int) -> None:
        self.store.reject_prompt(version_id)

    def rollback_prompt(self, agent: str) -> Optional[PromptVersion]:
        """Возвращает предыдущую версию промпта (None - исходный промпт из кода)."""
        previous = self.store.rollback_prompt(agent)
        self._agent(agent).system_prompt = (
            previous.prompt if previous else self._default_prompts[agent]
        )
        return previous

    # --- Инструменты, предложенные агентами ----------------------------------

    def pending_tools(self) -> List[CustomToolRecord]:
        return self.store.list_custom_tools(PENDING)

    def approve_tool(self, name: str) -> CustomToolRecord:
        """Подключает инструмент после того, как человек проверил его код."""
        record = self.store.get_custom_tool(name)
        if record is None or record.status != PENDING:
            raise ValueError(f"Нет инструмента '{name}', ожидающего проверки")
        director = self.orchestrator.director
        if name in director.tools:
            raise ValueError(f"Инструмент '{name}' уже есть")
        director.tools.add(build_tool(record))
        self.store.set_custom_tool_status(name, APPROVED)
        return record

    def reject_tool(self, name: str) -> None:
        self.store.set_custom_tool_status(name, REJECTED)

    # --- Настройка агентов ---------------------------------------------------

    def _setup_agents(self) -> None:
        director = self.orchestrator.director
        for tool in memory_tools(self.store):
            director.tools.add(tool)
        director.tools.add(propose_tool_tool(self.store, lambda: director.tools.names()))
        for record in self.store.list_custom_tools(APPROVED):
            if record.name not in director.tools:
                director.tools.add(build_tool(record))

        for name, agent in self.agents.items():
            active = self.store.active_prompt(name)
            if active:
                agent.system_prompt = active.prompt
            agent.context_provider = self._lessons_provider(name)

    def _lessons_provider(self, agent: str):
        def provide(query: str) -> str:
            return format_lessons(self.store.relevant_lessons(agent, query))

        return provide

    def _agent(self, name: str) -> Agent:
        agent = self.agents.get(name)
        if agent is None:
            raise ValueError(f"Нет агента '{name}'. Доступны: {', '.join(self.agents)}")
        return agent


def _new_session_id() -> str:
    return uuid.uuid4().hex[:12]
