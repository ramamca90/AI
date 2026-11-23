"""Example: calling the agent from a Python script.

    python main.py                       # runs the demo questions
    python main.py "your question here"  # one-off question
    python main.py --chat                # interactive chat loop
"""

import sys

import anthropic

from agent_client import ClaudeAgent


def demo(agent: ClaudeAgent) -> None:
    questions = [
        "Hi! What's the status of order A1002?",
        "If the item costs 1499 rupees and I get 12% off, what do I pay?",
        "Write a small Python script in your workspace that prints the first 10 "
        "Fibonacci numbers, run it, and tell me the output.",
    ]
    for q in questions:
        print(f"\nYou: {q}")
        print(f"Agent: {agent.ask(q)}")


def chat(agent: ClaudeAgent) -> None:
    print("Chat with the agent (type 'exit' to quit, 'new' for a fresh session).")
    while True:
        q = input("\nYou: ").strip()
        if q.lower() in ("exit", "quit"):
            break
        if q.lower() == "new":
            agent.new_session()
            continue
        if q:
            print(f"Agent: {agent.ask(q)}")


def main() -> None:
    agent = ClaudeAgent()
    try:
        if "--chat" in sys.argv:
            chat(agent)
        elif len(sys.argv) > 1:
            print(agent.ask(" ".join(sys.argv[1:])))
        else:
            demo(agent)
    except anthropic.AuthenticationError:
        sys.exit("Authentication failed - set ANTHROPIC_API_KEY (or run `ant auth login`).")
    except anthropic.RateLimitError:
        sys.exit("Rate limited - wait a moment and try again.")
    except anthropic.APIStatusError as e:
        sys.exit(f"API error {e.status_code}: {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("Could not reach the Anthropic API - check your network.")


if __name__ == "__main__":
    main()
