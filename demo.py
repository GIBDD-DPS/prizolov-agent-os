from prizolov_os.kernel import Kernel
from prizolov_os.agent import Agent

kernel = Kernel()
agent = Agent(role="Demo")

print(kernel.run(agent, "Hello AI"))
