# Copilot Studio agent from Python

Calls an agent built in **Microsoft Copilot Studio** from a Python script, using the
**Direct Line API v3** (plain HTTPS + `requests`).

```
main.py ──► CopilotAgent.ask("...") ──► Direct Line ──► your Copilot Studio agent
                    ▲                                         │
                    └──────── poll for reply activities ◄─────┘
```

The agent's topics, knowledge, actions and tools are all configured in Copilot Studio;
this Python side only sends messages and reads replies.

## Files

| File | Purpose |
|---|---|
| `copilot_client.py` | `CopilotAgent` class: starts a conversation, sends messages, waits for replies, refreshes the token. |
| `main.py` | Example usage: demo, one-off question, or `--chat`. |

## 1. Get credentials from Copilot Studio

Publish the agent first, then use **one** of these:

- **Web channel secret** (works for any agent):
  Copilot Studio > your agent > **Settings > Security > Web channel security** > copy *Secret 1*.
- **Token endpoint** (only if the agent's authentication is set to *No authentication*):
  **Channels > Mobile app** > copy the *Token Endpoint* URL.

## 2. Put the credentials in `.env`

Copy `.env.example` to `.env` (same folder) and fill in one value, e.g.

```
COPILOT_DIRECTLINE_SECRET=abc123...
```

`.env` is git-ignored. Environment variables also work and take priority
(PowerShell: `$env:COPILOT_DIRECTLINE_SECRET = "..."`, Git Bash: `export COPILOT_DIRECTLINE_SECRET="..."`).

## 3. Run

```
pip install -r requirements.txt
python main.py --chat
```

If your environment is in a non-US region and you get 401/403 errors, also set the regional host, e.g.
`$env:COPILOT_DIRECTLINE_DOMAIN = "https://europe.directline.botframework.com"`.

## 3. Use it from your own script

```python
from copilot_client import CopilotAgent

agent = CopilotAgent()
print(agent.ask("Where is order A1001?"))
print(agent.ask("When will it arrive?"))   # same conversation

for activity in agent.ask_raw("Show me options"):   # full JSON (adaptive cards, buttons...)
    print(activity)
```

## Notes

- Keep the secret out of source control; read it from an environment variable or a vault.
- Replies are collected by polling every second until the agent has been quiet for ~2 s
  (timeout 60 s, `reply_timeout=` to change).
- Agents that use **user authentication (Entra ID sign-in)** need a sign-in card flow and
  aren't handled by this sample.
