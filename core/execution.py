# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from core.context import ExecutionContext
from memory.memory_system import MemorySystem


class ExecutionEngine:
    def __init__(self, director):
        self.director = director

        # 🔥 ГЛОБАЛЬНАЯ ПАМЯТЬ (ОДИН ЭКЗЕМПЛЯР)
        self.memory = MemorySystem()

    def run(self, user_input: str):
        # 🔥 ПЕРЕДАЁМ ТУ ЖЕ САМУЮ ПАМЯТЬ КАЖДЫЙ РАЗ
        context = ExecutionContext(user_input, self.memory)

        result = self.director.handle(context)

        return result
