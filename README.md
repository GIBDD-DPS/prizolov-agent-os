# 🤖 Prizolov Agent OS

**Agentic AI Operating System** — фреймворк для оркестрации автономных ИИ-агентов с поддержкой RAG-архитектуры и принципами "Sovereign AI".

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://badge.fury.io/py/prizolov-os.svg)](https://pypi.org/project/prizolov-os/)
[![Tests](https://github.com/GIBDD-DPS/prizolov-agent-os/actions/workflows/test.yml/badge.svg)](https://github.com/GIBDD-DPS/prizolov-agent-os/actions)

---

## 📋 Оглавление

- [Возможности](#-возможности)
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

## 📦 Установка

### Через pip (рекомендуется)

```bash
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
