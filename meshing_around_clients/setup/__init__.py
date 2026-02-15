"""
Setup-only modules for Meshing-Around Clients.
These are used by configure_bot.py and mesh_client.py --import-config,
NOT by the runtime TUI/Web applications.

Modules:
- cli_utils: Terminal colors, printing, user input helpers
- pi_utils: Raspberry Pi detection, serial ports, venv management
- system_maintenance: Updates, git operations, systemd services
- alert_configurators: Alert configuration wizards
- config_schema: Unified config schema for upstream format conversion
"""
