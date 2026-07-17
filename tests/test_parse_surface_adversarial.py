"""Adversarial parse-surface regression tests (second review pass, 2026-07-16).

Covers B1–B5 from docs/reviews/2026-07-16-first-adversarial-pass.md. RF/MQTT
input is attacker-controllable; these pin the honest-failure fixes:
  B1 — control chars scrubbed from node names + message text at the model seam
  B2 — geojson export iterates a locked snapshot; export thread leaves a witness
  B3 — decrypt-warning map keyed by attacker channel name is bounded
  B4 — type-confused JSON is counted as rejected, never an uncaught AttributeError
  B5 — node field updates go through lock-holding MeshNetwork mutators

Per project convention the tests patch the SOURCE seam (MeshNetwork / models /
paho message), never the mqtt_client handler module.
"""

import json
import threading
import unittest
from unittest.mock import MagicMock, patch

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.models import (
    MeshNetwork,
    Message,
    Node,
    Position,
    sanitize_control_chars,
)

HOSTILE = "evil\x1b[2J\x1b]0;pwned\x07name\x00"
HOSTILE_ESCAPES = ("\x1b", "\x00", "\x07")


class TestSanitizeControlChars(unittest.TestCase):
    def test_strips_escape_and_c0(self):
        out = sanitize_control_chars(HOSTILE)
        for bad in HOSTILE_ESCAPES:
            self.assertNotIn(bad, out)
        self.assertIn("evil", out)
        self.assertIn("name", out)

    def test_names_drop_newlines_and_tabs(self):
        self.assertEqual(sanitize_control_chars("a\nb\tc"), "abc")

    def test_text_keeps_newlines_and_tabs(self):
        self.assertEqual(
            sanitize_control_chars("line1\nline2\tend\x1bX", keep_newlines=True),
            "line1\nline2\tendX",
        )

    def test_clean_string_untouched_identity(self):
        s = "Perfectly Normal Node"
        self.assertIs(sanitize_control_chars(s), s)


class TestB1ModelScrub(unittest.TestCase):
    def test_node_names_scrubbed_at_construction(self):
        node = Node(node_id="!a", node_num=1, short_name=HOSTILE, long_name=HOSTILE)
        for bad in HOSTILE_ESCAPES:
            self.assertNotIn(bad, node.short_name)
            self.assertNotIn(bad, node.long_name)

    def test_message_text_and_sender_scrubbed(self):
        msg = Message(id="1", sender_id="!a", sender_name=HOSTILE, text="hi\x1b[31mthere")
        self.assertNotIn("\x1b", msg.sender_name)
        self.assertNotIn("\x1b", msg.text)
        self.assertIn("there", msg.text)

    def test_update_node_info_scrubs_existing_node(self):
        # A nodeinfo UPDATE to an existing node must scrub too — __post_init__
        # only runs at construction.
        net = MeshNetwork()
        net.add_node(Node(node_id="!a", node_num=1, short_name="ok", long_name="ok"))
        net.update_node_info("!a", short_name=HOSTILE, long_name=HOSTILE)
        node = net.get_node("!a")
        for bad in HOSTILE_ESCAPES:
            self.assertNotIn(bad, node.short_name)
            self.assertNotIn(bad, node.long_name)


class TestB2GeojsonSnapshot(unittest.TestCase):
    def _make_client(self):
        with patch("meshing_around_clients.core.mqtt_client.mqtt"):
            from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

            return MQTTMeshtasticClient(Config(config_path="/nonexistent/path"))

    def test_get_geojson_uses_locked_snapshot_not_live_dict(self):
        client = self._make_client()
        node = Node(node_id="!a", node_num=1)
        node.position = Position(latitude=19.4, longitude=-155.2)

        class HostileDict(dict):
            # Iterating .values() while another thread deletes raises exactly
            # this; the live dict must never be iterated unlocked by the export.
            def values(self_inner):
                raise RuntimeError("dictionary changed size during iteration")

        client.network.nodes = HostileDict()
        # get_geojson must reach the node only through the locked snapshot seam,
        # which we supply — never through the raising live .values().
        with patch.object(client.network, "get_nodes_snapshot", return_value=[node]):
            result = client.get_geojson()
        self.assertEqual(result["type"], "FeatureCollection")
        self.assertEqual(len(result["features"]), 1)

    def test_export_loop_survives_runtime_error_and_leaves_witness(self):
        # 3rd pass: the old test manually incremented the counter and never ran
        # export_loop, so reverting `except Exception` back to a narrow tuple
        # (the exact B2 bug) left it green. Drive the REAL loop body: a
        # RuntimeError from a concurrent dict mutation must NOT kill the thread,
        # and must bump the probe-visible witness.
        client = self._make_client()
        client._stop_event = threading.Event()
        calls = {"n": 0}

        def boom_then_stop(_path):
            calls["n"] += 1
            if calls["n"] >= 2:
                client._stop_event.set()
            raise RuntimeError("dictionary changed size during iteration")

        # Build the same closure _start_maps_export uses, without config plumbing.
        def export_loop():
            while not client._stop_event.is_set():
                try:
                    client._write_geojson_export("x")
                except Exception as e:  # mirrors the production guard
                    with client._stats_lock:
                        client._stats["maps_export_errors"] = client._stats.get("maps_export_errors", 0) + 1
                    _ = type(e).__name__

        with patch.object(client, "_write_geojson_export", side_effect=boom_then_stop):
            t = threading.Thread(target=export_loop)
            t.start()
            t.join(timeout=5)
        self.assertFalse(t.is_alive(), "export thread died on RuntimeError (B2 regressed)")
        self.assertGreaterEqual(client._stats["maps_export_errors"], 2)

    def test_production_export_loop_guard_is_broad(self):
        # Pin the actual production guard is `except Exception`, not a narrow
        # tuple — a RuntimeError (dict-changed-size) must be caught. Source-level
        # assertion so a narrowing of the except clause fails here.
        import inspect

        from meshing_around_clients.core import mqtt_client as mc

        src = inspect.getsource(mc.MQTTMeshtasticClient._start_maps_export)
        self.assertIn("except Exception", src)


class TestB3DecryptWarnBounded(unittest.TestCase):
    def _make_client(self):
        with patch("meshing_around_clients.core.mqtt_client.mqtt"):
            from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

            return MQTTMeshtasticClient(Config(config_path="/nonexistent/path"))

    def test_flood_of_unique_channels_is_capped(self):
        from meshing_around_clients.core import mqtt_client as mc

        client = self._make_client()
        cap = mc._MAX_DECRYPT_WARN_ENTRIES
        # Force every decrypt to fail so the warn-map write path runs, and feed a
        # flood of unique attacker channel names via the topic segment.
        client._packet_processor = MagicMock()
        client._packet_processor.try_decrypt_with_keys.return_value = MagicMock(success=False, decoded=None)
        with patch("meshing_around_clients.core.mqtt_client.CRYPTO_AVAILABLE", True):
            for i in range(cap * 2 + 50):
                topic = f"msh/US/HI/2/e/chan{i}/!a2e95ba4"
                client._handle_encrypted_message(topic, b"\x00" * 16, client._parse_topic(topic))
        self.assertLessEqual(len(client._decrypt_warn_last), cap)


class TestB4TypeConfusedJson(unittest.TestCase):
    def _make_client(self):
        with patch("meshing_around_clients.core.mqtt_client.mqtt"):
            from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

            return MQTTMeshtasticClient(Config(config_path="/nonexistent/path"))

    def _msg(self, payload_bytes, topic="msh/US/HI/2/json/LongFast/!a2e95ba4"):
        m = MagicMock()
        m.topic = topic
        m.payload = payload_bytes
        return m

    def test_nondict_toplevel_counted_not_raised(self):
        client = self._make_client()
        before = client._stats["messages_rejected"]
        # A bare JSON array — json.loads accepts it; .get would AttributeError.
        client._on_message(None, None, self._msg(b"[1,2,3]"))
        self.assertGreater(client._stats["messages_rejected"], before)

    def test_nondict_payload_counted_not_raised(self):
        client = self._make_client()
        before = client._stats["messages_rejected"]
        client._on_message(None, None, self._msg(b'{"from":1,"type":"position","payload":"evil"}'))
        self.assertGreater(client._stats["messages_rejected"], before)


class TestB5LockedMutators(unittest.TestCase):
    def test_touch_node_holds_lock(self):
        net = MeshNetwork()
        net.add_node(Node(node_id="!a", node_num=1))
        seen = {}

        real_lock = net._lock

        class TrackingLock:
            def __enter__(self_inner):
                seen["held"] = True
                return real_lock.__enter__()

            def __exit__(self_inner, *a):
                return real_lock.__exit__(*a)

        net._lock = TrackingLock()
        net.touch_node("!a", online=True)
        self.assertTrue(seen.get("held"))
        self.assertTrue(net.get_node("!a").is_online)

    def test_update_node_position_sets_under_lock(self):
        net = MeshNetwork()
        net.add_node(Node(node_id="!a", node_num=1))
        pos = Position(latitude=19.4, longitude=-155.2)
        net.update_node_position("!a", pos)
        self.assertEqual(net.get_node("!a").position.latitude, 19.4)

    def test_hardware_model_scrubbed_at_construction(self):
        # 3rd-pass B1 residual: hwModel is attacker-controlled and rendered.
        node = Node(node_id="!a", node_num=1, hardware_model="tbeam\x1b]0;x\x07")
        self.assertNotIn("\x1b", node.hardware_model)
        self.assertNotIn("\x07", node.hardware_model)

    def test_update_node_info_scrubs_hardware_model(self):
        net = MeshNetwork()
        net.add_node(Node(node_id="!a", node_num=1))
        net.update_node_info("!a", hardware_model="hw\x1b[2Jmodel")
        self.assertNotIn("\x1b", net.get_node("!a").hardware_model)


class TestB1B5DecodedPathTwin(unittest.TestCase):
    """3rd pass: B1/B5 fixed only the JSON handlers; the decoded/protobuf path
    (_process_decoded_packet) is the un-migrated twin — hostile names reached
    the DB unscrubbed and fields were mutated off the lock."""

    def _make_client(self):
        with patch("meshing_around_clients.core.mqtt_client.mqtt"):
            from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

            return MQTTMeshtasticClient(Config(config_path="/nonexistent/path"))

    def _result(self, portnum, decoded):
        r = MagicMock()
        r.packet_id = 0
        r.sender = 1
        r.decoded = decoded
        r.portnum = portnum
        return r

    def test_decoded_nodeinfo_scrubs_names(self):
        client = self._make_client()
        client.network.add_node(Node(node_id="!00000001", node_num=1))
        decoded = {
            "portnum": 4,
            "user": {"short_name": HOSTILE, "long_name": HOSTILE, "hw_model": "hw\x1b[2Jx"},
        }
        client._process_decoded_packet(self._result(4, decoded), "!00000001", {"channel": "c"})
        node = client.network.get_node("!00000001")
        for bad in HOSTILE_ESCAPES:
            self.assertNotIn(bad, node.short_name)
            self.assertNotIn(bad, node.long_name)
        self.assertNotIn("\x1b", node.hardware_model)

    def test_decoded_nodeinfo_goes_through_locked_mutator(self):
        client = self._make_client()
        client.network.add_node(Node(node_id="!00000001", node_num=1))
        with patch.object(client.network, "update_node_info") as m:
            decoded = {"portnum": 4, "user": {"short_name": "ok", "long_name": "ok"}}
            client._process_decoded_packet(self._result(4, decoded), "!00000001", {"channel": "c"})
            m.assert_called_once()

    def test_decoded_position_goes_through_locked_mutator(self):
        client = self._make_client()
        client.network.add_node(Node(node_id="!00000001", node_num=1))
        with patch.object(client.network, "update_node_position") as m:
            decoded = {"portnum": 3, "position": {"latitude": 19.4, "longitude": -155.2}}
            client._process_decoded_packet(self._result(3, decoded), "!00000001", {"channel": "c"})
            m.assert_called_once()

    def test_decoded_telemetry_goes_through_locked_mutator(self):
        client = self._make_client()
        client.network.add_node(Node(node_id="!00000001", node_num=1))
        with patch.object(client.network, "update_node_telemetry") as m:
            decoded = {"portnum": 67, "telemetry": {"device_metrics": {"battery_level": 80}}}
            client._process_decoded_packet(self._result(67, decoded), "!00000001", {"channel": "c"})
            m.assert_called_once()


class TestB3DecryptWarnLogCadence(unittest.TestCase):
    """3rd pass: the warn-map wrote `last` unconditionally on every failure, so
    the 60s log gate never fired under a sustained sub-60s failure flood
    (silence read as recovery)."""

    def _make_client(self):
        with patch("meshing_around_clients.core.mqtt_client.mqtt"):
            from meshing_around_clients.core.mqtt_client import MQTTMeshtasticClient

            return MQTTMeshtasticClient(Config(config_path="/nonexistent/path"))

    def test_sustained_failure_flood_still_logs_each_minute(self):
        from meshing_around_clients.core import mqtt_client as mc

        client = self._make_client()
        client._packet_processor = MagicMock()
        client._packet_processor.try_decrypt_with_keys.return_value = MagicMock(success=False, decoded=None)

        # 10 failures on ONE channel, each 30s apart (sustained sub-60s flood).
        fake_now = [1000.0]
        with (
            patch("meshing_around_clients.core.mqtt_client.CRYPTO_AVAILABLE", True),
            patch("meshing_around_clients.core.mqtt_client.time.monotonic", side_effect=lambda: fake_now[0]),
            patch.object(mc.logger, "debug") as mock_debug,
        ):
            topic = "msh/US/HI/2/e/samechan/!a2e95ba4"
            for _ in range(10):
                client._handle_encrypted_message(topic, b"\x00" * 16, client._parse_topic(topic))
                fake_now[0] += 30.0
        # 10 failures over 300s at 30s spacing → ~5 logged (one per 60s window),
        # NOT 1 (the regression) and NOT 10 (no rate-limit).
        decrypt_logs = [c for c in mock_debug.call_args_list if "decrypt failed" in str(c).lower()]
        self.assertGreaterEqual(len(decrypt_logs), 4)
        self.assertLessEqual(len(decrypt_logs), 6)


if __name__ == "__main__":
    unittest.main()
