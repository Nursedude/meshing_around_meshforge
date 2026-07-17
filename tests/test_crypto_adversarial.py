"""Adversarial crypto residual tests (second review pass, 2026-07-16).

D1 — multi-key decode must not accept wrong-key noise: the plausibility gate
     rejects out-of-vocabulary portnums, sub-decode errors, and content-bearing
     types whose field didn't populate.
D2 — a broken/absent `cryptography` backend leaves a witness log instead of a
     silent swallow.

Tests patch the SOURCE seam (mesh_crypto internals), never a consumer.
"""

import unittest
from unittest.mock import patch

from meshing_around_clients.core.mesh_crypto import (
    MeshPacketProcessor,
    _warn_backend_unavailable,
)


class TestD1PlausibilityGate(unittest.TestCase):
    def setUp(self):
        self.proc = MeshPacketProcessor()

    def test_out_of_vocab_portnum_rejected(self):
        # A wrong-key parse commonly lands on a garbage portnum.
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 9999}))
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 259491839}))

    def test_zero_and_missing_portnum_rejected(self):
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 0}))
        self.assertFalse(self.proc._decode_is_plausible({}))

    def test_sub_decode_error_rejected(self):
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 3, "decode_error": "bad"}))

    def test_text_without_text_field_rejected(self):
        # portnum 1 (TEXT) is in-vocab but a wrong-key parse won't have text.
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 1}))
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 1, "text": ""}))

    def test_position_without_position_field_rejected(self):
        self.assertFalse(self.proc._decode_is_plausible({"portnum": 3}))

    def test_valid_text_accepted(self):
        self.assertTrue(self.proc._decode_is_plausible({"portnum": 1, "text": "hello"}))

    def test_valid_position_accepted(self):
        self.assertTrue(
            self.proc._decode_is_plausible({"portnum": 3, "position": {"latitude": 19.4, "longitude": -155.2}})
        )

    def test_every_real_portnum_passes_the_gate(self):
        # 3rd pass: the gate was built on a stale display dict missing 8+ real
        # portnums, so DETECTION_SENSOR/ALERT/AUDIO packets decrypted with the
        # CORRECT key were false-rejected — the client went deaf on real
        # traffic, worse than the wrong-key false-accept the gate replaced.
        # Table-driven over the installed enum so a firmware portnum addition
        # fails a test here instead of going silently deaf in the field.
        try:
            from meshtastic.protobuf import portnums_pb2
        except ImportError:
            self.skipTest("meshtastic portnums_pb2 not installed")
        for value in portnums_pb2.PortNum.DESCRIPTOR.values:
            if value.number in (0, 1, 3):
                # 0 is never a real decode; 1/3 additionally require content
                # (covered by the accept tests above).
                continue
            self.assertTrue(
                self.proc._decode_is_plausible({"portnum": value.number}),
                f"real portnum {value.number} ({value.name}) false-rejected by the D1 gate",
            )

    def test_portnum_display_names_match_real_enum(self):
        # The static dict carried wrong names at 64/65/66 (claimed IP_TUNNEL/
        # PAXCOUNTER/SERIAL; real enum says SERIAL/STORE_FORWARD/RANGE_TEST).
        try:
            from meshtastic.protobuf import portnums_pb2
        except ImportError:
            self.skipTest("meshtastic portnums_pb2 not installed")
        from meshing_around_clients.core.mesh_crypto import ProtobufDecoder

        real = {v.number: v.name for v in portnums_pb2.PortNum.DESCRIPTOR.values}
        for number, name in ProtobufDecoder.PORTNUMS.items():
            if number in real:
                self.assertEqual(name, real[number], f"portnum {number} display name drifted")

    def test_process_encrypted_rejects_garbage_portnum_decode(self):
        # Even when decrypt yields bytes that parse to a Data with a garbage
        # portnum, success must be False (no injection into the node DB).
        with (
            patch.object(self.proc.crypto, "decrypt", return_value=b"\x01\x02\x03\x04"),
            patch.object(self.proc.decoder, "is_available", return_value=True),
            patch.object(self.proc, "_try_decode_data", return_value={"portnum": 9999}),
            patch.object(self.proc.decoder, "decode_mesh_packet", return_value=None),
        ):
            result = self.proc.process_encrypted_packet(b"x" * 16, packet_id=1, sender=1)
        self.assertFalse(result.success)


class TestD2BackendWitness(unittest.TestCase):
    def test_broken_backend_leaves_witness(self):
        # The import guard calls this instead of swallowing silently; assert it
        # emits an operator-facing WARNING naming the cause.
        with self.assertLogs("meshing_around_clients.core.mesh_crypto", level="WARNING") as cm:
            _warn_backend_unavailable(ImportError("simulated broken Rust backend"))
        self.assertTrue(any("backend unavailable" in line for line in cm.output), cm.output)
        self.assertTrue(
            any("simulated broken Rust backend" in line for line in cm.output),
            cm.output,
        )


if __name__ == "__main__":
    unittest.main()
