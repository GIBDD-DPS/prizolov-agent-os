"""Специалисты Prizolov OS: готовые агенты с ролью, промптом и инструментами."""

from pathlib import Path
from typing import Dict, Optional, Union

from ..agent import Agent
from ..config import settings
from ..forecasting import ForecastEngine
from ..llm import LLMClient
from ..market import MarketData
from ..tools import (
    Approver,
    Workspace,
    calculator_tool,
    cashflow_tool,
    datetime_tool,
    default_tools,
    file_tools,
    market_tools,
    web_fetch_tool,
    web_search_tool,
)

COMMON_RULES = """
Общие правила:
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
2. Ищи в интернете (web_search), открывай ключевые страницы (web_fetch), при \
необходимости читай документы пользователя из рабочей папки.
3. Сверяй факты по нескольким источникам; отмечай противоречия и устаревшие данные.
4. Верни структурированную сводку: ключевые факты, цифры с датами, выводы и список \
источников со ссылками. Явно отделяй факты от своих оценок.

Не пиши готовый публицистический текст - это работа писателя.""" + COMMON_RULES

WRITER_PROMPT = """Ты - писатель Prizolov Agent OS.

Пишешь тексты по материалу, который тебе дали: статьи, отчёты, посты, письма, \
описания, коммерческие предложения.
- Опирайся только на переданный материал и файлы из рабочей папки; новые факты \
не придумывай. Если материала мало, скажи, чего не хватает.
- Подстраивай стиль и объём под задачу и аудиторию; по умолчанию пиши ясно, \
живо и без канцелярита.
- Если просят сохранить результат, запиши его в файл (пользователь подтвердит \
запись).""" + COMMON_RULES

CASHFLOW_PROMPT = """Ты - финансовый аналитик Prizolov Agent OS, специалист по \
движению денежных средств бизнеса.

- Для выписок в CSV используй analyze_cashflow; если остаток на начало неизвестен, \
уточни его или прими 0 и прямо скажи об этом.
- Объясняй результат простым языком: сколько пришло и ушло, куда уходят деньги, \
какой остаток ожидается и с каким диапазоном неопределённости, есть ли риск кассового \
разрыва.
- Предлагай конкретные действия: что сократить, какие платежи перенести, какой \
резерв держать.
- Прогноз - статистическая оценка по истории, а не гарантия; говори об этом.
- Сообщай надёжность из forecast.reliability. Если в ответе есть forecast.verified_now, \
расскажи, насколько сбылись прошлые прогнозы.""" + COMMON_RULES

MARKET_PROMPT = """Ты - рыночный аналитик Prizolov Agent OS: драгоценные металлы, \
акции, валюты, криптовалюты, сырьё.

- Получай данные только инструментами: analyze_market (Yahoo Finance, Московская \
биржа, ЦБ РФ) или analyze_price_csv для файлов пользователя. Не называй цены по памяти.
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
            datetime_tool(),
        ],
        llm=llm,
        approver=approver,
    )


def create_writer(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
) -> Agent:
    return Agent(
        role="писатель",
        name="writer",
        description=(
            "Пишет тексты по готовому материалу: статьи, отчёты, посты, письма; "
            "может сохранить результат в файл."
        ),
        system_prompt=WRITER_PROMPT,
        tools=file_tools(Workspace(_workspace_dir(workspace_dir))),
        llm=llm,
        approver=approver,
    )


def create_cashflow_analyst(
    llm: Optional[LLMClient] = None,
    workspace_dir: Optional[Union[str, Path]] = None,
    approver: Optional[Approver] = None,
    forecasts: Optional[ForecastEngine] = None,
) -> Agent:
    workspace = Workspace(_workspace_dir(workspace_dir))
    read_only = [t for t in file_tools(workspace) if t.name in ("list_files", "read_file")]
    return Agent(
        role="финансовый аналитик",
        name="cashflow_analyst",
        description=(
            "Анализирует движение денег бизнеса по выписке (CSV) и прогнозирует остаток "
            "и риск кассового разрыва."
        ),
        system_prompt=CASHFLOW_PROMPT,
        tools=[cashflow_tool(workspace, forecasts), calculator_tool(), datetime_tool(), *read_only],
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
            "(Yahoo Finance, Мосбиржа, ЦБ РФ)."
        ),
        system_prompt=MARKET_PROMPT,
        tools=[
            *market_tools(market or MarketData(), workspace, forecasts),
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
) -> Dict[str, Agent]:
    """Все специалисты по именам: assistant, researcher, writer, cashflow_analyst,
    market_analyst."""
    agents = [
        create_assistant(llm, workspace_dir, approver),
        create_researcher(llm, workspace_dir, approver),
        create_writer(llm, workspace_dir, approver),
        create_cashflow_analyst(llm, workspace_dir, approver, forecasts),
        create_market_analyst(llm, workspace_dir, approver, market, forecasts),
    ]
    return {agent.name: agent for agent in agents}


def _workspace_dir(workspace_dir: Optional[Union[str, Path]]) -> Union[str, Path]:
    return workspace_dir if workspace_dir is not None else settings.workspace_dir
