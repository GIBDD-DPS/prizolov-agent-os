
class Orchestrator:
    def __init__(self, agents, memory):
        self.agents = agents
        self.memory = memory

    def plan(self, task):
        return [
            {"agent": "research", "task": f"Research: {task}"},
            {"agent": "writer", "task": f"Write: {task}"}
        ]

    def execute(self, plan):
        results = []
        for step in plan:
            agent = self.agents[step["agent"]]
            ctx = self.memory.retrieve(step["task"])
            out = agent.run(step["task"], ctx)
            self.memory.store(step["task"], out)
            results.append(out)
        return results
