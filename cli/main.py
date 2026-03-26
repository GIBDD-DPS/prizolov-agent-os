import argparse
from prizolov_os.agent import Agent
from prizolov_os.kernel import Kernel

def main():
    parser = argparse.ArgumentParser(description="Prizolov OS CLI")
    parser.add_argument("command", help="Command to run")
    parser.add_argument("--input", help="Input text")

    args = parser.parse_args()

    kernel = Kernel()
    agent = Agent(role="Universal Agent")

    if args.command == "run":
        result = kernel.run(agent, args.input)
        print(result)

if __name__ == "__main__":
    main()
