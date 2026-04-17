# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

from memory.memory_system import MemorySystem


class ExecutionContext:
    def __init__(self, user_input: str):
        self.input = user_input
        self.state = {}
        self.history = []
        self.metadata = {}

        self.memory = MemorySystem()

    def update(self, key, value):
        self.state[key] = value

    def get(self, key, default=None):
        return self.state.get(key, default)

    def log(self, message):
        self.history.append(message)
        self.memory.store_episode(message)
