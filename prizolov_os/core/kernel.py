
class Kernel:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def run(self, task):
        plan = self.orchestrator.plan(task)
        return self.orchestrator.execute(plan)
