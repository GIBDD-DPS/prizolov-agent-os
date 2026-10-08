# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Стоимость запросов и лимиты расходов.

Все агенты работают через MeteredLLM: перед каждым запросом проверяются лимиты,
после - считается стоимость по ценам модели, и она добавляется в usage.cost_usd.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from .llm import LLMClient, LLMError, LLMResponse, Usage
from .memory import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Price:
    """Цены в долларах за миллион токенов."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * 1.25  # запись в кэш на 5 минут


# Публичные цены Anthropic (Claude API).
PRICES: Dict[str, Price] = {
    "claude-fable-5-1": Price(10.0, 50.0, 0.25),
    "claude-fable-5": Price(10.0, 50.0, 1.0),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20),
    "claude-opus-5": Price(5.0, 25.0, 0.50),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50),
    "claude-opus-4-7": Price(5.0, 25.0, 0.50),
    "claude-opus-4-6": Price(5.0, 25.0, 0.50),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30),
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10),
}
DEFAULT_MODEL = "claude-sonnet-5-5"
WEB_SEARCH_USD = 10.0 / 1000  # за один поиск

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
    day TEXT PRIMARY KEY,
    usd REAL NOT NULL,
    requests INTEGER NOT NULL
);
"""


def price_for(model: str) -> Price:
    for name, price in PRICES.items():
        if model == name or model.startswith(name + "-"):
            return price
    return PRICES[DEFAULT_MODEL]


def cost(usage: Usage, model: str) -> float:
    """Стоимость запроса в долларах."""
    price = price_for(model)
    tokens = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.cache_read
        + usage.cache_creation_input_tokens * price.cache_write
    )
    return tokens / 1_000_000 + usage.web_search_requests * WEB_SEARCH_USD


class BudgetExceeded(LLMError):
    """Превышен лимит расходов."""


class Budget:
    """Лимиты на задачу и на день. 0 - без лимита."""

    def __init__(
        self, store: Store, task_limit_usd: float = 1.0, day_limit_usd: float = 10.0,
        today: Any = date.today,
    ) -> None:
        self.store = store
        store.add_schema(SCHEMA)
        self.task_limit_usd = task_limit_usd
        self.day_limit_usd = day_limit_usd
        self.task_spent_usd = 0.0
        self._today = today

    def start_task(self) -> None:
        self.task_spent_usd = 0.0

    def check(self) -> None:
        if self.task_limit_usd and self.task_spent_usd >= self.task_limit_usd:
            raise BudgetExceeded(
                f"Превышен лимит расходов на задачу (${self.task_limit_usd:.2f}): потрачено "
                f"${self.task_spent_usd:.2f}. Увеличьте лимит (/budget task N или "
                "PRIZOLOV_BUDGET_TASK_USD) или упростите задачу."
            )
        spent_today = self.today_spent_usd()
        if self.day_limit_usd and spent_today >= self.day_limit_usd:
            raise BudgetExceeded(
                f"Превышен дневной лимит расходов (${self.day_limit_usd:.2f}): сегодня "
                f"потрачено ${spent_today:.2f}. Увеличьте лимит (/budget day N или "
                "PRIZOLOV_BUDGET_DAY_USD) или продолжите завтра."
            )

    def add(self, usd: float) -> None:
        self.task_spent_usd += usd
        self.store.execute(
            "INSERT INTO spend (day, usd, requests) VALUES (?, ?, 1) ON CONFLICT(day) DO "
            "UPDATE SET usd = usd + excluded.usd, requests = requests + 1",
            (self._today().isoformat(), usd),
        )

    def today_spent_usd(self) -> float:
        rows = self.store.query(
            "SELECT usd FROM spend WHERE day = ?", (self._today().isoformat(),)
        )
        return rows[0]["usd"] if rows else 0.0

    def history(self, days: int = 30) -> List[Dict[str, Any]]:
        rows = self.store.query(
            "SELECT day, usd, requests FROM spend ORDER BY day DESC LIMIT ?", (days,)
        )
        return [dict(r) for r in rows]

    def total_spent_usd(self) -> float:
        return self.store.query("SELECT COALESCE(SUM(usd), 0) AS s FROM spend")[0]["s"]


class MeteredLLM:
    """Обёртка над LLM-клиентом: лимиты до запроса, стоимость после."""

    def __init__(self, inner: LLMClient, budget: Budget) -> None:
        self.inner = inner
        self.budget = budget

    def __getattr__(self, name: str) -> Any:
        # Остальные атрибуты (модель, история вызовов фейкового клиента) - от исходного клиента.
        return getattr(self.inner, name)

    def complete(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        compact: bool = False,
    ) -> LLMResponse:
        self.budget.check()
        response = self.inner.complete(
            system=system, messages=messages, tools=tools, max_tokens=max_tokens,
            output_schema=output_schema, compact=compact,
        )
        response.usage.cost_usd = cost(response.usage, response.model)
        self.budget.add(response.usage.cost_usd)
        return response
