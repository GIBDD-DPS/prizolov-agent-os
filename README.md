# 🤖 Prizolov Agent OS

**Agentic AI Operating System** — фреймворк для оркестрации автономных ИИ-агентов с поддержкой RAG-архитектуры и принципами "Sovereign AI".

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
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

### Требования

- Python 3.9+
- pip 21.0+

### Установка из исходников

```bash
# Клонируйте репозиторий
git clone https://github.com/GIBDD-DPS/prizolov-agent-os.git
cd prizolov-agent-os

# Создайте виртуальное окружение (рекомендуется)
python -m venv venv
source venv/bin/activate  # macOS/Linux
# или
venv\Scripts\activate     # Windows

# Установите зависимости
pip install -r requirements.txt

# Установите пакет
pip install -e .
