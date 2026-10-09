<!-- Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
SPDX-License-Identifier: Apache-2.0 -->

# Prizolov Agent OS

**Автор:** Dm.Andreyanov · **Бренд:** Prizolov Lab · © 2026 · версия 0.3.0 · [prizolov.ru](https://prizolov.ru)

[![CI](https://github.com/GIBDD-DPS/prizolov-agent-os/actions/workflows/ci.yml/badge.svg)](https://github.com/GIBDD-DPS/prizolov-agent-os/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Команда ИИ-агентов на моделях Claude (Anthropic) для бизнеса: Директор распределяет
задачу между специалистами, проверяет результат и учится на ошибках. Есть прогнозы
металлов, акций, валют и криптовалют, анализ движения денег, база знаний по вашим
документам, Telegram-бот, расписание и HTTP API.

## Содержание

- [Что умеет](#что-умеет)
- [Установка](#установка)
- [Быстрый старт](#быстрый-старт)
- [Отчёт по активу без Claude](#отчёт-по-активу-без-claude)
- [Telegram-бот](#telegram-бот)
- [Расписание](#расписание)
- [HTTP API](#http-api)
- [Использование из Python](#использование-из-python)
- [Документация](#документация)
- [Разработка](#разработка)
- [Авторство и лицензия](#авторство-и-лицензия)

## Что умеет

- **Команда агентов.** Директор понимает задачу и поручает её специалистам:
  - ассистент — расчёты, даты, файлы;
  - исследователь — поиск в интернете и в ваших документах, с источниками;
  - писатель — статьи, отчёты, письма;
  - финансовый аналитик — выписки и кассовые разрывы;
  - рыночный аналитик — цены и прогнозы.

  Независимые поручения выполняются одновременно.
- **Прогнозы рынков.** Источники данных: Yahoo Finance (мировые акции, валюты,
  криптовалюты, фьючерсы на металлы), Мосбиржа и ЦБ РФ (курсы рубля, учётные цены
  золота, серебра, платины, палладия).
  - Каждый прогноз содержит медиану, интервалы 80% и 95% и вероятность роста.
  - К каждому прогнозу приложено, на скольких прогнозах проверен метод и как часто
    он попадал в интервал.
- **Самообучение на ошибках.** Методы прогноза соревнуются на истории. Наступившие
  прогнозы сверяются с фактом, и калибровка интервалов подстраивается в заданных
  границах. Из ваших оценок (`/good`, `/bad`) и замечаний критика получаются уроки
  агентам. Улучшенные промпты и новые инструменты агентов подключаются только после
  вашего одобрения.
- **Самопроверка.** Сложные ответы проверяет критик; при низкой оценке агент
  дорабатывает ответ.
- **База знаний.** PDF, Word, Excel, CSV, TXT и MD из рабочей папки индексируются
  локально (SQLite FTS5); агенты ищут в них по словам с учётом окончаний.
- **Отчёты и графики.** PNG-графики прогнозов и движения денег. Отчёты в Markdown
  подписываются автором.
- **Безопасность.**
  - Файлы читаются и пишутся только в рабочей папке; запись — с вашего подтверждения.
  - Работает защита от инструкций, спрятанных в веб-страницах и документах
    (prompt injection).
  - Инструменты, созданные агентами, запускаются в отдельном процессе после проверки
    кода.
- **Контроль расходов.** Стоимость каждой задачи. Лимиты на задачу и на день.
  Журнал трассировки всех шагов. Сжатие длинных диалогов.
- **Интерфейсы.** Терминал, Telegram-бот, HTTP API, расписание задач.

## Установка

Нужен Python 3.10 или новее.

```bash
git clone https://github.com/GIBDD-DPS/prizolov-agent-os.git
cd prizolov-agent-os
pip install -e .                      # основа: агенты, прогнозы, отчёты, CLI
pip install -e ".[telegram]"          # + Telegram-бот
pip install -e ".[api]"               # + HTTP API (FastAPI)
pip install -e ".[all]"               # всё, включая инструменты разработки
```

Скопируйте `.env.example` в `.env` и впишите ключ Anthropic
([console.anthropic.com](https://console.anthropic.com/)):

```bash
cp .env.example .env
# ANTHROPIC_API_KEY=sk-ant-...
```

Остальные настройки описаны в [docs/configuration.md](docs/configuration.md).

## Быстрый старт

```bash
prizolov chat                         # диалог с командой агентов
prizolov run "Спрогнозируй курс доллара ЦБ на 30 дней"
prizolov sessions                     # сохранённые диалоги
prizolov chat --session ID            # продолжить диалог
```

Примеры задач:

- «Сравни золото, серебро и биткоин за год и дай прогноз на месяц»
- «Проанализируй выписку inbox/bank.csv: будет ли кассовый разрыв в ближайшие 60 дней?»
- «Найди в договорах условия оплаты и сделай сводку в файл summary.md»
- «Запомни: наша валюта учёта — рубли, НДС 20%»

Ход работы виден по шагам: кто чем занят, какие инструменты вызваны, сколько
стоила задача. Команды чата — `/help`; основные:

| Команда | Что делает |
|---|---|
| `/good`, `/bad комментарий` | оценка ответа; замечание становится уроком |
| `/forecasts`, `/verify` | точность прогнозов и методов, сверка с фактом |
| `/schedule` | задачи по расписанию |
| `/cost`, `/budget` | расходы и лимиты |
| `/index` | обновить базу знаний |
| `/improve`, `/prompts`, `/approve-prompt N` | улучшение промптов по урокам |
| `/tools`, `/approve-tool имя` | инструменты, созданные агентами |

## Отчёт по активу без Claude

Прогнозы на несколько горизонтов, таблица и график. Ключ Anthropic не нужен, это бесплатно:

```bash
prizolov report GOLD --horizons 1,7,15,30     # золото, ЦБ РФ, руб./г
prizolov report GC=F                          # золото, фьючерс COMEX, $/унция
prizolov report USD                           # курс доллара ЦБ
prizolov report SBER --source moex            # акция Мосбиржи
prizolov report BTC-USD                       # биткоин
```

Отчёт сохраняется в `workspace/reports/` (Markdown и PNG). Прогнозы записываются
в журнал и затем сверяются с фактом, так система учится. Это статистическая оценка
по истории цен, а не инвестиционная рекомендация.

## Telegram-бот

1. Создайте бота у [@BotFather](https://t.me/BotFather) и получите токен.
2. Узнайте свой Telegram ID у [@userinfobot](https://t.me/userinfobot).
3. В `.env`:

   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   PRIZOLOV_TELEGRAM_ALLOWED_IDS=111111111
   ```
4. Запустите: `prizolov telegram`.

Особенности бота:

- Отвечает только пользователям из списка; без списка не запускается.
- Показывает ход работы и присылает графики.
- Перед записью файла спрашивает кнопками «Разрешить» и «Отклонить».
- Присланные документы сохраняет в базу знаний.
- В процессе бота работает и расписание.

## Расписание

```
/schedule report "по будням 9:00" GOLD 1,7,15,30
/schedule add "по понедельникам 10:00" Обзор рынка металлов за неделю
/schedule                          список
/schedule run|pause|resume|remove N
```

- **Формат времени:** «ежедневно 09:00», «по будням 9:30», «по понедельникам 10:00»,
  «каждые 6 часов» или строка cron.
- **Часовой пояс:** `PRIZOLOV_TIMEZONE`, по умолчанию Москва.
- **Без команд:** можно просто попросить: «присылай каждое утро обзор золота».
- **Сверка прогнозов:** встроена, ежедневно в 08:50.
- **Где выполняется:** в процессе Telegram-бота, в отдельном процессе
  `prizolov scheduler` или в `prizolov api --scheduler`. Запускайте только один из них.

## HTTP API

```bash
# в .env: PRIZOLOV_API_KEYS=<ключ не короче 16 символов>
python -c "import secrets; print(secrets.token_urlsafe(32))"   # создать ключ
prizolov api                      # http://127.0.0.1:8800, документация /docs
```

```bash
KEY=...
curl -X POST localhost:8800/v1/tasks -H "Authorization: Bearer $KEY" \
     -H "Content-Type: application/json" -d '{"message": "Курс юаня ЦБ на неделю"}'
curl localhost:8800/v1/tasks/<id> -H "Authorization: Bearer $KEY"

curl -X POST localhost:8800/v1/reports -H "X-API-Key: $KEY" \
     -H "Content-Type: application/json" -d '{"symbol": "GOLD", "horizons": [1, 7, 15, 30]}'
```

Все методы описаны в [docs/api.md](docs/api.md).

## Использование из Python

```python
from prizolov_os.core.kernel import Kernel

kernel = Kernel.create()                       # настройки из .env
result = kernel.chat("Спрогнозируй цену серебра на 2 недели")
print(result.text, result.usage.cost_usd)
kernel.feedback(positive=False, comment="Указывай источник данных")
```

Отчёт без модели:

```python
from prizolov_os.forecasting import ForecastEngine, ForecastJournal
from prizolov_os.market import MarketData
from prizolov_os.memory import Store
from prizolov_os.reports import market_report, to_markdown

engine = ForecastEngine(ForecastJournal(Store("data/prizolov.db")))
report = market_report(MarketData(), engine, "GOLD", horizons=(1, 7, 15, 30))
print(to_markdown(report))
```

## Документация

- [docs/architecture.md](docs/architecture.md) — как устроена система:
  - агенты;
  - самообучение;
  - прогнозы;
  - база знаний;
  - безопасность.
- [docs/configuration.md](docs/configuration.md) — все настройки `.env`.
- [docs/api.md](docs/api.md) — HTTP API.

## Разработка

```bash
pip install -e ".[all]"
python -m pytest                                # тесты: сеть и ключ не нужны
ruff check .                                    # стиль кода
python scripts/stamp_headers.py                 # шапки авторства во всех файлах
```

Как устроен репозиторий:

- **CI на GitHub Actions** при каждом push и pull request запускает ruff, проверку
  шапок авторства и тесты на Python 3.10–3.13.
- **Версия и авторство** задаются только в `prizolov_os/__about__.py`; после
  изменения запустите `scripts/stamp_headers.py`.
- **Прежняя версия кода** лежит в папке `legacy/`.

## Авторство и лицензия

Copyright © 2026 **Dm.Andreyanov / Prizolov Lab**. Все права на программу принадлежат автору.

Распространяется по лицензии [Apache 2.0](LICENSE). При любом распространении программы
или производной работы обязательно сохранять уведомление об авторстве из файла
[NOTICE](NOTICE) и шапки файлов, а изменённые файлы — помечать. Цитирование:
[CITATION.cff](CITATION.cff). Авторы: [AUTHORS](AUTHORS).
