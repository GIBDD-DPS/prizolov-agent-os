# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class SampleAgent:
    def __init__(self):
        self.name = "SampleAgent"

    def can_handle(self, context):
        return True  # пока принимает всё

    def run(self, context):
        user_input = context.input
        response = f"Processed: {user_input}"
        return response
