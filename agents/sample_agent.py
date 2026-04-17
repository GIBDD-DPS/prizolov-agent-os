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
        return 0.6

    def run(self, context):
        user_input = context.input

        last_agent = context.memory.get_fact("last_agent")

        if last_agent:
            response = f"[SampleAgent] Last agent was: {last_agent} | Input: {user_input}"
        else:
            response = f"[SampleAgent] Processed: {user_input}"

        context.memory.store_fact("last_input", user_input)

        return response
