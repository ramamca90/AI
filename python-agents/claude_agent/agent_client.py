"""Reusable Python wrapper for calling the agent from any script.

    from agent_client import ClaudeAgent

    agent = ClaudeAgent()
    print(agent.ask("Where is my order A1001?"))
    print(agent.ask("And how many days until it arrives from 2026-11-23?"))  # same conversation
"""

import json
import sys
from pathlib import Path

import anthropic

from tools import run_tool

CONFIG_FILE = Path(__file__).with_name("agent_config.json")


class ClaudeAgent:
    def __init__(self, verbose: bool = True, interactive_approvals: bool | None = None):
        if not CONFIG_FILE.exists():
            raise RuntimeError("agent_config.json not found - run `python setup_agent.py` first.")
        cfg = json.loads(CONFIG_FILE.read_text())
        self.client = anthropic.Anthropic()
        self.agent_id = cfg["agent_id"]
        self.agent_version = cfg["agent_version"]
        self.environment_id = cfg["environment_id"]
        self.verbose = verbose
        # Ask a human before risky sandbox commands only when someone is at the terminal.
        self.interactive_approvals = (
            sys.stdin.isatty() if interactive_approvals is None else interactive_approvals
        )
        self.session_id: str | None = None

    # ------------------------------------------------------------------ public

    def new_session(self, title: str = "Python script session") -> str:
        """Start a fresh conversation (a new sandbox container)."""
        session = self.client.beta.sessions.create(
            agent={"type": "agent", "id": self.agent_id, "version": self.agent_version},
            environment_id=self.environment_id,
            title=title,
        )
        self.session_id = session.id
        self._log(f"[session {session.id} started]")
        return session.id

    def ask(self, prompt: str) -> str:
        """Send a message and block until the agent finishes. Returns its reply text."""
        if self.session_id is None:
            self.new_session()
        session_id = self.session_id
        reply_parts: list[str] = []

        # Stream-first: open the event stream, then send the message.
        with self.client.beta.sessions.events.stream(session_id=session_id) as stream:
            self.client.beta.sessions.events.send(
                session_id=session_id,
                events=[{"type": "user.message", "content": [{"type": "text", "text": prompt}]}],
            )

            for event in stream:
                if event.type == "agent.message":
                    for block in event.content:
                        if block.type == "text":
                            reply_parts.append(block.text)

                elif event.type == "agent.custom_tool_use":
                    # The agent wants to call one of OUR Python tools (tools.py).
                    self._log(f"[tool call] {event.name}({json.dumps(event.input)})")
                    result, is_error = run_tool(event.name, event.input)
                    self._log(f"[tool result] {result}")
                    self.client.beta.sessions.events.send(
                        session_id=session_id,
                        events=[{
                            "type": "user.custom_tool_result",
                            "custom_tool_use_id": event.id,
                            "content": [{"type": "text", "text": result}],
                            "is_error": is_error,
                        }],
                    )

                elif event.type == "agent.tool_use":
                    # Built-in sandbox tool (bash, file edit, ...).
                    self._log(f"[sandbox tool] {event.name}")
                    if getattr(event, "evaluated_permission", None) == "ask":
                        decision = "allow" if self._approve(event) else "deny"
                        self.client.beta.sessions.events.send(
                            session_id=session_id,
                            events=[{
                                "type": "user.tool_confirmation",
                                "tool_use_id": event.id,
                                "result": decision,
                            }],
                        )

                elif event.type == "session.status_idle":
                    # requires_action = waiting on us (tool result / approval): keep streaming.
                    if event.stop_reason.type != "requires_action":
                        break

                elif event.type == "session.status_terminated":
                    self.session_id = None
                    break

        return "".join(reply_parts).strip()

    # ----------------------------------------------------------------- helpers

    def _approve(self, event) -> bool:
        if not self.interactive_approvals:
            self._log("[approval] no one at the terminal - denying")
            return False
        answer = input(
            f"\nAgent wants to run {event.name} with {json.dumps(event.input)[:300]}\nAllow? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr)
