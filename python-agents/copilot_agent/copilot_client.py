"""Python client for a Microsoft Copilot Studio agent, via the Direct Line API (v3).

    from copilot_client import CopilotAgent

    agent = CopilotAgent()                 # reads settings from environment variables
    print(agent.ask("Where is my order A1001?"))
    print(agent.ask("When will it arrive?"))   # same conversation
    agent.new_conversation()                   # start fresh

Authentication - set ONE of these environment variables:
  COPILOT_DIRECTLINE_SECRET   Web channel security secret
                              (Copilot Studio > Settings > Security > Web channel security)
  COPILOT_TOKEN_ENDPOINT      Token endpoint URL for agents with no authentication
                              (Copilot Studio > Channels > Mobile app > Token Endpoint)

Optional:
  COPILOT_DIRECTLINE_DOMAIN   Regional Direct Line host, default
                              https://directline.botframework.com
                              (e.g. https://europe.directline.botframework.com)
"""

from __future__ import annotations

import os
import sys
import time
import uuid

import requests

from pathlib import Path

DEFAULT_DOMAIN = "https://directline.botframework.com"
ENV_FILE = Path(__file__).with_name(".env")


def _load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines from .env next to this file (real env vars win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if value and not os.environ.get(key):
            os.environ[key] = value


_load_env_file()


class CopilotAgentError(RuntimeError):
    pass


class CopilotAgent:
    def __init__(
        self,
        secret: str | None = None,
        token_endpoint: str | None = None,
        domain: str | None = None,
        user_id: str | None = None,
        user_name: str = "Python script",
        reply_timeout: float = 60.0,
        verbose: bool = True,
    ):
        self.secret = secret or os.getenv("COPILOT_DIRECTLINE_SECRET")
        self.token_endpoint = token_endpoint or os.getenv("COPILOT_TOKEN_ENDPOINT")
        if not self.secret and not self.token_endpoint:
            raise CopilotAgentError(
                "No credentials found. Copy .env.example to .env and put your "
                "COPILOT_DIRECTLINE_SECRET (or COPILOT_TOKEN_ENDPOINT) in it, "
                f"or set it as an environment variable. Looked for: {ENV_FILE}"
            )
        self.domain = (domain or os.getenv("COPILOT_DIRECTLINE_DOMAIN") or DEFAULT_DOMAIN).rstrip("/")
        self.base_url = f"{self.domain}/v3/directline"
        # Direct Line user IDs must not start with "dl_".
        self.user = {"id": user_id or f"user-{uuid.uuid4().hex[:12]}", "name": user_name}
        self.reply_timeout = reply_timeout
        self.verbose = verbose

        self.http = requests.Session()
        self.token: str | None = None
        self.token_expires_at = 0.0
        self.conversation_id: str | None = None
        self.watermark: str | None = None

    # ------------------------------------------------------------------ public

    def new_conversation(self) -> str:
        """Start a new conversation with the agent and return its ID."""
        self.token = self._get_token()
        data = self._request("POST", "/conversations")
        self.conversation_id = data["conversationId"]
        self.token = data.get("token", self.token)
        self.token_expires_at = time.time() + int(data.get("expires_in", 1800))
        self.watermark = None
        self._log(f"[conversation {self.conversation_id} started]")
        return self.conversation_id

    def ask(self, text: str) -> str:
        """Send a message and wait for the agent's reply. Returns the reply text."""
        replies = self.ask_raw(text)
        parts = []
        for activity in replies:
            if activity.get("text"):
                parts.append(activity["text"])
            for att in activity.get("attachments") or []:
                parts.append(f"[attachment: {att.get('contentType')}]")
            actions = (activity.get("suggestedActions") or {}).get("actions") or []
            if actions:
                parts.append("Options: " + ", ".join(a.get("title", "") for a in actions))
        return "\n".join(parts).strip()

    def ask_raw(self, text: str) -> list[dict]:
        """Send a message and return the agent's reply activities (full JSON)."""
        if self.conversation_id is None:
            self.new_conversation()
        self._refresh_token_if_needed()

        sent = self._request(
            "POST",
            f"/conversations/{self.conversation_id}/activities",
            json={"type": "message", "from": self.user, "text": text, "locale": "en-US"},
        )
        sent_id = sent.get("id")
        return self._collect_replies(sent_id)

    def end_conversation(self) -> None:
        """Tell the agent the conversation is over (optional)."""
        if self.conversation_id is None:
            return
        try:
            self._request(
                "POST",
                f"/conversations/{self.conversation_id}/activities",
                json={"type": "endOfConversation", "from": self.user},
            )
        finally:
            self.conversation_id = None

    # ----------------------------------------------------------------- helpers

    def _collect_replies(self, sent_id: str | None) -> list[dict]:
        """Poll for activities until the agent has replied and gone quiet."""
        replies: list[dict] = []
        deadline = time.monotonic() + self.reply_timeout
        quiet_polls = 0

        while time.monotonic() < deadline:
            params = {"watermark": self.watermark} if self.watermark else None
            data = self._request(
                "GET", f"/conversations/{self.conversation_id}/activities", params=params
            )
            self.watermark = data.get("watermark", self.watermark)

            new = [
                a for a in data.get("activities", [])
                if a.get("from", {}).get("id") != self.user["id"] and a.get("type") == "message"
            ]
            if new:
                replies.extend(new)
                quiet_polls = 0
            elif replies:
                quiet_polls += 1
                # Agents often send several messages; stop after ~2s of silence.
                if quiet_polls >= 2:
                    break
            time.sleep(1.0)

        if not replies:
            raise CopilotAgentError(
                f"No reply from the agent within {self.reply_timeout:.0f}s (message {sent_id})."
            )
        return replies

    def _get_token(self) -> str:
        if self.token_endpoint:
            resp = self.http.get(self.token_endpoint, timeout=30)
            self._raise_for_status(resp, "token endpoint")
            return resp.json()["token"]
        # Exchange the secret for a short-lived token so the secret is used only once.
        resp = self.http.post(
            f"{self.base_url}/tokens/generate",
            headers={"Authorization": f"Bearer {self.secret}"},
            json={"user": self.user},
            timeout=30,
        )
        self._raise_for_status(resp, "tokens/generate")
        return resp.json()["token"]

    def _refresh_token_if_needed(self) -> None:
        # Direct Line tokens last 30 minutes; refresh when < 5 minutes remain.
        if self.token and time.time() > self.token_expires_at - 300:
            data = self._request("POST", "/tokens/refresh")
            self.token = data["token"]
            self.token_expires_at = time.time() + int(data.get("expires_in", 1800))
            self._log("[token refreshed]")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        resp = self.http.request(
            method,
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=30,
            **kwargs,
        )
        self._raise_for_status(resp, f"{method} {path}")
        return resp.json() if resp.content else {}

    @staticmethod
    def _raise_for_status(resp: requests.Response, what: str) -> None:
        if resp.status_code >= 400:
            hint = ""
            if resp.status_code in (401, 403):
                hint = " - check the secret / token endpoint and the Direct Line region."
            raise CopilotAgentError(f"{what} failed: HTTP {resp.status_code} {resp.text[:300]}{hint}")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(msg, file=sys.stderr)
