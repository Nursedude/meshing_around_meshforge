"""
Unit tests for meshing_around_clients.core.mesh_crypto

Tests cover the crypto primitives, key derivation, and utility functions.
Protobuf decode tests are skipped when meshtastic is not installed.
"""

import base64
import hashlib
import struct
import sys
import unittest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.mesh_crypto import (
    CHANNEL_PRESETS,
    CRYPTO_AVAILABLE,
    DEFAULT_CHANNEL_KEY,
    PROTOBUF_AVAILABLE,
    DecryptedPacket,
    MeshCrypto,
    MeshPacketProcessor,
    ProtobufDecoder,
    get_channel_key_for_preset,
    node_id_to_num,
    node_num_to_id,
)


class TestNodeIdConversions(unittest.TestCase):
    """Test node_id_to_num and node_num_to_id utility functions."""

    def test_node_num_to_id(self):
        self.assertEqual(node_num_to_id(0x12345678), "!12345678")

    def test_node_num_to_id_zero(self):
        self.assertEqual(node_num_to_id(0), "!00000000")

    def test_node_num_to_id_max(self):
        self.assertEqual(node_num_to_id(0xFFFFFFFF), "!ffffffff")

    def test_node_id_to_num_hex(self):
        self.assertEqual(node_id_to_num("!12345678"), 0x12345678)

    def test_node_id_to_num_no_prefix(self):
        self.assertEqual(node_id_to_num("305419896"), 305419896)

    def test_node_id_to_num_invalid_hex(self):
        self.assertEqual(node_id_to_num("!zzzzzzzz"), 0)

    def test_node_id_to_num_invalid_string(self):
        self.assertEqual(node_id_to_num("not_a_number"), 0)

    def test_roundtrip(self):
        for num in [0, 1, 0xDEADBEEF, 0xFFFFFFFF]:
            self.assertEqual(node_id_to_num(node_num_to_id(num)), num)


class TestChannelPresets(unittest.TestCase):
    """Test channel preset key lookups."""

    def test_all_presets_are_bytes(self):
        for name, key in CHANNEL_PRESETS.items():
            self.assertIsInstance(key, bytes, f"Preset {name} key is not bytes")

    def test_default_key_value(self):
        self.assertEqual(DEFAULT_CHANNEL_KEY, bytes([0x01]))

    def test_longfast_is_default(self):
        self.assertEqual(CHANNEL_PRESETS["LongFast"], DEFAULT_CHANNEL_KEY)

    def test_get_channel_key_known(self):
        key = get_channel_key_for_preset("LongFast")
        self.assertEqual(key, DEFAULT_CHANNEL_KEY)

    def test_get_channel_key_unknown_returns_default(self):
        key = get_channel_key_for_preset("NonexistentPreset")
        self.assertEqual(key, DEFAULT_CHANNEL_KEY)


class TestMeshCryptoInit(unittest.TestCase):
    """Test MeshCrypto initialization."""

    def test_default_init(self):
        crypto = MeshCrypto()
        self.assertEqual(crypto._key, DEFAULT_CHANNEL_KEY)
        self.assertIsNotNone(crypto._derived_key)

    def test_init_with_custom_key(self):
        # 32-byte key encoded as base64
        key_bytes = b"\x00" * 32
        key_b64 = base64.b64encode(key_bytes).decode()
        crypto = MeshCrypto(key_b64)
        self.assertEqual(crypto._key, key_bytes)

    def test_is_available(self):
        crypto = MeshCrypto()
        self.assertEqual(crypto.is_available(), CRYPTO_AVAILABLE)


class TestMeshCryptoSetKey(unittest.TestCase):
    """Test MeshCrypto.set_key()."""

    def test_set_valid_base64_key(self):
        crypto = MeshCrypto()
        key = base64.b64encode(b"\x42" * 16).decode()
        self.assertTrue(crypto.set_key(key))
        self.assertEqual(crypto._key, b"\x42" * 16)

    def test_set_none_clears_key(self):
        crypto = MeshCrypto()
        self.assertTrue(crypto.set_key("none"))
        self.assertEqual(crypto._key, b"")
        self.assertIsNone(crypto._derived_key)

    def test_set_empty_clears_key(self):
        crypto = MeshCrypto()
        self.assertTrue(crypto.set_key(""))
        self.assertEqual(crypto._key, b"")

    def test_set_invalid_base64_returns_false(self):
        crypto = MeshCrypto()
        # Use a string with characters that are truly invalid for base64
        self.assertFalse(crypto.set_key("\x00\x01\x02==="))


class TestMeshCryptoKeyDerivation(unittest.TestCase):
    """Test key derivation logic."""

    def test_32_byte_key_used_directly(self):
        crypto = MeshCrypto()
        key = b"\xab" * 32
        derived = crypto._derive_key(key)
        self.assertEqual(derived, key)

    def test_16_byte_key_expanded_with_sha256(self):
        crypto = MeshCrypto()
        key = b"\xcd" * 16
        derived = crypto._derive_key(key)
        expected = hashlib.sha256(key).digest()
        self.assertEqual(derived, expected)
        self.assertEqual(len(derived), 32)

    def test_1_byte_key_expanded_with_salt(self):
        crypto = MeshCrypto()
        key = bytes([0x01])
        derived = crypto._derive_key(key)
        expected = hashlib.sha256(b"Meshtastic" + key).digest()
        self.assertEqual(derived, expected)
        self.assertEqual(len(derived), 32)

    def test_other_length_key_uses_sha256(self):
        crypto = MeshCrypto()
        key = b"\xef" * 8  # 8 bytes — not 1, 16, or 32
        derived = crypto._derive_key(key)
        expected = hashlib.sha256(key).digest()
        self.assertEqual(derived, expected)


class TestMeshCryptoNonce(unittest.TestCase):
    """Test nonce creation."""

    def test_nonce_length(self):
        crypto = MeshCrypto()
        nonce = crypto._create_nonce(12345, 67890)
        self.assertEqual(len(nonce), 16)

    def test_nonce_structure(self):
        crypto = MeshCrypto()
        packet_id = 0x12345678
        sender = 0xDEADBEEF
        nonce = crypto._create_nonce(packet_id, sender)
        # First 8 bytes: packet_id as uint64 LE
        # Next 4 bytes: sender as uint32 LE
        # Last 4 bytes: zeros
        unpacked_pid, unpacked_sender = struct.unpack_from("<QI", nonce, 0)
        self.assertEqual(unpacked_pid, packet_id)
        self.assertEqual(unpacked_sender, sender)
        self.assertEqual(nonce[12:], b"\x00\x00\x00\x00")


@unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography library not installed")
class TestMeshCryptoEncryptDecrypt(unittest.TestCase):
    """Test encrypt/decrypt roundtrip (requires cryptography library)."""

    def test_encrypt_decrypt_roundtrip(self):
        crypto = MeshCrypto()
        plaintext = b"Hello Meshtastic!"
        packet_id = 42
        sender = 12345

        encrypted = crypto.encrypt(plaintext, packet_id, sender)
        self.assertNotEqual(encrypted, plaintext)

        decrypted = crypto.decrypt(encrypted, packet_id, sender)
        self.assertEqual(decrypted, plaintext)

    def test_decrypt_with_wrong_key_fails(self):
        crypto1 = MeshCrypto()
        key_b64 = base64.b64encode(b"\xff" * 32).decode()
        crypto2 = MeshCrypto(key_b64)

        plaintext = b"Secret message"
        encrypted = crypto1.encrypt(plaintext, 1, 1)
        decrypted = crypto2.decrypt(encrypted, 1, 1)
        # Won't match because different keys
        self.assertNotEqual(decrypted, plaintext)

    def test_decrypt_with_no_key_returns_data_as_is(self):
        crypto = MeshCrypto()
        crypto.set_key("none")
        data = b"unencrypted"
        result = crypto.decrypt(data, 1, 1)
        self.assertEqual(result, data)

    def test_encrypt_with_no_key_returns_data_as_is(self):
        crypto = MeshCrypto()
        crypto.set_key("none")
        data = b"plaintext"
        result = crypto.encrypt(data, 1, 1)
        self.assertEqual(result, data)


class TestDecryptedPacketDataclass(unittest.TestCase):
    """Test DecryptedPacket dataclass."""

    def test_default_values(self):
        pkt = DecryptedPacket(success=False)
        self.assertFalse(pkt.success)
        self.assertEqual(pkt.portnum, 0)
        self.assertEqual(pkt.payload, b"")
        self.assertIsNone(pkt.decoded)
        self.assertEqual(pkt.error, "")

    def test_with_values(self):
        pkt = DecryptedPacket(
            success=True,
            portnum=1,
            portnum_name="TEXT_MESSAGE_APP",
            payload=b"hello",
            sender=12345,
        )
        self.assertTrue(pkt.success)
        self.assertEqual(pkt.portnum_name, "TEXT_MESSAGE_APP")


class TestProtobufDecoder(unittest.TestCase):
    """Test ProtobufDecoder."""

    def test_is_available(self):
        decoder = ProtobufDecoder()
        self.assertEqual(decoder.is_available(), PROTOBUF_AVAILABLE)

    def test_portnums_mapping(self):
        decoder = ProtobufDecoder()
        self.assertEqual(decoder.PORTNUMS[1], "TEXT_MESSAGE_APP")
        self.assertEqual(decoder.PORTNUMS[3], "POSITION_APP")
        self.assertEqual(decoder.PORTNUMS[67], "TELEMETRY_APP")

    @unittest.skipUnless(PROTOBUF_AVAILABLE, "meshtastic protobuf not installed")
    def test_decode_invalid_data_returns_error(self):
        decoder = ProtobufDecoder()
        result = decoder.decode_mesh_packet(b"\x00\x00\x00")
        # Should return a dict (possibly with error), not crash
        self.assertIsInstance(result, dict)


class TestMeshPacketProcessor(unittest.TestCase):
    """Test MeshPacketProcessor."""

    def test_init(self):
        processor = MeshPacketProcessor()
        self.assertIsNotNone(processor.crypto)
        self.assertIsNotNone(processor.decoder)

    def test_set_channel_key(self):
        processor = MeshPacketProcessor()
        self.assertTrue(processor.set_channel_key("AQ=="))
        # Use a truly invalid base64 string (embedded null bytes)
        self.assertFalse(processor.set_channel_key("\x00\x01\x02==="))

    @unittest.skipUnless(CRYPTO_AVAILABLE, "cryptography library not installed")
    def test_process_encrypted_packet_with_bad_data(self):
        processor = MeshPacketProcessor()
        result = processor.process_encrypted_packet(b"\x00" * 10, packet_id=1, sender=1)
        self.assertIsInstance(result, DecryptedPacket)


if __name__ == "__main__":
    unittest.main()
