
from prizolov_os.core.kernel import Kernel
from prizolov_os.core.orchestrator import Orchestrator
from prizolov_os.memory.memory import Memory
from prizolov_os.agents.research_agent import ResearchAgent
from prizolov_os.agents.writer_agent import WriterAgent

agents = {
    "research": ResearchAgent(),
    "writer": WriterAgent()
}

memory = Memory()
orch = Orchestrator(agents, memory)
kernel = Kernel(orch)

print(kernel.run("buy drone 2026"))
