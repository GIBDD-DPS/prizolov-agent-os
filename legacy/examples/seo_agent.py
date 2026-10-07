from prizolov_os.agent import Agent
from prizolov_os.kernel import Kernel

kernel = Kernel()

seo_agent = Agent(
    role="SEO Generator",
    constraints={"forbidden_tokens": ["spam", "blackhat"]}
)

print(kernel.run(seo_agent, "Write SEO text about drones"))
