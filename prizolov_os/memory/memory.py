
class Memory:
    def __init__(self):
        self.data = []

    def store(self, q, r):
        self.data.append((q, r))

    def retrieve(self, q):
        return " ".join([r for x, r in self.data if q.split()[0] in x])
