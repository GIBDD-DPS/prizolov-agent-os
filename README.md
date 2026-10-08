<!-- Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
SPDX-License-Identifier: Apache-2.0 -->

**For business owners:** Reduce operational chaos by orchestrating multiple AI agents — not just building chatbots.

# 🤖 Prizolov Agent OS

**Автор:** Dm.Andreyanov · **Бренд:** Prizolov Lab · © 2026 · версия 0.3.0

**Agentic AI Operating System** — фреймворк для оркестрации автономных ИИ-агентов с поддержкой RAG-архитектуры и принципами "Sovereign AI".

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/prizolov-os.svg)](https://pypi.org/project/prizolov-os/)
[![Tests](https://github.com/GIBDD-DPS/prizolov-agent-os/actions/workflows/test.yml/badge.svg)](https://github.com/GIBDD-DPS/prizolov-agent-os/actions)
[![Business Ready](https://img.shields.io/badge/Business-Ready-00aa00.svg)](https://prizolov.ru)

🌐 [prizolov.ru](https://prizolov.ru) — AI solutions for business

---

## 📋 Оглавление

- [Возможности](#-возможности)
- [Пример для бизнеса](#-пример-для-бизнеса)
- [Установка](#-установка)
- [Быстрый старт](#-быстрый-старт)
- [Конфигурация](#-конфигурация)
- [Архитектура](#-архитектура)
- [Разработка](#-разработка)
- [Лицензия](#-лицензия)

---

## ✨ Возможности

- 🧠 **Оркестрация агентов** — координация нескольких ИИ-агентов для сложных задач
- 📚 **RAG-архитектура** — Retrieval-Augmented Generation для точных ответов
- 🔒 **Безопасность** — валидация входных данных, запрещённые токены
- 💾 **Память** — сохранение и поиск по истории взаимодействий
- ⚙️ **Конфигурация** — гибкие настройки через `.env` и переменные окружения
- 📊 **Логирование** — профессиональное логирование с разными уровнями
- 🧪 **Тесты** — покрытие тестами >90%

---

## 💼 Пример для бизнеса

```python
from prizolov_os import AgentOrchestrator

# Создаём агента для анализа финансового потока
cashflow_agent = AgentOrchestrator.create("cashflow_predictor")
result = cashflow_agent.run("Спрогнозировать остаток на счетах через 30 дней")
print(result)

---

## 📦 Установка
Через pip (рекомендуется)

# Базовая установка
pip install prizolov-os

# С зависимостями для разработки
pip install "prizolov-os[dev]"

# С поддержкой RAG
pip install "prizolov-os[rag]"

# С поддержкой LLM (OpenAI, Anthropic)
pip install "prizolov-os[llm]"

# Все зависимости сразу
pip install "prizolov-os[all]"

---

## 📄 Лицензия

Copyright © 2026 **Dm.Andreyanov / Prizolov Lab**. Все права на программу принадлежат автору.

Распространяется по лицензии [Apache 2.0](LICENSE). При любом распространении программы или
производной работы обязательно сохранять уведомление об авторстве из файла [NOTICE](NOTICE)
и шапки файлов, а изменённые файлы — помечать. Цитирование: [CITATION.cff](CITATION.cff).
