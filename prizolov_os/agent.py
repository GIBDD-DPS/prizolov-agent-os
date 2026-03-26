class Agent:
    def __init__(self, role, constraints=None):
        self.role = role
        self.constraints = constraints or {}

    def apply_constraints(self, input_data):
        if "forbidden_tokens" in self.constraints:
            for token in self.constraints["forbidden_tokens"]:
                if token in input_data:
                    raise ValueError(f"Forbidden token detected: {token}")
        return input_data

    def execute(self, input_data):
        return f"[{self.role}] processed: {input_data}"
