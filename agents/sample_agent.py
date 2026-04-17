# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from agents.base_agent import BaseAgent


class SampleAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="SampleAgent", priority=1)

    def evaluate(self, context) -> float:
        # базовый агент — всегда средний приоритет
        return 0.6

    def run(self, context):
        user_input = context.input
        response = f"[SampleAgent] Processed: {user_input}"
        return response
