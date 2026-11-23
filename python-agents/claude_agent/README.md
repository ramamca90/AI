# Sample Claude Agent (called from Python)

A minimal agent built on **Claude Managed Agents**: Anthropic runs the agent loop
and a sandbox container (bash, files, code execution), while your Python script
sends it messages and serves **custom tools** that run locally.

```
main.py ──► agent_client.ClaudeAgent.ask("...") ──► Anthropic (agent loop + sandbox)
                     ▲                                         │
                     └──── tools.py (lookup_order, calculate) ◄┘  custom tool calls
```

## Files

| File | Purpose |
|---|---|
| `setup_agent.py` | **Run once.** Creates the environment + agent, saves IDs to `agent_config.json`. `--update` pushes prompt/tool changes as a new agent version. |
| `agent_client.py` | `ClaudeAgent` class – import this from any script. `ask()` returns the reply text; follow-up calls keep the same conversation. |
| `tools.py` | Your own tools (schema + Python implementation). Add new ones here. |
| `main.py` | Example usage: demo, one-off question, or `--chat`. |

## Setup (Windows PowerShell)

```powershell
cd python-agents/claude_agent
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # from https://platform.claude.com
python setup_agent.py
python main.py
```

## Use it from your own script

```python
from agent_client import ClaudeAgent

agent = ClaudeAgent()
print(agent.ask("Where is order A1001?"))
print(agent.ask("How many days from 2026-11-23 is that?"))  # same conversation
agent.new_session()                                          # start fresh
```

## Adding a tool

1. Add its schema to `CUSTOM_TOOLS` and a handler to `TOOL_HANDLERS` in `tools.py`.
2. Run `python setup_agent.py --update` (creates a new agent version).

## Notes

- Model: `claude-opus-5-5`. Change `MODEL` in `setup_agent.py`, then `--update`.
- Managed Agents is in beta; billing is token usage plus session runtime, and
  session history is kept until you delete it.
- Web search/fetch are disabled; enable them in `setup_agent.py` if needed.
- Sandbox commands flagged as risky pause for approval: you're prompted in the
  terminal, and they're denied automatically when no one is at the keyboard.
