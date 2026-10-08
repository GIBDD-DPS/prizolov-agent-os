# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    def __init__(self, name: str, priority: int = 1):
        self.name = name
        self.priority = priority

    @abstractmethod
    def evaluate(self, context) -> float:
        """
        Оценка релевантности (0.0 - 1.0)
        """
        pass

    @abstractmethod
    def run(self, context):
        """
        Выполнение задачи
        """
        pass

    def can_handle(self, context) -> bool:
        return self.evaluate(context) > 0.5
