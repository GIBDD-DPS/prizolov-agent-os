# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

from prizolov_os.agent import Agent
from prizolov_os.kernel import Kernel

kernel = Kernel()

seo_agent = Agent(
    role="SEO Generator",
    constraints={"forbidden_tokens": ["spam", "blackhat"]}
)

print(kernel.run(seo_agent, "Write SEO text about drones"))
