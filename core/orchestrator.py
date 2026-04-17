# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class Orchestrator:
    def __init__(self, agents):
        self.agents = agents

    def process(self, context):
        print("DEBUG: NEW ORCHESTRATOR VERSION")
        best_agent = None
        best_score = 0

        for agent in self.agents:
            score = agent.evaluate(context)
            context.log(f"{agent.name} score: {score}")

            if score > best_score:
                best_score = score
                best_agent = agent

        if not best_agent:
            return "No suitable agent"

        # 👉 ДО выполнения — читаем прошлое
        previous_agent = context.memory.get_fact("last_agent")

        context.log(f"Selected agent: {best_agent.name}")

        result = best_agent.run(context)

        # 👉 ПОСЛЕ выполнения — обновляем
        if previous_agent:
            context.memory.store_fact("previous_agent", previous_agent)

        context.memory.store_fact("last_agent", best_agent.name)

        return result
