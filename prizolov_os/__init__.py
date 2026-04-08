"""
Prizolov Agent OS - Agentic AI Operating System.

Фреймворк для оркестрации автономных ИИ-агентов с поддержкой RAG-архитектуры.
"""

__version__ = "0.2.0.dev0"
__author__ = "Dm.Andreyanov"
__email__ = "contact@prizolov.ru"

from .agent import Agent
from .config import settings

__all__ = ["Agent", "settings", "__version__"]
