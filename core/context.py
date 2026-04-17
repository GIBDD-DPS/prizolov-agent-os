class ExecutionContext:
    def __init__(self, user_input: str):
        self.input = user_input
        self.state = {}
        self.history = []
        self.metadata = {}

    def update(self, key, value):
        self.state[key] = value

    def log(self, message):
        self.history.append(message)
