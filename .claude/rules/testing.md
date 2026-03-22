# Testing Rules — meshing_around_meshforge

## Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_models.py -v

# Run with coverage
python3 -m pytest tests/ --cov=meshing_around_clients --cov-report=term-missing

# Quick syntax check
python3 -m py_compile mesh_client.py
python3 -m py_compile meshing_around_clients/core/*.py
```

## Test Structure

```
tests/                          # 743 tests across 17 files
├── conftest.py                 # Shared fixtures
├── test_models.py              # Data models (Node, Message, Alert)
├── test_config.py              # INI config loading
├── test_mqtt_client.py         # MQTT connection + packet decode
├── test_meshtastic_api.py      # Device API + MockAPI
├── test_mesh_crypto.py         # AES-256-CTR encryption
├── test_callbacks.py           # Callback mixin + cooldowns
├── test_tui.py                 # TUI rendering
├── test_whiptail.py            # Dialog helpers
└── ...
```

## Key Patterns

### Mock MQTT for testing
```python
@patch('paho.mqtt.client.Client')
def test_mqtt_connect(mock_client):
    # Test connection logic without network
```

### Test alert cooldowns
```python
def test_cooldown_suppresses_repeat():
    api._alert_cooldown_seconds = 0  # Disable for test
    # Verify cooldown behavior
```

### Test Rich fallback
```python
@patch.dict('sys.modules', {'rich': None})
def test_tui_without_rich():
    # Verify plain-text fallback works
```

## CI Configuration

GitHub Actions runs on every push:
- Python 3.9-3.13 matrix
- pytest with 65% coverage threshold
- black (formatting), isort (imports), flake8 (style)
- py_compile syntax check
