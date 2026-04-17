# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class Orchestrator:
    def __init__(self, agents):
        self.agents = agents

    def process(self, context):
        scored_agents = []

        for agent in self.agents:
            score = agent.evaluate(context)
            scored_agents.append((agent, score))
            context.log(f"{agent.name} score: {score}")

        scored_agents.sort(key=lambda x: (x[1], x[0].priority), reverse=True)

        best_agent, best_score = scored_agents[0]

        if best_score < 0.3:
            context.memory.store_episode("No suitable agent found")
            return "No suitable agent found"

        context.log(f"Selected agent: {best_agent.name}")
        context.memory.store_fact("last_agent", best_agent.name)

        result = best_agent.run(context)

        context.log(f"{best_agent.name} executed")

        return result
