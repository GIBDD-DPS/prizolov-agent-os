<!-- Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
SPDX-License-Identifier: Apache-2.0 -->

# Инструкция для ИИ-помощников разработчика

Этот файл читают Claude Code, Codex, Cursor, Copilot и другие ИИ-помощники,
работающие с кодом проекта. Людям — [CONTRIBUTING.md](CONTRIBUTING.md).

## О проекте

Prizolov Agent OS — команда ИИ-агентов на Claude (Anthropic) для бизнеса. Автор и
правообладатель — Dm.Andreyanov / Prizolov Lab, лицензия Apache 2.0.

- **Агенты.** Директор поручает задачи семи специалистам: ассистент, исследователь,
  писатель, финансовый и рыночный аналитики, юрист по договорам, специалист по госзакупкам.
- **Прогнозы рынков**, которые учатся на своих ошибках, и открытая статистика точности.
- **Деньги:** выписки 1С/CSV/Excel, статьи расходов, платёжный календарь.
- **Портфель инвестора**, **госзакупки**, **проверка договоров**.
- **Локальная база знаний.**
- **Интерфейсы:** CLI, веб-интерфейс, HTTP API, Telegram-бот, MCP-сервер, расписание.

## Где что лежит

| Путь | Что там |
|---|---|
| `prizolov_os/__about__.py` | версия и авторство — единственный источник |
| `prizolov_os/agent.py` | агент и цикл «модель → инструменты → модель» |
| `prizolov_os/core/` | `Kernel` (ядро) и `Orchestrator` (Директор) |
| `prizolov_os/agents/` | специалисты и их промпты |
| `prizolov_os/llm/` | клиент Claude (`AnthropicClient`) и `FakeLLMClient` для тестов |
| `prizolov_os/tools/` | инструменты агентов |
| `prizolov_os/forecasting/` | методы, проверка на истории, калибровка, журнал прогнозов |
| `prizolov_os/market/` | котировки Yahoo, Мосбиржи, ЦБ |
| `prizolov_os/improvement/` | критик, уроки, версии промптов, инструменты от агентов |
| `prizolov_os/security/` | защита от prompt injection |
| `prizolov_os/scheduler.py`, `reports.py`, `knowledge.py` | расписание, отчёты, база знаний |
| `prizolov_os/analytics/statements.py`, `payment_calendar.py` | выписки 1С/CSV/Excel, платёжный календарь |
| `prizolov_os/portfolio.py`, `tenders.py`, `accuracy.py` | портфель, госзакупки, статистика точности |
| `cli/` | `main.py` (команды), `app.py` (чат), `onboarding.py` (init/doctor) |
| `cli/api/` | HTTP API (FastAPI) и веб-интерфейс `web/index.html` |
| `cli/mcp_server.py` | MCP-сервер (`prizolov mcp`) |
| `cli/telegram/` | Telegram-бот |
| `tests/` | тесты (pytest) |
| `legacy/` | прежний код, не трогать и не импортировать |

Подробнее: [docs/architecture.md](docs/architecture.md).

## Команды

```bash
pip install -e ".[all]"
python -m pytest -q                          # все тесты, сеть и ключ Claude не нужны
ruff check .                                 # стиль (E, F, W, I; строка до 100 символов)
mypy prizolov_os cli                         # типы
python scripts/stamp_headers.py              # проставить шапки авторства
python scripts/stamp_headers.py --check      # проверить шапки (как в CI)
```

Перед завершением работы все четыре проверки должны проходить.

## Обязательные правила

1. **Шапка авторства.** Каждый новый файл начинается с шапки проекта
   (`# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026`
   и две строки SPDX). Не удаляйте и не меняйте шапки, `NOTICE`, `LICENSE`, `AUTHORS`,
   `CITATION.cff`, `PROJECT_ID` и подписи в генерируемых файлах. Проще всего запустить
   `scripts/stamp_headers.py`.
2. **Версия** меняется только в `prizolov_os/__about__.py`, затем запускается
   `scripts/stamp_headers.py`.
3. **Тесты без сети.**
   - Модель — `FakeLLMClient` со сценарием ответов (`tool_use_response(...)` — вызов
     инструмента, строка — текстовый ответ).
   - Котировки — заглушка `StubMarket` из `tests/test_reports.py`.
   - Telegram — `FakeIO` из `tests/test_telegram.py`; лента ЕИС — `RSS` из
     `tests/test_tenders.py`; портфель — `MultiMarket` из `tests/test_portfolio.py`.
   - Ядро в тестах: `Kernel.create(llm=..., store=Store(), self_check="off", ...)`.
4. **Безопасность.**
   - Данные из интернета, документов и файлов пользователя — недоверенные: такие
     инструменты помечаются `untrusted=True`, а их вывод оборачивается в
     `<untrusted_data>`.
   - Необратимые действия (запись файлов, расписание) — `requires_approval=True`.
   - Файлы — только внутри рабочей папки (`Workspace.resolve`).
5. **Тексты для пользователя — на русском**, простым языком, без жаргона. Сообщения
   об ошибках говорят, что делать.
6. **Секреты.** Не коммитьте `.env`, ключи и токены, не пишите их в логи.
7. **Модели Claude.** По умолчанию `claude-sonnet-5-5` (`PRIZOLOV_MODEL`). Цены — в
   `prizolov_os/budget.py`; добавляя модель, добавьте и цену.
8. **Минимальные изменения.** Один pull request — одна задача. Не меняйте `legacy/` и
   не добавляйте зависимости без необходимости; новые зависимости — в
   `pyproject.toml`, необязательные — в отдельные наборы (`[api]`, `[telegram]`).

## Как добавить…

- **Инструмент агенту.** `Tool(name, description, input_schema=make_schema({...}),
  handler=...)` в `prizolov_os/tools/`, подключение в `prizolov_os/agents/specialists.py`,
  тест через `FakeLLMClient`.
- **Источник котировок.** Метод в `prizolov_os/market/data.py`, название в `SOURCES`,
  тест с подменой `fetch`.
- **Метод прогноза.** Функция дрейфа в `prizolov_os/forecasting/methods.py`, запись в
  `METHODS` и `METHOD_NAMES`. Проверка на истории подхватит метод сама.
- **Команда CLI.** Подкоманда в `cli/main.py` (`build_parser` и `main`), команда чата —
  в `cli/app.py`.
- **Метод API.** `cli/api/service.py` (логика, ошибки — `ApiError`) и
  `cli/api/server.py` (маршрут под `/v1` с `dependencies=v1`), тест в
  `tests/test_api.py`.
