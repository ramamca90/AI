"""ONE-TIME setup: create the environment and the agent, save their IDs.

Run this once:   python setup_agent.py
Then use the agent from any script via agent_client.ClaudeAgent.

Agents are persistent, versioned objects - do NOT create one on every run.
To change the prompt/tools later, run:  python setup_agent.py --update
"""

import json
import sys
from pathlib import Path

import anthropic

from tools import CUSTOM_TOOLS

CONFIG_FILE = Path(__file__).with_name("agent_config.json")

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a helpful customer-support assistant for an online store.
- Use the lookup_order tool whenever the user mentions an order ID.
- Use the calculate tool for any arithmetic instead of doing it in your head.
- You also have a sandboxed Linux workspace (bash, file tools) if you need to write
  or run code.
Keep answers short and clear."""

TOOLS = [
    # Built-in tools that run in Anthropic's sandbox container (bash, files, ...)
    {
        "type": "agent_toolset_20260401",
        "default_config": {"enabled": True, "permission_policy": {"type": "auto"}},
        "configs": [
            # Web access off; set enabled=True if your agent needs the internet.
            {"name": "web_fetch", "enabled": False},
            {"name": "web_search", "enabled": False},
        ],
    },
    # Custom tools that run in YOUR Python process (see tools.py)
    *CUSTOM_TOOLS,
]


def main() -> None:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    if "--update" in sys.argv:
        cfg = json.loads(CONFIG_FILE.read_text())
        current = client.beta.agents.retrieve(cfg["agent_id"])
        agent = client.beta.agents.update(
            cfg["agent_id"],
            version=current.version,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
        )
        cfg["agent_version"] = agent.version
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
        print(f"Updated agent {agent.id} -> version {agent.version}")
        return

    if CONFIG_FILE.exists():
        print(f"{CONFIG_FILE.name} already exists - agent is set up. Use --update to change it.")
        return

    environment = client.beta.environments.create(
        name="sample-agent-env",
        config={
            "type": "cloud",
            "networking": {"type": "limited", "allow_package_managers": True},
        },
    )
    print(f"Created environment: {environment.id}")

    agent = client.beta.agents.create(
        name="Sample Support Agent",
        model=MODEL,
        system=SYSTEM_PROMPT,
        tools=TOOLS,
    )
    print(f"Created agent: {agent.id} (version {agent.version})")

    CONFIG_FILE.write_text(
        json.dumps(
            {
                "environment_id": environment.id,
                "agent_id": agent.id,
                "agent_version": agent.version,
            },
            indent=2,
        )
    )
    print(f"Saved IDs to {CONFIG_FILE.name}")


if __name__ == "__main__":
    main()
