class Kernel:
    def __init__(self, api_key=None, mode="standard"):
        self.api_key = api_key
        self.mode = mode

    def run(self, agent, input_data):
        validated = agent.apply_constraints(input_data)
        result = agent.execute(validated)
        return result
