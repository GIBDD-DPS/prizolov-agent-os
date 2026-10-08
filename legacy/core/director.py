# Prizolov Agent OS 0.3.0 | Author: Dm.Andreyanov | Brand: Prizolov Lab | © 2026
# SPDX-FileCopyrightText: 2026 Dm.Andreyanov / Prizolov Lab
# SPDX-License-Identifier: Apache-2.0

# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class Director:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def handle(self, context):
        context.log("Director started")

        response = self.orchestrator.process(context)

        context.memory.store_episode(f"Final response: {response}")

        context.log("Director finished")

        return response
