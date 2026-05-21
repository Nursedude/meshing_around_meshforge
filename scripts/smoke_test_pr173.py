#!/usr/bin/env python3
"""Smoke test for PR #173 -- exercises the two HIGH fixes against the
installed code on the target host (intended for wh6gxzTRDEV / BA5E).

Scenarios:
  1. MQTT emergency-keyword cooldown -- three rapid "MAYDAY" messages
     from the same sender_id must produce exactly one Alert.
  2. MessagesScreen renders user-controlled text containing Rich
     markup without parsing it (literal brackets preserved).
  3. AlertsScreen renders alert.title / alert.message containing
     markup literally.
  4. Malformed markup ("[/]" with no opener) does not raise.

Run on the deployment host:
    python3 scripts/smoke_test_pr173.py

Exit codes: 0 all pass, 1 one or more failed, 2 import/setup error.
"""

from __future__ import annotations

import json
import sys
import traceback
from io import StringIO
from pathlib import Path

# Allow running from the repo root or scripts/ dir
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _section(name: str) -> None:
    print(f"\n--- {name} ---")


def _pass(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str, exc: BaseException | None = None) -> None:
    print(f"  FAIL  {msg}")
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__)


def scenario_1_mqtt_cooldown() -> bool:
    """Three MAYDAYs from same sender -> 1 alert."""
    _section("1. MQTT emergency-keyword cooldown")
    try:
        from meshing_around_clients.core.config import Config
        from meshing_around_clients.core.models import AlertType
        from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient
    except ImportError as e:
        _fail("import failed (paho-mqtt missing?)", e)
        return False

    cfg = Config(config_path="/nonexistent/path")
    cfg.storage.enabled = False
    cfg.alerts.enabled = True
    cfg.alerts.emergency_keywords = ["mayday", "sos"]
    cfg.chunk_reassembly_timeout = 0

    client = MQTTMeshtasticClient(cfg)
    client._alert_cooldown_seconds = 60

    # Each packet needs a unique id AND unique content - otherwise
    # _handle_json_message dedupes via is_duplicate_message() (SHA of
    # sender+payload) before the emergency check runs, masking the
    # cooldown behaviour we want to test.  Discovered on wh6gxzTRDEV.
    for i in range(3):
        payload = {
            "from": 0xAABBCCDD,
            "to": "^all",
            "channel": 0,
            "type": "text",
            "id": 1000 + i,
            "payload": {"text": f"MAYDAY MAYDAY #{i}"},
        }
        client._handle_json_message("msh/US/LongFast/json", json.dumps(payload).encode())

    if len(client.network.messages) != 3:
        _fail(
            f"messages were deduped upstream of cooldown: got {len(client.network.messages)}/3 "
            "- test cannot prove the fix"
        )
        return False

    alerts = [a for a in client.network.alerts if a.alert_type == AlertType.EMERGENCY]
    if len(alerts) == 1:
        _pass(f"3 distinct MAYDAYs -> {len(alerts)} alert under 60s cooldown")
        return True
    _fail(f"expected 1 emergency alert under cooldown, got {len(alerts)}")
    return False


def _render(panel) -> str:
    from rich.console import Console

    buf = StringIO()
    Console(file=buf, force_terminal=False, width=200).print(panel)
    return buf.getvalue()


def scenario_2_messages_markup() -> bool:
    """MessagesScreen escapes markup in text + sender_name."""
    _section("2. MessagesScreen markup escape")
    try:
        from meshing_around_clients.core.config import Config
        from meshing_around_clients.core.models import Message, MessageType
        from meshing_around_clients.tui.app import MeshingAroundTUI, MessagesScreen
    except ImportError as e:
        _fail("import failed (rich missing?)", e)
        return False

    tui = MeshingAroundTUI(config=Config(), demo_mode=True)
    tui.api.connect()
    try:
        screen = MessagesScreen(tui)

        tui.api.network.add_message(
            Message(
                id="markup-text",
                sender_id="!aabb1234",
                sender_name="[blink]badname[/blink]",
                text="[bold red]EVIL[/bold red]",
                recipient_id=None,
                message_type=MessageType.TEXT,
            )
        )

        rendered = _render(screen.render())
        ok = True
        if "[bold red]" in rendered:
            _pass("text markup preserved literally")
        else:
            _fail("text markup was parsed (no literal brackets in output)")
            ok = False
        if "[blink]" in rendered:
            _pass("sender_name markup preserved literally")
        else:
            _fail("sender_name markup was parsed")
            ok = False
        return ok
    finally:
        tui.api.disconnect()


def scenario_3_alerts_markup() -> bool:
    """AlertsScreen escapes markup in title + message."""
    _section("3. AlertsScreen markup escape")
    try:
        from meshing_around_clients.core.config import Config
        from meshing_around_clients.core.models import Alert, AlertType
        from meshing_around_clients.tui.app import AlertsScreen, MeshingAroundTUI
    except ImportError as e:
        _fail("import failed", e)
        return False

    tui = MeshingAroundTUI(config=Config(), demo_mode=True)
    tui.api.connect()
    try:
        screen = AlertsScreen(tui)

        tui.api.network.add_alert(
            Alert(
                id="markup-alert",
                alert_type=AlertType.EMERGENCY,
                title="[bold red]EVIL[/]",
                message="[link=http://x]Click[/link]",
                severity=4,
            )
        )

        rendered = _render(screen.render())
        ok = True
        if "[bold red]" in rendered:
            _pass("alert.title markup preserved literally")
        else:
            _fail("alert.title markup was parsed")
            ok = False
        if "[link=" in rendered:
            _pass("alert.message markup preserved literally")
        else:
            _fail("alert.message markup was parsed")
            ok = False
        return ok
    finally:
        tui.api.disconnect()


def scenario_4_malformed_markup() -> bool:
    """Malformed markup must not raise from either screen."""
    _section("4. Malformed markup does not crash render")
    try:
        from meshing_around_clients.core.config import Config
        from meshing_around_clients.core.models import Alert, AlertType, Message, MessageType
        from meshing_around_clients.tui.app import AlertsScreen, MeshingAroundTUI, MessagesScreen
    except ImportError as e:
        _fail("import failed", e)
        return False

    tui = MeshingAroundTUI(config=Config(), demo_mode=True)
    tui.api.connect()
    try:
        tui.api.network.add_message(
            Message(
                id="malformed-msg",
                sender_id="!aabbcdef",
                sender_name="x",
                text="oops [/] [unterminated",
                recipient_id=None,
                message_type=MessageType.TEXT,
            )
        )
        tui.api.network.add_alert(
            Alert(
                id="malformed-alert",
                alert_type=AlertType.EMERGENCY,
                title="[/]",
                message="[no-close",
                severity=4,
            )
        )

        try:
            _render(MessagesScreen(tui).render())
            _pass("MessagesScreen renders malformed markup without raising")
        except Exception as e:
            _fail("MessagesScreen raised on malformed markup", e)
            return False

        try:
            _render(AlertsScreen(tui).render())
            _pass("AlertsScreen renders malformed markup without raising")
        except Exception as e:
            _fail("AlertsScreen raised on malformed markup", e)
            return False

        return True
    finally:
        tui.api.disconnect()


def main() -> int:
    print(f"Smoke test for PR #173 -- repo: {REPO_ROOT}")
    try:
        import meshing_around_clients  # noqa: F401
    except ImportError as e:
        print(f"FATAL: cannot import meshing_around_clients from {REPO_ROOT}: {e}")
        return 2

    results = [
        scenario_1_mqtt_cooldown(),
        scenario_2_messages_markup(),
        scenario_3_alerts_markup(),
        scenario_4_malformed_markup(),
    ]

    print()
    passed = sum(1 for r in results if r)
    total = len(results)
    if passed == total:
        print(f"OK  {passed}/{total} scenarios passed")
        return 0
    print(f"FAIL  {passed}/{total} scenarios passed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
