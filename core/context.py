# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class ExecutionContext:
    def __init__(self, user_input: str, memory):
        self.input = user_input
        self.state = {}
        self.history = []
        self.metadata = {}

        # 🔥 ВАЖНО: НЕ СОЗДАЁМ НОВУЮ ПАМЯТЬ
        self.memory = memory

    def update(self, key, value):
        self.state[key] = value

    def get(self, key, default=None):
        return self.state.get(key, default)

    def log(self, message):
        self.history.append(message)
        self.memory.store_episode(message)