# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

"""
Prizolov Agent OS - Agentic AI Operating System.

Фреймворк для оркестрации автономных ИИ-агентов с поддержкой RAG-архитектуры.
"""

from .__about__ import (
    PROJECT_ID,
    __author__,
    __brand__,
    __copyright__,
    __email__,
    __license__,
    __version__,
)
from .agent import Agent
from .config import settings

__all__ = [
    "PROJECT_ID",
    "Agent",
    "settings",
    "__author__",
    "__brand__",
    "__copyright__",
    "__email__",
    "__license__",
    "__version__",
]
