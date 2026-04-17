# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class Director:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator

    def handle(self, context):
        context.log("Director received input")

        response = self.orchestrator.process(context)

        context.log("Director completed execution")

        return response
