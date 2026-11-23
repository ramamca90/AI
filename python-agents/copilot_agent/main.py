"""Example: calling a Copilot Studio agent from a Python script.

    python main.py                       # runs the demo questions
    python main.py "your question here"  # one-off question
    python main.py --chat                # interactive chat loop
"""

import sys

import requests

from copilot_client import CopilotAgent, CopilotAgentError


def demo(agent: CopilotAgent) -> None:
    questions = [
        "Hi! What can you help me with?",
        "What are your opening hours?",
    ]
    for q in questions:
        print(f"\nYou: {q}")
        print(f"Agent: {agent.ask(q)}")


def chat(agent: CopilotAgent) -> None:
    print("Chat with the Copilot agent (type 'exit' to quit, 'new' for a fresh conversation).")
    while True:
        q = input("\nYou: ").strip()
        if q.lower() in ("exit", "quit"):
            agent.end_conversation()
            break
        if q.lower() == "new":
            agent.new_conversation()
            continue
        if q:
            print(f"Agent: {agent.ask(q)}")


def main() -> None:
    try:
        agent = CopilotAgent()
        if "--chat" in sys.argv:
            chat(agent)
        elif len(sys.argv) > 1:
            print(agent.ask(" ".join(sys.argv[1:])))
        else:
            demo(agent)
    except CopilotAgentError as e:
        sys.exit(f"Error: {e}")
    except requests.ConnectionError:
        sys.exit("Could not reach Direct Line - check your network.")


if __name__ == "__main__":
    main()
