from prizolov_os.agent import Agent

def test_agent():
    agent = Agent(role="test")
    result = agent.execute("hello")
    assert "hello" in result
