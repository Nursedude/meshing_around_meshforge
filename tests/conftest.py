"""
Shared test fixtures for meshing_around_meshforge test suite.
"""

import sys

import pytest

sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0])

from meshing_around_clients.core.config import Config
from meshing_around_clients.core.models import (
    Alert,
    AlertType,
    MeshNetwork,
    Message,
    MessageType,
    Node,
    NodeTelemetry,
    Position,
)


@pytest.fixture
def config():
    """Create a default Config for testing."""
    cfg = Config(config_path="/nonexistent/path")
    cfg.alerts.enabled = True
    cfg.alerts.emergency_keywords = ["help", "sos", "emergency"]
    return cfg


@pytest.fixture
def network():
    """Create an empty MeshNetwork for testing."""
    return MeshNetwork()


@pytest.fixture
def sample_node():
    """Create a sample Node for testing."""
    return Node(
        node_id="!aabbccdd",
        node_num=0xAABBCCDD,
        short_name="TST",
        long_name="Test Node",
    )


@pytest.fixture
def sample_message():
    """Create a sample Message for testing."""
    return Message(
        id="msg-test-001",
        sender_id="!aabbccdd",
        sender_name="Test Node",
        text="Hello mesh!",
        message_type=MessageType.TEXT,
    )
