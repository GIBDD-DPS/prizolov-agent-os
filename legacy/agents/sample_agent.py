# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from agents.base_agent import BaseAgent


class SampleAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="SampleAgent", priority=1)

    def evaluate(self, context) -> float:
        return 0.6

    def run(self, context):
        previous_agent = context.memory.get_fact("previous_agent")

        if previous_agent:
            return f"[SampleAgent] Last agent was: {previous_agent} | Input: {context.input}"

        return f"[SampleAgent] Processed: {context.input}"
