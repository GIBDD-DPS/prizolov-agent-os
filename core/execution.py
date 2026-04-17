# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from core.context import ExecutionContext


class ExecutionEngine:
    def __init__(self, director):
        self.director = director

    def run(self, user_input: str):
        context = ExecutionContext(user_input)

        result = self.director.handle(context)

        return result
