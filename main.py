# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from core.execution import ExecutionEngine
from core.director import Director
from core.orchestrator import Orchestrator
from core.meta import VERSION, SYSTEM_NAME

from agents.sample_agent import SampleAgent


def main():
    print(f"{SYSTEM_NAME} v{VERSION} initialized")

    agents = [SampleAgent()]

    orchestrator = Orchestrator(agents)
    director = Director(orchestrator)
    engine = ExecutionEngine(director)

    while True:
        user_input = input(">> ")
        result = engine.run(user_input)
        print(result)


if __name__ == "__main__":
    main()
