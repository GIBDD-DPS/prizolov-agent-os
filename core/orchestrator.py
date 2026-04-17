# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class Orchestrator:
    def __init__(self, agents):
        self.agents = agents

    def process(self, context):
        for agent in self.agents:
            if agent.can_handle(context):
                result = agent.run(context)
                context.log(f"{agent.name} executed")
                return result

        return "No agent could handle request"
