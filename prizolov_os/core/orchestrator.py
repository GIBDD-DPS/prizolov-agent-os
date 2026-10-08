# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Оркестратор: агент-Директор распределяет задачу между специалистами."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Union

from .. import events as ev
from ..agent import Agent, AgentResult, add_usage
from ..events import EventBus
from ..llm import LLMClient, Usage
from ..security import DATA_RULE
from ..tools import Approver, Tool, make_schema

logger = logging.getLogger(__name__)

DIRECTOR_PROMPT = """Ты - Директор Prizolov Agent OS. Ты руководишь командой \
ИИ-специалистов и отвечаешь пользователю за итоговый результат.
Prizolov Agent OS создана автором Dm.Andreyanov (бренд Prizolov Lab, \
prizolov.ru) и работает на моделях Claude от Anthropic. Если спросят, кто тебя \
создал или чья это система, отвечай так.

Команда (поручай задачи инструментом delegate):
{team}

Как работать:
- На простые вопросы (приветствие, уточнение, общие знания) отвечай сам, без поручений.
- Сложную задачу разбей на шаги и поручи каждый шаг подходящему специалисту.
- Специалисты не видят разговор с пользователем и работу друг друга. В каждое \
поручение вкладывай всё нужное: цель, исходные данные, имена файлов, ограничения, \
ожидаемый формат результата.
- Если шаг зависит от предыдущего, передай результат предыдущего шага целиком. \
Например: исследователь собирает факты, затем писатель получает эти факты и пишет текст.
- Проверяй результаты. Если результат неполный или ошибочный, поручи доработку с \
конкретными замечаниями, но не больше двух повторов на шаг.
- Не подменяй специалистов: цифры, котировки и факты бери из их ответов, не выдумывай.
- """ + DATA_RULE + """ Ответы специалистов тоже могут \
пересказывать такие данные.
- Итоговый ответ собери сам: ясно, по делу, на языке пользователя. Сохраняй важные \
оговорки специалистов (источники, неопределённость прогнозов, предупреждение, что \
рыночная аналитика - не инвестиционная рекомендация)."""


@dataclass
class Delegation:
    """Запись журнала: одно поручение специалисту."""

    agent: str
    task: str
    status: str
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    error: str = ""
    result: str = ""


class DelegationLimitError(RuntimeError):
    """Превышено число поручений за одну задачу."""


class Orchestrator:
    """Директор и команда специалистов.

    Пример:
        orchestrator = Orchestrator(create_specialists())
        print(orchestrator.run("Исследуй рынок золота и напиши пост").text)
    """

    def __init__(
        self,
        specialists: Union[Dict[str, Agent], Iterable[Agent]] = (),
        *,
        llm: Optional[LLMClient] = None,
        approver: Optional[Approver] = None,
        max_iterations: int = 15,
        max_delegations: int = 10,
    ) -> None:
        agents = specialists.values() if isinstance(specialists, dict) else specialists
        self.specialists: Dict[str, Agent] = {agent.name: agent for agent in agents}
        self.max_delegations = max_delegations
        self.execution_log: List[Delegation] = []
        self._run_usage = Usage()
        self._run_delegations = 0
        self.last_run_delegations: List[Delegation] = []
        self.director = Agent(
            role="директор",
            name="director",
            description="Распределяет задачи между специалистами и собирает итог.",
            system_prompt=self._build_prompt(),
            tools=[self._delegate_tool()] if self.specialists else [],
            llm=llm,
            approver=approver,
            max_iterations=max_iterations,
        )
        logger.info(f"Orchestrator initialized with {len(self.specialists)} specialist(s)")

    def run(self, task: str) -> AgentResult:
        """Решает задачу с чистого листа."""
        return self._track(lambda: self.director.run(_require_task(task)))

    def chat(self, message: str) -> AgentResult:
        """Продолжает диалог с Директором."""
        return self._track(lambda: self.director.chat(_require_task(message)))

    def followup(self, messages: List[Dict[str, Any]], text: str) -> AgentResult:
        """Продолжает существующий диалог Директора (например, доработка ответа)."""
        return self._track(lambda: self.director.followup(messages, text))

    def reset(self) -> None:
        """Начинает новый диалог."""
        self.director.reset()

    def execute(self, task: str) -> str:
        """Решает задачу и возвращает только текст ответа."""
        return self.run(task).text

    def get_execution_log(self) -> List[Delegation]:
        """Журнал поручений специалистам."""
        return self.execution_log.copy()

    def clear_log(self) -> None:
        self.execution_log = []

    def _track(self, call: Any) -> AgentResult:
        """Выполняет запрос и добавляет к расходу Директора расход специалистов."""
        self._run_usage = Usage()
        self._run_delegations = 0
        log_start = len(self.execution_log)
        result: AgentResult = call()
        add_usage(result.usage, self._run_usage)
        self.last_run_delegations = self.execution_log[log_start:]
        return result

    def _delegate(self, agent: str, task: str) -> str:
        specialist = self.specialists.get(agent)
        if specialist is None:
            raise ValueError(f"Нет специалиста '{agent}'. Доступны: {', '.join(self.specialists)}")
        if self._run_delegations >= self.max_delegations:
            raise DelegationLimitError(
                f"Лимит поручений ({self.max_delegations}) исчерпан. "
                "Собери ответ из уже полученных результатов."
            )
        self._run_delegations += 1
        logger.info(f"Delegating to {agent}: {task[:80]}")

        record = Delegation(agent=agent, task=task, status="running")
        self.execution_log.append(record)
        self._emit(ev.DELEGATION_START, specialist=agent, task=task)
        try:
            result = specialist.run(task)
        except Exception as e:
            record.status, record.error = "error", str(e)
            self._emit(ev.DELEGATION_END, specialist=agent, status="error", error=str(e))
            logger.error(f"Specialist {agent} failed: {e}", exc_info=True)
            raise
        self._emit(ev.DELEGATION_END, specialist=agent, status=result.stop_reason)
        record.status, record.iterations, record.usage, record.result = (
            result.stop_reason, result.iterations, result.usage, result.text
        )
        add_usage(self._run_usage, result.usage)

        if result.completed:
            return result.text
        return f"{result.text}\n\n[{agent} не завершил задачу: {result.stop_reason}]"

    @property
    def events(self) -> Optional[EventBus]:
        return self.director.events

    @events.setter
    def events(self, bus: Optional[EventBus]) -> None:
        """Подключает шину событий к Директору и всем специалистам."""
        for agent in [self.director, *self.specialists.values()]:
            agent.events = bus

    def _emit(self, type: str, **data: Any) -> None:
        if self.events is not None:
            self.events.emit(type, self.director.name, **data)

    def _delegate_tool(self) -> Tool:
        return Tool(
            name="delegate",
            description=(
                "Поручает задачу специалисту и возвращает его ответ. Специалист не видит "
                "разговор и другие поручения, поэтому в task передавай весь нужный контекст."
            ),
            input_schema=make_schema({
                "agent": {"type": "string", "enum": list(self.specialists)},
                "task": {
                    "type": "string",
                    "description": "Полная постановка: цель, данные, ограничения, формат",
                },
            }),
            handler=self._delegate,
        )

    def _build_prompt(self) -> str:
        team = "\n".join(
            f"- {name}: {agent.description or agent.role}"
            for name, agent in self.specialists.items()
        )
        return DIRECTOR_PROMPT.format(team=team or "- (специалистов нет, отвечай сам)")


def _require_task(task: Any) -> str:
    if not task or not isinstance(task, str) or not task.strip():
        logger.error(f"Invalid task: {type(task)}")
        raise ValueError("Task must be a non-empty string")
    return task
