"""
Meshtastic Mesh Cryptography and Protobuf Decoding

This module provides:
- Channel encryption/decryption using AES-CTR (Meshtastic default)
- Protobuf message decoding using meshtastic library
- Key derivation from channel PSKs
- Support for default and custom encryption keys
"""

import base64
import binascii
import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Try to import cryptography library
# Use BaseException to catch pyo3_runtime.PanicException from broken Rust backends
CRYPTO_AVAILABLE = False
Cipher = None
algorithms = None
modes = None
default_backend = None

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    CRYPTO_AVAILABLE = True
except BaseException as e:
    # Must use BaseException (not Exception) because pyo3_runtime.PanicException
    # from broken Rust cryptography backends inherits from BaseException directly.
    # Re-raise KeyboardInterrupt/SystemExit so they aren't silently swallowed.
    if isinstance(e, (KeyboardInterrupt, SystemExit)):
        raise

# Try to import meshtastic protobuf definitions
try:
    from meshtastic.protobuf import mesh_pb2, telemetry_pb2

    PROTOBUF_AVAILABLE = True
except ImportError:
    try:
        # Alternative import path for older versions
        from meshtastic import mesh_pb2, telemetry_pb2

        PROTOBUF_AVAILABLE = True
    except ImportError:
        PROTOBUF_AVAILABLE = False


# Meshtastic default channel key (AQ== in base64 = 0x01)
DEFAULT_CHANNEL_KEY = bytes([0x01])

# Well-known channel presets and their keys
CHANNEL_PRESETS = {
    "LongFast": base64.b64decode("AQ=="),  # Default key
    "LongSlow": base64.b64decode("AQ=="),
    "MediumFast": base64.b64decode("AQ=="),
    "MediumSlow": base64.b64decode("AQ=="),
    "ShortFast": base64.b64decode("AQ=="),
    "ShortSlow": base64.b64decode("AQ=="),
}


@dataclass
class DecryptedPacket:
    """Result of packet decryption."""

    success: bool
    portnum: int = 0
    portnum_name: str = ""
    payload: bytes = b""
    decoded: Optional[Dict[str, Any]] = None
    error: str = ""

    # Packet metadata
    packet_id: int = 0
    sender: int = 0
    destination: int = 0
    channel: int = 0
    hop_limit: int = 0
    want_ack: bool = False


class MeshCrypto:
    """
    Handles Meshtastic mesh network cryptography.

    Meshtastic uses AES-256-CTR for channel encryption with a nonce
    derived from packet ID and sender node number.
    """

    def __init__(self, encryption_key: str = ""):
        """
        Initialize crypto handler.

        Args:
            encryption_key: Base64-encoded encryption key, or empty for default
        """
        self._key: bytes = DEFAULT_CHANNEL_KEY
        self._derived_key: Optional[bytes] = None

        if encryption_key:
            self.set_key(encryption_key)

    @staticmethod
    def is_available() -> bool:
        """Check if cryptography library is available."""
        return CRYPTO_AVAILABLE

    def set_key(self, key: str) -> bool:
        """
        Set encryption key from base64 string.

        Args:
            key: Base64-encoded key (1-32 bytes)

        Returns:
            True if key was set successfully
        """
        try:
            if key.lower() == "none" or key == "":
                # No encryption
                self._key = b""
                self._derived_key = None
                return True

            raw_key = base64.b64decode(key)
            if len(raw_key) == 0:
                return False

            self._key = raw_key
            self._derived_key = self._derive_key(raw_key)
            return True

        except (binascii.Error, ValueError, TypeError):
            # binascii.Error: Invalid base64 padding/characters
            # ValueError: Invalid base64 string
            # TypeError: Non-string/bytes input
            return False

    def _derive_key(self, raw_key: bytes) -> bytes:
        """
        Derive AES-256 key from raw PSK.

        Meshtastic uses SHA-256 to expand short keys to 32 bytes.
        """
        if len(raw_key) == 32:
            return raw_key
        elif len(raw_key) == 16:
            # 128-bit key, expand with SHA-256
            return hashlib.sha256(raw_key).digest()
        elif len(raw_key) == 1:
            # Single-byte key (like default 0x01)
            # Expand using the "Meshtastic" salt
            expanded = b"Meshtastic" + raw_key
            return hashlib.sha256(expanded).digest()
        else:
            # Use SHA-256 for other key sizes
            return hashlib.sha256(raw_key).digest()

    def _create_nonce(self, packet_id: int, sender: int) -> bytes:
        """
        Create nonce for AES-CTR decryption.

        Meshtastic nonce format (16 bytes):
        - Bytes 0-7: Packet ID (little-endian uint64)
        - Bytes 8-11: Sender node number (little-endian uint32)
        - Bytes 12-15: Zero padding
        """
        nonce = struct.pack("<QI", packet_id, sender)
        nonce += b"\x00" * 4  # Pad to 16 bytes
        return nonce

    def decrypt(self, encrypted_data: bytes, packet_id: int, sender: int) -> bytes:
        """
        Decrypt AES-CTR encrypted data.

        Args:
            encrypted_data: The encrypted payload bytes
            packet_id: Packet ID for nonce generation
            sender: Sender node number for nonce generation

        Returns:
            Decrypted bytes, or empty on failure
        """
        if not CRYPTO_AVAILABLE:
            return b""

        if not self._derived_key:
            # No key set or no encryption
            return encrypted_data

        try:
            nonce = self._create_nonce(packet_id, sender)
            cipher = Cipher(algorithms.AES(self._derived_key), modes.CTR(nonce), backend=default_backend())
            decryptor = cipher.decryptor()
            return decryptor.update(encrypted_data) + decryptor.finalize()

        except (ValueError, TypeError, struct.error):
            # ValueError: Invalid key/nonce size or cipher error
            # TypeError: Invalid input types
            # struct.error: Nonce packing error
            return b""

    def encrypt(self, plaintext: bytes, packet_id: int, sender: int) -> bytes:
        """
        Encrypt data with AES-CTR.

        Args:
            plaintext: The plaintext bytes to encrypt
            packet_id: Packet ID for nonce generation
            sender: Sender node number for nonce generation

        Returns:
            Encrypted bytes
        """
        if not CRYPTO_AVAILABLE:
            return b""

        if not self._derived_key:
            return plaintext

        try:
            nonce = self._create_nonce(packet_id, sender)
            cipher = Cipher(algorithms.AES(self._derived_key), modes.CTR(nonce), backend=default_backend())
            encryptor = cipher.encryptor()
            return encryptor.update(plaintext) + encryptor.finalize()

        except (ValueError, TypeError, struct.error):
            # ValueError: Invalid key/nonce size or cipher error
            # TypeError: Invalid input types
            # struct.error: Nonce packing error
            return b""


class ProtobufDecoder:
    """
    Decodes Meshtastic protobuf messages.

    Handles various portnum types:
    - TEXT_MESSAGE_APP (1): Plain text messages
    - POSITION_APP (3): GPS position updates
    - NODEINFO_APP (4): Node information
    - TELEMETRY_APP (67): Device/environment telemetry
    - TRACEROUTE_APP (70): Route tracing
    - NEIGHBORINFO_APP (71): Neighbor information
    """

    # Portnum to name mapping
    PORTNUMS = {
        0: "UNKNOWN",
        1: "TEXT_MESSAGE_APP",
        2: "REMOTE_HARDWARE_APP",
        3: "POSITION_APP",
        4: "NODEINFO_APP",
        5: "ROUTING_APP",
        6: "ADMIN_APP",
        7: "TEXT_MESSAGE_COMPRESSED_APP",
        8: "WAYPOINT_APP",
        32: "REPLY_APP",
        64: "IP_TUNNEL_APP",
        65: "PAXCOUNTER_APP",
        66: "SERIAL_APP",
        67: "TELEMETRY_APP",
        68: "ZPS_APP",
        69: "SIMULATOR_APP",
        70: "TRACEROUTE_APP",
        71: "NEIGHBORINFO_APP",
        72: "ATAK_PLUGIN",
        73: "MAP_REPORT_APP",
        256: "PRIVATE_APP",
        257: "ATAK_FORWARDER",
    }

    @staticmethod
    def is_available() -> bool:
        """Check if protobuf library is available."""
        return PROTOBUF_AVAILABLE

    def decode_mesh_packet(self, data: bytes) -> Optional[Dict[str, Any]]:
        """
        Decode a MeshPacket from raw bytes.

        Args:
            data: Raw protobuf bytes

        Returns:
            Dictionary with packet fields, or None on failure
        """
        if not PROTOBUF_AVAILABLE:
            return None

        try:
            packet = mesh_pb2.MeshPacket()
            packet.ParseFromString(data)

            result = {
                "from": packet.source if hasattr(packet, "source") else getattr(packet, "from", 0),
                "to": packet.dest if hasattr(packet, "dest") else getattr(packet, "to", 0),
                "id": packet.id,
                "channel": packet.channel,
                "hop_limit": packet.hop_limit,
                "want_ack": packet.want_ack,
                "rx_time": packet.rx_time if packet.rx_time else None,
                "rx_snr": packet.rx_snr if hasattr(packet, "rx_snr") else 0,
                "rx_rssi": packet.rx_rssi if hasattr(packet, "rx_rssi") else 0,
            }

            # Check for encrypted vs decoded payload
            if packet.HasField("encrypted"):
                result["encrypted"] = packet.encrypted
                result["is_encrypted"] = True
            elif packet.HasField("decoded"):
                decoded = self._decode_data_payload(packet.decoded)
                result.update(decoded)
                result["is_encrypted"] = False

            return result

        except (ValueError, TypeError, KeyError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # KeyError: Missing expected fields
            # AttributeError: Protobuf structure mismatch
            return {"error": str(e)}

    def _decode_data_payload(self, data) -> Dict[str, Any]:
        """Decode the Data message payload based on portnum."""
        result = {
            "portnum": data.portnum,
            "portnum_name": self.PORTNUMS.get(data.portnum, f"UNKNOWN_{data.portnum}"),
            "payload_raw": data.payload,
        }

        try:
            if data.portnum == 1:  # TEXT_MESSAGE_APP
                result["text"] = data.payload.decode("utf-8")
                result["type"] = "text"

            elif data.portnum == 3:  # POSITION_APP
                result.update(self._decode_position(data.payload))
                result["type"] = "position"

            elif data.portnum == 4:  # NODEINFO_APP
                result.update(self._decode_nodeinfo(data.payload))
                result["type"] = "nodeinfo"

            elif data.portnum == 67:  # TELEMETRY_APP
                result.update(self._decode_telemetry(data.payload))
                result["type"] = "telemetry"

            elif data.portnum == 70:  # TRACEROUTE_APP
                result.update(self._decode_traceroute(data.payload))
                result["type"] = "traceroute"

            elif data.portnum == 71:  # NEIGHBORINFO_APP
                result.update(self._decode_neighborinfo(data.payload))
                result["type"] = "neighborinfo"

            elif data.portnum == 5:  # ROUTING_APP
                result.update(self._decode_routing(data.payload))
                result["type"] = "routing"

        except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError) as e:
            # ValueError: Invalid payload data
            # TypeError: Unexpected data types
            # KeyError: Missing expected keys
            # AttributeError: Missing protobuf fields
            # UnicodeDecodeError: Invalid UTF-8 in text messages
            result["decode_error"] = str(e)

        return result

    def _decode_position(self, payload: bytes) -> Dict[str, Any]:
        """Decode position protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            pos = mesh_pb2.Position()
            pos.ParseFromString(payload)

            return {
                "position": {
                    "latitude": pos.latitude_i / 1e7 if pos.latitude_i else 0,
                    "longitude": pos.longitude_i / 1e7 if pos.longitude_i else 0,
                    "altitude": pos.altitude if hasattr(pos, "altitude") else 0,
                    "time": pos.time if pos.time else None,
                    "ground_speed": pos.ground_speed if hasattr(pos, "ground_speed") else 0,
                    "ground_track": pos.ground_track if hasattr(pos, "ground_track") else 0,
                    "sats_in_view": pos.sats_in_view if hasattr(pos, "sats_in_view") else 0,
                    "precision_bits": pos.precision_bits if hasattr(pos, "precision_bits") else 0,
                }
            }
        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"position_error": str(e)}

    def _decode_nodeinfo(self, payload: bytes) -> Dict[str, Any]:
        """Decode nodeinfo protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            user = mesh_pb2.User()
            user.ParseFromString(payload)

            return {
                "user": {
                    "id": user.id,
                    "long_name": user.long_name,
                    "short_name": user.short_name,
                    "hw_model": user.hw_model if hasattr(user, "hw_model") else 0,
                    "is_licensed": user.is_licensed if hasattr(user, "is_licensed") else False,
                    "role": user.role if hasattr(user, "role") else 0,
                }
            }
        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"nodeinfo_error": str(e)}

    def _decode_telemetry(self, payload: bytes) -> Dict[str, Any]:
        """Decode telemetry protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            telemetry = telemetry_pb2.Telemetry()
            telemetry.ParseFromString(payload)

            result = {"telemetry": {"time": telemetry.time if telemetry.time else None}}

            # Device metrics
            if telemetry.HasField("device_metrics"):
                dm = telemetry.device_metrics
                result["telemetry"]["device_metrics"] = {
                    "battery_level": dm.battery_level if hasattr(dm, "battery_level") else 0,
                    "voltage": dm.voltage if hasattr(dm, "voltage") else 0,
                    "channel_utilization": dm.channel_utilization if hasattr(dm, "channel_utilization") else 0,
                    "air_util_tx": dm.air_util_tx if hasattr(dm, "air_util_tx") else 0,
                    "uptime_seconds": dm.uptime_seconds if hasattr(dm, "uptime_seconds") else 0,
                }

            # Environment metrics
            if telemetry.HasField("environment_metrics"):
                em = telemetry.environment_metrics
                result["telemetry"]["environment_metrics"] = {
                    "temperature": em.temperature if hasattr(em, "temperature") else 0,
                    "relative_humidity": em.relative_humidity if hasattr(em, "relative_humidity") else 0,
                    "barometric_pressure": em.barometric_pressure if hasattr(em, "barometric_pressure") else 0,
                    "gas_resistance": em.gas_resistance if hasattr(em, "gas_resistance") else 0,
                }

            return result

        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"telemetry_error": str(e)}

    def _decode_traceroute(self, payload: bytes) -> Dict[str, Any]:
        """Decode traceroute protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            route = mesh_pb2.RouteDiscovery()
            route.ParseFromString(payload)

            return {
                "traceroute": {
                    "route": list(route.route) if hasattr(route, "route") else [],
                    "snr_towards": list(route.snr_towards) if hasattr(route, "snr_towards") else [],
                    "route_back": list(route.route_back) if hasattr(route, "route_back") else [],
                    "snr_back": list(route.snr_back) if hasattr(route, "snr_back") else [],
                }
            }
        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"traceroute_error": str(e)}

    def _decode_neighborinfo(self, payload: bytes) -> Dict[str, Any]:
        """Decode neighbor info protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            neighbor = mesh_pb2.NeighborInfo()
            neighbor.ParseFromString(payload)

            neighbors = []
            if hasattr(neighbor, "neighbors"):
                for n in neighbor.neighbors:
                    neighbors.append(
                        {
                            "node_id": n.node_id if hasattr(n, "node_id") else 0,
                            "snr": n.snr if hasattr(n, "snr") else 0,
                        }
                    )

            return {
                "neighborinfo": {
                    "node_id": neighbor.node_id if hasattr(neighbor, "node_id") else 0,
                    "last_sent_by_id": neighbor.last_sent_by_id if hasattr(neighbor, "last_sent_by_id") else 0,
                    "node_broadcast_interval_secs": (
                        neighbor.node_broadcast_interval_secs
                        if hasattr(neighbor, "node_broadcast_interval_secs")
                        else 0
                    ),
                    "neighbors": neighbors,
                }
            }
        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"neighborinfo_error": str(e)}

    def _decode_routing(self, payload: bytes) -> Dict[str, Any]:
        """Decode routing protobuf."""
        if not PROTOBUF_AVAILABLE:
            return {}

        try:
            routing = mesh_pb2.Routing()
            routing.ParseFromString(payload)

            result = {"routing": {}}

            if routing.HasField("error_reason"):
                result["routing"]["error_reason"] = routing.error_reason

            if routing.HasField("route_request"):
                result["routing"]["route_request"] = {
                    "route": list(routing.route_request.route) if hasattr(routing.route_request, "route") else [],
                    "dest": routing.route_request.dest if hasattr(routing.route_request, "dest") else 0,
                }

            if routing.HasField("route_reply"):
                result["routing"]["route_reply"] = {
                    "route": list(routing.route_reply.route) if hasattr(routing.route_reply, "route") else [],
                }

            return result

        except (ValueError, TypeError, AttributeError) as e:
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return {"routing_error": str(e)}


class MeshPacketProcessor:
    """
    High-level processor combining crypto and protobuf decoding.

    Usage:
        processor = MeshPacketProcessor(encryption_key="AQ==")
        result = processor.process_mqtt_packet(raw_bytes, topic_info)
    """

    def __init__(self, encryption_key: str = ""):
        self.crypto = MeshCrypto(encryption_key)
        self.decoder = ProtobufDecoder()

    def set_channel_key(self, key: str) -> bool:
        """Set the channel encryption key."""
        return self.crypto.set_key(key)

    def process_encrypted_packet(self, raw_data: bytes, packet_id: int = 0, sender: int = 0) -> DecryptedPacket:
        """
        Process an encrypted packet: decrypt and decode.

        Args:
            raw_data: Raw packet bytes (may include header)
            packet_id: Packet ID for decryption
            sender: Sender node number for decryption

        Returns:
            DecryptedPacket with results
        """
        result = DecryptedPacket(success=False)

        # Parse the ServiceEnvelope if present (MQTT packets)
        parsed = self._parse_service_envelope(raw_data)
        if parsed:
            packet_id = parsed.get("packet_id", packet_id)
            sender = parsed.get("sender", sender)
            encrypted_data = parsed.get("encrypted", raw_data)
            result.packet_id = packet_id
            result.sender = sender
            result.destination = parsed.get("destination", 0)
            result.channel = parsed.get("channel", 0)
            result.hop_limit = parsed.get("hop_limit", 0)
            result.want_ack = parsed.get("want_ack", False)
        else:
            encrypted_data = raw_data

        # Decrypt
        if not self.crypto.is_available():
            result.error = "Crypto library not available"
            return result

        decrypted = self.crypto.decrypt(encrypted_data, packet_id, sender)
        if not decrypted:
            result.error = "Decryption failed"
            return result

        result.payload = decrypted

        # Decode protobuf
        if self.decoder.is_available():
            decoded = self.decoder.decode_mesh_packet(decrypted)
            if decoded and "error" not in decoded:
                result.decoded = decoded
                result.portnum = decoded.get("portnum", 0)
                result.portnum_name = decoded.get("portnum_name", "")
                result.success = True
            else:
                # Try decoding as Data directly
                decoded = self._try_decode_data(decrypted)
                if decoded:
                    result.decoded = decoded
                    result.portnum = decoded.get("portnum", 0)
                    result.portnum_name = decoded.get("portnum_name", "")
                    result.success = True
                else:
                    result.error = decoded.get("error", "Decode failed") if decoded else "Unknown decode error"
        else:
            result.error = "Protobuf library not available"

        return result

    def _parse_service_envelope(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse MQTT ServiceEnvelope if protobuf is available."""
        if not PROTOBUF_AVAILABLE:
            return None

        try:
            envelope = mesh_pb2.ServiceEnvelope()
            envelope.ParseFromString(data)

            if envelope.HasField("packet"):
                packet = envelope.packet
                result = {
                    "packet_id": packet.id,
                    "sender": getattr(packet, "from", 0) or getattr(packet, "source", 0),
                    "destination": getattr(packet, "to", 0) or getattr(packet, "dest", 0),
                    "channel": packet.channel,
                    "hop_limit": packet.hop_limit,
                    "want_ack": packet.want_ack,
                }

                if packet.HasField("encrypted"):
                    result["encrypted"] = packet.encrypted
                elif packet.HasField("decoded"):
                    result["decoded"] = packet.decoded

                return result

        except (ValueError, TypeError, AttributeError, KeyError):
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            # KeyError: Missing expected keys
            pass

        return None

    def _try_decode_data(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Try decoding bytes as a Data message directly."""
        if not PROTOBUF_AVAILABLE:
            return None

        try:
            data_msg = mesh_pb2.Data()
            data_msg.ParseFromString(data)
            return self.decoder._decode_data_payload(data_msg)
        except (ValueError, TypeError, AttributeError):
            # ValueError: Invalid protobuf data
            # TypeError: Unexpected field types
            # AttributeError: Missing protobuf fields
            return None


def get_channel_key_for_preset(preset_name: str) -> bytes:
    """Get the encryption key for a channel preset."""
    return CHANNEL_PRESETS.get(preset_name, DEFAULT_CHANNEL_KEY)


def node_id_to_num(node_id: str) -> int:
    """Convert node ID string (e.g., '!12345678') to integer."""
    if node_id.startswith("!"):
        try:
            return int(node_id[1:], 16)
        except ValueError:
            return 0
    try:
        return int(node_id)
    except ValueError:
        return 0


def node_num_to_id(node_num: int) -> str:
    """Convert node number to ID string."""
    return f"!{node_num:08x}"
