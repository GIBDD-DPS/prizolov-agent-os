<!-- Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
SPDX-License-Identifier: Apache-2.0 -->

# MCP-сервер: Prizolov в Claude Desktop, Cursor и Claude Code

MCP (Model Context Protocol) — стандарт, по которому ИИ-приложения подключают внешние
инструменты. `prizolov mcp` отдаёт инструменты Prizolov любой программе с поддержкой
MCP. Модель работает в самой программе, поэтому ключ Claude серверу не нужен.

## Установка

```bash
pip install -e ".[mcp]"        # из папки проекта
which prizolov                 # полный путь к команде - понадобится ниже (Windows: where prizolov)
```

Программа запускает сервер из своей папки, а не из папки проекта, и файл `.env` там не
читается. Поэтому пути к рабочей папке и базе укажите полностью, в настройках сервера.

## Claude Desktop

Файл настроек:

- macOS — `~/Library/Application Support/Claude/claude_desktop_config.json`;
- Windows — `%APPDATA%\Claude\claude_desktop_config.json`.

Его же открывает Settings → Developer → Edit Config.

```json
{
  "mcpServers": {
    "prizolov": {
      "command": "/полный/путь/к/prizolov",
      "args": ["mcp"],
      "env": {
        "PRIZOLOV_WORKSPACE": "/Users/me/prizolov/workspace",
        "PRIZOLOV_DB_PATH": "/Users/me/prizolov/data/prizolov.db",
        "PRIZOLOV_MCP_ROOTS": "/Users/me/Downloads"
      }
    }
  }
}
```

Перезапустите Claude Desktop. Инструменты Prizolov появятся в списке инструментов чата.

## Cursor

Файл `~/.cursor/mcp.json` (для всех проектов) или `.cursor/mcp.json` в проекте. Формат
тот же, что у Claude Desktop: секция `mcpServers`.

## Claude Code

```bash
claude mcp add prizolov --env PRIZOLOV_WORKSPACE=$HOME/prizolov/workspace \
  --env PRIZOLOV_DB_PATH=$HOME/prizolov/data/prizolov.db -- prizolov mcp
```

## Инструменты

| Инструмент | Что делает |
|---|---|
| `market_forecast` | прогноз цены на несколько горизонтов: интервалы 80%/95%, вероятность роста, надёжность метода. Источники: ЦБ РФ, Мосбиржа, Yahoo |
| `analyze_bank_statement` | выписка 1С/CSV/Excel: статьи, помесячно, прогноз остатка, платёжный календарь и день кассового разрыва |
| `payment_calendar_list`, `payment_calendar_add`, `payment_calendar_remove` | плановые платежи и поступления |
| `portfolio_analysis` | портфель из CSV/Excel: доли, VaR, просадка, стресс-тесты, прогнозы по бумагам |
| `search_tenders` | открытые госзакупки 44-ФЗ/223-ФЗ в ЕИС |
| `compare_documents` | что изменилось между версиями договора |
| `read_document` | текст PDF, Word, Excel, TXT |
| `search_documents` | поиск по документам рабочей папки |
| `forecast_accuracy` | статистика: сколько прогнозов сбылось |

Примеры запросов в Claude Desktop:

- «Сделай прогноз по золоту ЦБ на 7 и 30 дней и объясни, насколько он надёжен».
- «Проанализируй выписку ~/Downloads/kl_to_1c.txt: будет ли кассовый разрыв в ноябре?»
- «Найди открытые закупки на поставку офисной мебели до 3 млн рублей».
- «Сравни две версии договора в папке Downloads и скажи, что стало хуже для нас».

## Доступ к файлам

Сервер читает файлы только:

- из рабочей папки `PRIZOLOV_WORKSPACE` — по относительному пути;
- из папок в `PRIZOLOV_MCP_ROOTS` — по полному пути; папки перечисляются через запятую.

Остальные пути отклоняются. Записывает сервер только в свою базу: плановые платежи,
журнал прогнозов, отметки о показанных закупках.

## Проверка

```bash
PRIZOLOV_WORKSPACE=$HOME/prizolov/workspace prizolov mcp   # ждёт команд по stdio; Ctrl+C - выход
npx @modelcontextprotocol/inspector prizolov mcp           # визуальная проверка инструментов
```
