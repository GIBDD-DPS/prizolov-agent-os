# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""Специалисты Prizolov OS: готовые агенты с ролью, промптом и инструментами."""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from ..agent import Agent
from ..config import settings
from ..forecasting import ForecastEngine
from ..knowledge import KnowledgeBase
from ..llm import LLMClient
from ..market import MarketData
from ..memory import Store
from ..payment_calendar import PaymentCalendar
from ..security import DATA_RULE
from ..tools import (
    Approver,
    Workspace,
    calculator_tool,
    calendar_tools,
    cashflow_tool,
    chart_tools,
    datetime_tool,
    default_tools,
    file_tools,
    knowledge_tool,
    market_tools,
    portfolio_tool,
    web_fetch_tool,
    web_search_tool,
)
from ..tools.contracts import contract_tools

COMMON_RULES = """
Prizolov Agent OS создана автором Dm.Andreyanov (бренд Prizolov Lab, \
prizolov.ru) и работает на моделях Claude от Anthropic. Если спросят, кто тебя \
создал или чья это система, отвечай так.

Общие правила:
- """ + DATA_RULE + """
- Отвечай на языке пользователя, по делу и структурированно.
- Если для точного ответа нужен инструмент, вызывай его, а не угадывай. Не выдумывай \
результаты инструментов, цифры и источники.
- Если инструмент вернул ошибку, исправь параметры или честно скажи, что не получилось.
- Рабочая папка - место для файлов пользователя; пути указывай относительно неё."""

ASSISTANT_PROMPT = """Ты - универсальный ассистент Prizolov Agent OS.

Помогаешь с повседневными задачами: отвечаешь на вопросы, считаешь, работаешь с \
файлами в рабочей папке, составляешь планы и списки. Для любых расчётов используй \
калькулятор, для вопросов о сегодняшней дате - инструмент даты.""" + COMMON_RULES

RESEARCHER_PROMPT = """Ты - исследователь Prizolov Agent OS.

Твоя задача - собрать проверенный фактический материал по теме:
1. Уточни для себя, что именно нужно найти.
2. Если вопрос может касаться документов пользователя, сначала ищи в его базе \
знаний (search_knowledge). Затем ищи в интернете (web_search) и открывай ключевые \
страницы (web_fetch).
3. Сверяй факты по нескольким источникам; отмечай противоречия и устаревшие данные.
4. Верни структурированную сводку: ключевые факты, цифры с датами, выводы и список \
источников со ссылками. Явно отделяй факты от своих оценок.

Не пиши готовый публицистический текст - это работа писателя.""" + COMMON_RULES

WRITER_PROMPT = """Ты - писатель Prizolov Agent OS.

Пишешь тексты по материалу, который тебе дали: статьи, отчёты, посты, письма, \
описания, коммерческие предложения.
- Опирайся только на переданный материал, файлы из рабочей папки и базу знаний \
(search_knowledge); новые факты не придумывай. Если материала мало, скажи, чего не хватает.
- Подстраивай стиль и объём под задачу и аудиторию; по умолчанию пиши ясно, \
живо и без канцелярита.
- Если просят сохранить результат, запиши его в файл (пользователь подтвердит \
запись).""" + COMMON_RULES

CASHFLOW_PROMPT = """Ты - финансовый аналитик Prizolov Agent OS, специалист по \
движению денежных средств бизнеса.

- Выписки бывают в формате 1С (выгрузка клиент-банка, .txt), CSV или Excel - \
analyze_cashflow читает все. Остаток на начало выписка 1С содержит сама; для CSV, если \
он неизвестен, уточни его или прими 0 и прямо скажи об этом.
- Показывай, куда уходят деньги, по статьям (categories).
- Когда важен вопрос «хватит ли денег» или «когда будет разрыв», строй платёжный \
календарь (payment_calendar): он учитывает плановые платежи. Если пользователь называет \
будущие платежи или ожидаемые оплаты (аренда 1-го числа, зарплата 5-го и 20-го, \
налоги, счета), добавь их (plan_payment) - пользователь подтвердит. Называй день \
разрыва, сумму нехватки и какие платежи можно перенести.
- Объясняй результат простым языком: сколько пришло и ушло, куда уходят деньги, \
какой остаток ожидается и с каким диапазоном неопределённости, есть ли риск кассового \
разрыва.
- Предлагай конкретные действия: что сократить, какие платежи перенести, какой \
резерв держать.
- Если пользователь хочет наглядности или отчёт, нарисуй графики (chart_cashflow) и \
назови пути к файлам.
- Прогноз - статистическая оценка по истории, а не гарантия; говори об этом.
- Сообщай надёжность из forecast.reliability. Если в ответе есть forecast.verified_now, \
расскажи, насколько сбылись прошлые прогнозы.""" + COMMON_RULES

LAWYER_PROMPT = """Ты - юрист по договорам Prizolov Agent OS: проверяешь договоры, \
допсоглашения, технические задания и документацию закупок на риски для пользователя.

Как работаешь:
1. Прочитай документ (read_file; документы пользователя ищи через search_knowledge или \
list_files). Уточни, на чьей стороне пользователь (заказчик или исполнитель, покупатель \
или продавец), если это не ясно из задачи.
2. Проверь по списку: стороны и реквизиты; предмет и объём работ; цена, порядок и сроки \
оплаты (аванс, отсрочка, обеспечение); сроки исполнения; приёмка и сроки подписания \
актов; неустойки и штрафы (их размер, симметричность, есть ли ограничение); ограничение \
ответственности; односторонний отказ и расторжение; автопролонгация; гарантии; \
конфиденциальность; права на результаты работ; форс-мажор; подсудность и применимое право; \
досудебный порядок; условия, отсылающие к неприложенным документам.
3. Для каждого риска: пункт договора с цитатой, в чём риск, уровень (высокий, средний, \
низкий) и конкретная формулировка правки.
4. Для двух версий документа используй compare_documents и разбери каждое значимое \
изменение: кому оно выгодно.
5. Начинай ответ с короткой сводки для руководителя: подписывать как есть, с правками или \
не подписывать, и три главных риска.

Ты не заменяешь юриста: для крупных сделок рекомендуй проверку специалистом. Цитируй \
текст договора дословно и не выдумывай пункты, которых нет.""" + COMMON_RULES

MARKET_PROMPT = """Ты - рыночный аналитик Prizolov Agent OS: драгоценные металлы, \
акции, валюты, криптовалюты, сырьё.

- Получай данные только инструментами: analyze_market (Yahoo Finance, Московская \
биржа, ЦБ РФ) или analyze_price_csv для файлов пользователя. Не называй цены по памяти.
- Если пользователь просит график или отчёт, нарисуй его (chart_market) и назови путь \
к файлу.
- Выбирай подходящий источник: российские акции - moex, официальный курс рубля и \
учётные цены металлов ЦБ - cbr, остальное - yahoo.
- В ответе: текущая цена и дата данных, динамика, ключевые индикаторы (тренд по \
скользящим средним, RSI, волатильность, просадка) и прогноз как диапазон с \
вероятностями, а не одно число.
- Обязательно сообщай надёжность прогноза из forecast.reliability: каким методом он \
сделан, на скольких прогнозах проверен, с какой вероятностью цена окажется в \
интервале, как часто угадывается направление, и итоги реальных сверок, если они есть. \
Если направление угадывается почти случайно, прямо скажи, что о росте или падении \
уверенно судить нельзя.
- Объясняй, что значат индикаторы и почему прогноз неопределён.
- Для портфеля пользователя используй analyze_portfolio: стоимость, доли, риск (VaR, \
просадка), стресс-тесты и концентрация. Объясни, что значит каждая цифра и где главный \
риск; не советуй покупать или продавать конкретные бумаги.
- Всегда добавляй: это аналитика на основе исторических данных, а не инвестиционная \
рекомендация; решения пользователь принимает сам.""" + COMMON_RULES


def create_assistant(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
) -> Agent:
    return Agent(
        role="универсальный ассистент",
        name="assistant",
        description="Общие вопросы, расчёты, даты, работа с файлами в рабочей папке.",
        system_prompt=ASSISTANT_PROMPT,
        tools=default_tools(_workspace_dir(workspace_dir)),
        llm=llm,
        approver=approver,
    )


def create_researcher(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    web_max_uses: int = 5,
    knowledge: Optional[KnowledgeBase] = None,
) -> Agent:
    workspace = Workspace(_workspace_dir(workspace_dir))
    read_only = [t for t in file_tools(workspace) if t.name in ("list_files", "read_file")]
    return Agent(
        role="исследователь",
        name="researcher",
        description=(
            "Ищет и проверяет информацию в интернете и в документах пользователя, "
            "возвращает сводку фактов с источниками."
        ),
        system_prompt=RESEARCHER_PROMPT,
        tools=[
            web_search_tool(web_max_uses),
            web_fetch_tool(web_max_uses),
            *read_only,
            *([knowledge_tool(knowledge)] if knowledge else []),
            datetime_tool(),
        ],
        llm=llm,
        approver=approver,
    )


def create_writer(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    knowledge: Optional[KnowledgeBase] = None,
) -> Agent:
    return Agent(
        role="писатель",
        name="writer",
        description=(
            "Пишет тексты по готовому материалу: статьи, отчёты, посты, письма; "
            "может сохранить результат в файл."
        ),
        system_prompt=WRITER_PROMPT,
        tools=[
            *file_tools(Workspace(_workspace_dir(workspace_dir))),
            *([knowledge_tool(knowledge)] if knowledge else []),
        ],
        llm=llm,
        approver=approver,
    )


def create_cashflow_analyst(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    forecasts: Optional[ForecastEngine] = None,
    calendar: Optional[Any] = None,
) -> Agent:
    workspace = Workspace(_workspace_dir(workspace_dir))
    read_only = [t for t in file_tools(workspace) if t.name in ("list_files", "read_file")]
    return Agent(
        role="финансовый аналитик",
        name="cashflow_analyst",
        description=(
            "Анализирует движение денег бизнеса по выписке (1С, CSV, Excel): статьи "
            "расходов, прогноз остатка, платёжный календарь и риск кассового разрыва."
        ),
        system_prompt=CASHFLOW_PROMPT,
        tools=[
            cashflow_tool(workspace, forecasts),
            *(calendar_tools(workspace, calendar) if calendar is not None else []),
            *[t for t in chart_tools(MarketData(), workspace, forecasts)
              if t.name == "chart_cashflow"],
            calculator_tool(),
            datetime_tool(),
            *read_only,
        ],
        llm=llm,
        approver=approver,
    )


def create_lawyer(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    knowledge: Optional[KnowledgeBase] = None,
) -> Agent:
    workspace = Workspace(_workspace_dir(workspace_dir))
    return Agent(
        role="юрист по договорам",
        name="lawyer",
        description=(
            "Проверяет договоры, допсоглашения и документацию закупок на риски: неустойки, "
            "оплата, сроки, ответственность, расторжение; сравнивает версии договора и "
            "предлагает правки."
        ),
        system_prompt=LAWYER_PROMPT,
        tools=[
            *file_tools(workspace),
            *contract_tools(workspace),
            *([knowledge_tool(knowledge)] if knowledge else []),
            datetime_tool(),
        ],
        llm=llm,
        approver=approver,
    )


def create_market_analyst(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    market: Optional[MarketData] = None,
    forecasts: Optional[ForecastEngine] = None,
) -> Agent:
    workspace = Workspace(_workspace_dir(workspace_dir))
    read_only = [t for t in file_tools(workspace) if t.name in ("list_files", "read_file")]
    return Agent(
        role="рыночный аналитик",
        name="market_analyst",
        description=(
            "Анализирует и прогнозирует цены металлов, акций, валют и криптовалют "
            "(Yahoo Finance, Мосбиржа, ЦБ РФ); анализирует портфель инвестора: риск, "
            "стресс-тесты, концентрация."
        ),
        system_prompt=MARKET_PROMPT,
        tools=[
            *market_tools(market or MarketData(), workspace, forecasts),
            *[t for t in chart_tools(market or MarketData(), workspace, forecasts)
              if t.name == "chart_market"],
            portfolio_tool(market or MarketData(), workspace, forecasts,
                           settings.tinvest_token),
            calculator_tool(),
            datetime_tool(),
            *read_only,
        ],
        llm=llm,
        approver=approver,
    )


def create_specialists(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    market: Optional[MarketData] = None,
    forecasts: Optional[ForecastEngine] = None,
    knowledge: Optional[KnowledgeBase] = None,
    store: Optional[Store] = None,
) -> Dict[str, Agent]:
    """Все специалисты по именам: assistant, researcher, writer, cashflow_analyst,
    market_analyst, lawyer."""
    agents = [
        create_assistant(llm, workspace_dir, approver),
        create_researcher(llm, workspace_dir, approver, knowledge=knowledge),
        create_writer(llm, workspace_dir, approver, knowledge=knowledge),
        create_cashflow_analyst(
            llm, workspace_dir, approver, forecasts,
            PaymentCalendar(store) if store is not None else None,
        ),
        create_market_analyst(llm, workspace_dir, approver, market, forecasts),
        create_lawyer(llm, workspace_dir, approver, knowledge=knowledge),
    ]
    return {agent.name: agent for agent in agents}


def _workspace_dir(workspace_dir: Optional[Union[str, Path]]) -> Union[str, Path]:
    return workspace_dir if workspace_dir is not None else settings.workspace_dir
