# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from agents.base_agent import BaseAgent


class EchoAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="EchoAgent", priority=2)

    def evaluate(self, context) -> float:
        if "echo" in context.input.lower():
            return 0.9
        return 0.2

    def run(self, context):
        return f"[EchoAgent] {context.input}"
