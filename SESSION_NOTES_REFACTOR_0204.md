# Session Notes: MeshForge Refactoring

**Date:** 2026-02-04
**Focus:** Code refactoring, config unification, reliability improvements

## Session Goals

1. Config schema unification
2. Decompose configure_bot.py (partial - extracted modules)
3. Narrow broad exception handling
4. Design auto-update system
5. Upstream integration analysis

## Completed Work

### New Modules Created

#### 1. `config_schema.py` (500+ lines)
Unified configuration system with:
- Dataclass-based type safety
- Support for both upstream (SpudGunMan) and MeshForge config formats
- Auto-detection of config format
- Multi-interface support (interface1-9 from upstream)
- All alert types defined with validation
- Auto-update configuration section

**Key Classes:**
- `UnifiedConfig` - Main configuration container
- `ConfigLoader` - Format detection and loading
- `InterfaceConfig`, `MQTTConfig`, `GeneralConfig`
- Alert configs: `EmergencyAlertConfig`, `SentryConfig`, `AltitudeAlertConfig`, etc.
- `AutoUpdateConfig` - Opt-in update scheduling

#### 2. `pi_utils.py` (350+ lines)
Raspberry Pi utilities:
- Pi detection and model identification
- Serial port discovery (USB, native UART)
- PEP 668 virtual environment handling
- User group management (dialout, gpio)
- raspi-config integration (non-interactive)
- Pi Zero 2W specific recommendations

**Key Functions:**
- `is_raspberry_pi()`, `get_pi_model()`, `get_pi_info()`
- `get_serial_ports()` - Returns SerialPortInfo objects
- `check_pep668_environment()` - Bookworm+ detection
- `create_venv()`, `get_pip_command()`, `get_pip_install_flags()`
- `configure_serial_via_raspi_config()`

#### 3. `system_maintenance.py` (450+ lines)
System maintenance and auto-update:
- Git-based updates for MeshForge and upstream
- apt update/upgrade wrapper
- Python dependency installation
- Systemd service management
- Scheduled update checks (weekly/monthly)

**Key Functions:**
- `update_meshforge()`, `update_upstream()`
- `check_for_updates()` - Compares with remote
- `install_python_dependencies()`
- `create_systemd_service()`, `manage_service()`
- `perform_scheduled_update_check()`

#### 4. `cli_utils.py` (400+ lines)
CLI/terminal utilities:
- ANSI color codes with auto-disable for non-TTY
- Formatted printing (headers, sections, success/error)
- User input with validation
- Progress bars and spinners
- Menu system for CLI apps

**Key Classes/Functions:**
- `Colors` - ANSI color codes
- `print_header()`, `print_section()`, `print_success()`, `print_error()`
- `get_input()`, `get_yes_no()`, `get_choice()`, `get_list_input()`
- `validate_mac_address()`, `validate_ip_address()`, `validate_email()`
- `ProgressBar`, `Spinner`, `Menu`

### Exception Handling Fixes

#### mqtt_client.py (7 fixes)
| Line | Before | After |
|------|--------|-------|
| 155 | `except Exception` | `except (TypeError, ValueError, AttributeError)` |
| 210 | `except Exception` | `except (OSError, ConnectionError, TimeoutError)` + `except ValueError` |
| 299 | `except Exception` | `except (json.JSONDecodeError, UnicodeDecodeError)` + `except (KeyError, ValueError, TypeError, struct.error)` |
| 412 | `except Exception` | `except (KeyError, TypeError, ValueError)` |
| 490 | `except Exception` | `except (KeyError, TypeError, ValueError)` |
| 608 | `except Exception` | `except (ValueError, struct.error, KeyError, TypeError)` |
| 888 | `except Exception` | `except (OSError, ConnectionError, ValueError, TypeError)` |

#### meshtastic_api.py (8 fixes)
| Line | Before | After |
|------|--------|-------|
| 87 | `except Exception` | `except (TypeError, ValueError, AttributeError)` |
| 147 | `except Exception` | `except (OSError, ConnectionError, TimeoutError)` + `except (ValueError, AttributeError)` |
| 163 | `except Exception` | `except (OSError, AttributeError, RuntimeError)` |
| 242 | `except Exception` | `except (KeyError, TypeError, ValueError)` |
| 272 | `except Exception` | `except (KeyError, TypeError, ValueError, AttributeError)` |
| 297 | `except Exception` | `except (KeyError, TypeError, ValueError, UnicodeDecodeError)` |
| 476 | `except Exception` | `except (OSError, AttributeError, ValueError)` |
| 488 | `except Exception` | `except (OSError, ValueError, AttributeError)` |

### Updated Files
- `core/__init__.py` - Exports new modules
- `RELIABILITY_ROADMAP.md` - Updated progress tracking

## Pending Work

### Still Needs Decomposition
- `configure_bot.py` remains monolithic (2266 lines)
- Alert configurators not yet extracted
- Main menu orchestration not refactored

### Exception Handling Remaining
- `mesh_crypto.py` - 13 instances
- `configure_bot.py` - 7 instances
- `message_handler.py` - 3 instances
- Test files - can remain broad for test isolation

### Integration Testing
- Test new modules on Pi Zero 2W
- Test auto-update workflow
- Test config loading from upstream format

## Architecture Notes

### Auto-Update Design
```
Auto-Update (Opt-In)
├── Check Schedule: weekly/monthly/daily
├── MeshForge Updates
│   └── git pull from Nursedude/meshing_around_meshforge
├── Upstream Updates
│   └── git pull from SpudGunMan/meshing-around
├── Notify Only Mode (default)
│   └── Shows update available, user applies manually
└── Auto-Apply Mode
    └── Applies updates automatically with backup
```

### Config Schema Design
```
UnifiedConfig
├── interfaces: List[InterfaceConfig]  # Supports 1-9
├── general: GeneralConfig
├── emergency: EmergencyAlertConfig
├── sentry: SentryConfig              # Maps upstream [sentry]
├── altitude: AltitudeAlertConfig
├── weather: WeatherAlertConfig
├── battery: BatteryAlertConfig
├── new_node: NewNodeAlertConfig
├── noisy_node: NoisyNodeAlertConfig
├── disconnect: DisconnectAlertConfig
├── global_alerts: GlobalAlertConfig
├── mqtt: MQTTConfig
├── smtp: SMTPConfig
├── sms: SMSConfig
├── tui: TUIConfig
├── web: WebConfig
└── auto_update: AutoUpdateConfig
```

## Future Sessions

### Priority 1: Configure_bot.py Decomposition
- Extract alert configuration wizard
- Extract Pi setup/detection routines (now in pi_utils.py - needs integration)
- Extract service management (now in system_maintenance.py - needs integration)
- Keep main menu orchestration thin

### Priority 2: Remaining Exception Handling
- `mesh_crypto.py` - crypto operations need specific exception types
- Consider adding custom exception classes

### Priority 3: Testing
- Unit tests for new modules
- Integration test for config migration
- Test auto-update on headless Pi

### Priority 4: Integration
- Wire up new modules to configure_bot.py
- Add auto-update menu option
- Add config format detection/migration wizard

## Commands Reference

```bash
# Test module syntax
python3 -m py_compile meshing_around_clients/core/config_schema.py

# Run unit tests (when fixed)
python3 -m pytest tests/ -v

# Check for broad exceptions
grep -rn "except Exception" meshing_around_clients/

# Check upstream changes
git fetch upstream && git log upstream/main --oneline -10
```

## Session Entropy Notes

Session remained coherent throughout. No context degradation observed.
All modules syntactically valid. Ready for next session to continue decomposition.
