"""
Slack notification + interactive approval gate.

Two approval mechanisms behind request_action_approval(mode=...):
  auto    - approve automatically (CI / unattended demo)
  prompt  - decide at the terminal (y/N)
  slack   - REAL interactive Approve/Reject buttons over Socket Mode; the pipeline
            blocks until you click. Falls back to the terminal if Slack isn't
            configured or the connection fails.

Socket Mode = an outbound websocket, so there's no public inbound endpoint to
expose. Needs SLACK_BOT_TOKEN (chat:write) + SLACK_APP_TOKEN (connections:write),
and the bot must be invited to SLACK_CHANNEL.
"""

from __future__ import annotations

import json
import os
import ssl
import threading
import uuid

# macOS Python often lacks a configured CA bundle -> SSL CERTIFICATE_VERIFY_FAILED.
# Point both the HTTP client and the Socket Mode websocket at certifi's bundle.
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("SSL_CERT_DIR", os.path.dirname(certifi.where()))
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = None


def _channel() -> str:
    return os.environ.get("SLACK_CHANNEL", "#soc-alerts")


def post_message(text: str) -> dict:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return {"posted": False, "reason": "SLACK_BOT_TOKEN not set"}
    try:
        from slack_sdk import WebClient
        resp = WebClient(token=token, ssl=_SSL_CONTEXT).chat_postMessage(
            channel=_channel(), text=text)
        return {"posted": True, "ts": resp.get("ts")}
    except Exception as exc:
        return {"posted": False, "error": str(exc)}


# --------------------------------------------------------------------------- #
# Interactive Slack approval (Socket Mode) — one message + buttons per action.
# --------------------------------------------------------------------------- #

class _SlackApprover:
    """Singleton: opens one Socket Mode connection, posts action approvals with
    Approve/Reject buttons, and blocks each request until the matching click."""

    def __init__(self):
        import logging
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
        from slack_sdk import WebClient

        logging.getLogger("slack_bolt").setLevel(logging.ERROR)  # silence "token unused" notice

        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        # WebClient with certifi CA bundle so chat_postMessage verifies SSL.
        self.app = App(client=WebClient(token=os.environ["SLACK_BOT_TOKEN"], ssl=_SSL_CONTEXT))

        def _handle(ack, body, action, respond):
            ack()
            val = json.loads(action["value"])
            rid, decision = val["rid"], val["decision"]
            user = body.get("user", {}).get("username") or body.get("user", {}).get("id", "analyst")
            with self._lock:
                slot = self._pending.get(rid)
            if slot:
                slot["decision"], slot["user"] = decision, user
                slot["event"].set()
            verb = "✅ APPROVED" if decision == "approve" else "❌ REJECTED"
            try:
                respond(text=f"{verb} by @{user}", replace_original=True)
            except Exception:
                pass

        self.app.action("approve_action")(_handle)
        self.app.action("reject_action")(_handle)
        self.handler = SocketModeHandler(self.app, os.environ["SLACK_APP_TOKEN"])
        self.handler.connect()   # non-blocking; socket runs in a background thread

    def request(self, *, action: str, target_desc: str, rationale: str,
                case_id: str | None = None, techniques: list | None = None,
                timeout: int = 300) -> dict:
        rid = uuid.uuid4().hex[:8]
        ev = threading.Event()
        with self._lock:
            self._pending[rid] = {"event": ev, "decision": None, "user": None}

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f":rotating_light: *Approve action?*  `{action}`\n"
                     f"• *Target:* {target_desc}\n• *Why:* {rationale}"}},
        ]
        if techniques:
            try:
                from common import technique_label
                labels = " · ".join(technique_label(t) for t in techniques)
            except Exception:
                labels = " · ".join(techniques)
            blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f":dart: {labels}"}]})
        blocks.append(
            {"type": "actions", "elements": [
                {"type": "button", "style": "primary", "action_id": "approve_action",
                 "text": {"type": "plain_text", "text": "✅ Approve"},
                 "value": json.dumps({"rid": rid, "decision": "approve"})},
                {"type": "button", "style": "danger", "action_id": "reject_action",
                 "text": {"type": "plain_text", "text": "❌ Reject"},
                 "value": json.dumps({"rid": rid, "decision": "reject"})},
            ]},
        )
        if case_id:
            ui = os.environ.get("UI_URL", "http://localhost:5001")
            blocks.append({"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"<{ui}/#case-{case_id}|View this case in the dashboard>"}]})
        self.app.client.chat_postMessage(
            channel=_channel(), text=f"Approve action {action} on {target_desc}?", blocks=blocks)

        got = ev.wait(timeout)
        with self._lock:
            slot = self._pending.pop(rid, {})
        if not got:
            return {"approved": False, "approver": "timeout"}
        return {"approved": slot.get("decision") == "approve", "approver": slot.get("user") or "analyst"}


_approver: _SlackApprover | None = None


def _get_approver() -> _SlackApprover:
    global _approver
    if _approver is None:
        _approver = _SlackApprover()
    return _approver


# --------------------------------------------------------------------------- #
# Public approval API
# --------------------------------------------------------------------------- #

def _terminal_approval(action: str, target_desc: str, rationale: str) -> dict:
    print("\n" + "-" * 60)
    print(f":rotating_light: Approve action?  `{action}`\n• Target: {target_desc}\n• Why: {rationale}")
    try:
        ans = input(f"Approve `{action}` on {target_desc}? [y/N] ").strip().lower()
    except EOFError:
        ans = "n"
    return {"approved": ans in ("y", "yes"), "approver": "analyst"}


def request_action_approval(*, action: str, target_desc: str, rationale: str,
                            case_id: str | None = None, techniques: list | None = None,
                            mode: str = "prompt") -> dict:
    """Approve ONE action individually (so an analyst can kill but not delete)."""
    if mode == "auto":
        return {"approved": True, "approver": "auto"}
    if mode == "slack":
        try:
            return _get_approver().request(action=action, target_desc=target_desc,
                                           rationale=rationale, case_id=case_id,
                                           techniques=techniques)
        except Exception as exc:
            print(f"[slack approval unavailable: {exc} — falling back to terminal]")
    return _terminal_approval(action, target_desc, rationale)


def request_approval(*, summary: str, actions: list[str], mode: str = "prompt") -> dict:
    """Legacy bundled approval (kept for compatibility)."""
    if mode == "auto":
        return {"approved": True, "approver": "auto", "actions": actions}
    if mode == "slack":
        post_message(f":rotating_light: {summary}\nProposed: {', '.join(actions)}")
    print("\n" + "=" * 60 + f"\n{summary}\nProposed: {', '.join(actions)}\n" + "=" * 60)
    try:
        ans = input("Approve these actions? [y/N] ").strip().lower()
    except EOFError:
        ans = "n"
    approved = ans in ("y", "yes")
    return {"approved": approved, "approver": "analyst", "actions": actions if approved else []}
