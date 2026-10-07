"""ИИ-агент: роль, инструменты и цикл «модель → инструменты → модель»."""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from .llm import LLMClient, LLMResponse, Usage, create_client
from .tools import AnyTool, Approver, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """Ты — агент Prizolov Agent OS. Твоя роль: {role}.

Отвечай на языке пользователя. Если для точного ответа нужен инструмент \
(расчёт, дата, файл), вызови его, а не угадывай. Не выдумывай результаты \
инструментов. Если инструмент вернул ошибку, учти её: исправь параметры \
или объясни пользователю, что не получилось."""


@dataclass
class AgentResult:
    """Итог выполнения задачи агентом.

    Attributes:
        text: Ответ агента.
        stop_reason: end_turn (задача решена), max_tokens (ответ обрезан),
            refusal (модель отказалась), max_iterations (исчерпан лимит шагов).
        iterations: Сколько раз агент обратился к модели.
        usage: Суммарный расход токенов.
        tool_results: Все вызовы инструментов по порядку.
    """

    text: str
    stop_reason: str
    iterations: int
    usage: Usage = field(default_factory=Usage)
    tool_results: List[ToolResult] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.stop_reason == "end_turn"


class Agent:
    """ИИ-агент с ролью, инструментами и ограничениями.

    Пример:
        agent = Agent(role="финансовый аналитик", tools=default_tools("workspace"))
        print(agent.run("Сколько будет 15% от 2 400 000?").text)
    """

    def __init__(
        self,
        role: str,
        constraints: Optional[Dict[str, Any]] = None,
        *,
        llm: Optional[LLMClient] = None,
        tools: Union[ToolRegistry, Iterable[AnyTool]] = (),
        system_prompt: Optional[str] = None,
        approver: Optional[Approver] = None,
        max_iterations: int = 20,
        name: Optional[str] = None,
        description: str = "",
    ) -> None:
        """
        Args:
            role: Роль агента (подставляется в системный промпт по умолчанию).
            constraints: Ограничения, например {"forbidden_tokens": ["spam"]}.
            llm: LLM-клиент. По умолчанию создаётся по настройкам при первом запросе.
            tools: Инструменты агента.
            system_prompt: Свой системный промпт вместо стандартного.
            approver: Спрашивает разрешение на опасные действия. Без него такие
                действия запрещены.
            max_iterations: Максимум обращений к модели за одну задачу.
            name: Имя агента (по умолчанию - роль).
            description: Чем агент полезен; по описанию оркестратор выбирает агента.
        """
        self.role: str = role
        self.name: str = name or role
        self.description: str = description
        self.constraints: Dict[str, Any] = constraints or {}
        self.tools: ToolRegistry = tools if isinstance(tools, ToolRegistry) else ToolRegistry(tools)
        self.system_prompt: str = system_prompt or DEFAULT_SYSTEM_PROMPT.format(role=role)
        self.approver = approver
        self.max_iterations = max_iterations
        self.history: List[Dict[str, Any]] = []
        self.memory: List[Tuple[str, str]] = []
        self._llm = llm
        logger.debug(f"Agent initialized with role: {role}")

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = create_client()
        return self._llm

    def apply_constraints(self, input_data: str) -> str:
        """
        Применяет ограничения к входным данным.

        Raises:
            TypeError: Если input_data не строка
            ValueError: Если найдены запрещённые токены
        """
        if not isinstance(input_data, str):
            logger.error(f"Invalid input type: {type(input_data)}")
            raise TypeError(
                f"Expected input_data to be str, got {type(input_data).__name__}"
            )

        for token in self.constraints.get("forbidden_tokens", []):
            if token in input_data:
                logger.warning(f"Forbidden token '{token}' detected")
                raise ValueError(f"Forbidden token '{token}' found in input data")

        return input_data

    def run(self, task: str) -> AgentResult:
        """Решает задачу с чистого листа, не трогая историю диалога."""
        task = self.apply_constraints(task)
        messages: List[Dict[str, Any]] = [{"role": "user", "content": task}]
        result = self._loop(messages)
        self.memory.append((task, result.text))
        return result

    def chat(self, message: str) -> AgentResult:
        """Продолжает диалог: агент помнит предыдущие сообщения."""
        message = self.apply_constraints(message)
        checkpoint = len(self.history)
        self.history.append({"role": "user", "content": message})
        result = self._loop(self.history)
        if result.stop_reason == "refusal":
            # Откатываем ход, чтобы отклонённый запрос не мешал следующим.
            del self.history[checkpoint:]
        self.memory.append((message, result.text))
        return result

    def reset(self) -> None:
        """Начинает новый диалог."""
        self.history = []

    def execute(self, input_data: str) -> str:
        """Выполняет задачу и возвращает только текст ответа."""
        logger.info(f"Agent {self.name} executing task")
        return self.run(input_data).text

    def get_memory(self) -> List[Tuple[str, str]]:
        """Возвращает историю выполненных задач (запрос, ответ)."""
        return self.memory.copy()

    def clear_memory(self) -> None:
        """Очищает историю выполненных задач."""
        self.memory = []

    def _loop(self, messages: List[Dict[str, Any]]) -> AgentResult:
        """Обращается к модели и выполняет инструменты, пока задача не решена.

        Дописывает в messages все ходы, так что после вызова это полная история.
        """
        usage = Usage()
        tool_results: List[ToolResult] = []
        tools = self.tools.schemas() or None
        response: Optional[LLMResponse] = None

        for iteration in range(1, self.max_iterations + 1):
            response = self.llm.complete(system=self.system_prompt, messages=messages, tools=tools)
            add_usage(usage, response.usage)

            def finish(text: str, stop_reason: str) -> AgentResult:
                return AgentResult(text, stop_reason, iteration, usage, tool_results)

            if response.refused:
                logger.warning(f"Agent {self.name}: model refused the request")
                return finish("Модель отказалась выполнять этот запрос.", "refusal")

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                # Серверный инструмент взял паузу: повторный запрос продолжит с того же места.
                continue

            calls = response.tool_calls
            if response.stop_reason == "max_tokens":
                if calls:
                    # Вызовы из обрезанного ответа не выполняем, но закрываем их,
                    # иначе история станет некорректной для следующего запроса.
                    messages.append({"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": c.id, "is_error": True,
                         "content": "Не выполнено: ответ модели был обрезан"}
                        for c in calls
                    ]})
                return finish(response.text + "\n\n[Ответ обрезан: достигнут лимит длины]",
                              "max_tokens")

            if response.stop_reason != "tool_use" or not calls:
                return finish(response.text, "end_turn")

            results = [self.tools.execute(call, self.approver) for call in calls]
            tool_results.extend(results)
            # Все результаты - одним сообщением, как требует API.
            messages.append({"role": "user", "content": [r.to_api() for r in results]})

        logger.warning(f"Agent {self.name}: iteration limit {self.max_iterations} reached")
        text = response.text if response else ""
        return AgentResult(
            (text + "\n\n" if text else "")
            + f"[Остановлено: превышен лимит в {self.max_iterations} шагов]",
            "max_iterations",
            self.max_iterations,
            usage,
            tool_results,
        )


def add_usage(total: Usage, part: Usage) -> None:
    total.input_tokens += part.input_tokens
    total.output_tokens += part.output_tokens
    total.cache_read_input_tokens += part.cache_read_input_tokens
    total.cache_creation_input_tokens += part.cache_creation_input_tokens
