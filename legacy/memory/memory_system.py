# ============================================
# Prizolov Agent OS v2.001
# Author: Dm.Andreyanov
# Organization: Prizolov Market / Prizolov Lab
# ============================================

class MemorySystem:
    def __init__(self):
        self.episodic = []
        self.semantic = {}
        self.working = {}

    def store_episode(self, event: str):
        self.episodic.append(event)

    def get_episodes(self, limit=10):
        return self.episodic[-limit:]

    def store_fact(self, key: str, value):
        self.semantic[key] = value

    def get_fact(self, key: str):
        return self.semantic.get(key)

    def set_context(self, key: str, value):
        self.working[key] = value

    def get_context(self, key: str):
        return self.working.get(key)

    def clear_working(self):
        self.working = {}
