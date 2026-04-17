# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from core.execution import ExecutionEngine
from core.director import Director
from core.orchestrator import Orchestrator
from agents.echo_agent import EchoAgent

def main():
    agents = [EchoAgent()]          # SampleAgent полностью исключён
    orchestrator = Orchestrator(agents)
    director = Director(orchestrator)
    engine = ExecutionEngine(director)

    while True:
        user_input = input(">> ")
        result = engine.run(user_input)
        print(result)

if __name__ == "__main__":
    main()
