# Python Agents

Two sample projects that call an AI agent from a Python script.

| Folder | Agent platform | How Python connects |
|---|---|---|
| [`claude_agent`](claude_agent) | Claude Managed Agents (Anthropic) | `anthropic` SDK: sessions + event stream, with custom tools that run locally in Python |
| [`copilot_agent`](copilot_agent) | Microsoft Copilot Studio | Direct Line API v3 over HTTPS (`requests`) |

Both expose the same simple interface:

```python
agent = ClaudeAgent()        # or CopilotAgent()
print(agent.ask("Where is my order A1001?"))
```

See each folder's README for setup. Secrets go in environment variables or a local
`.env` file, which is git-ignored.
