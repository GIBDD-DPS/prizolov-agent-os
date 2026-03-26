
import argparse
from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.memory.memory import Memory
from prizolov_os.agents.research_agent import ResearchAgent
from prizolov_os.agents.writer_agent import WriterAgent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    args = parser.parse_args()

    agents = {
        "research": ResearchAgent(),
        "writer": WriterAgent()
    }

    memory = Memory()
    orch = Orchestrator(agents, memory)
    kernel = Kernel(orch)

    result = kernel.run(args.task)
    print("\n".join(result))

if __name__ == "__main__":
    main()
