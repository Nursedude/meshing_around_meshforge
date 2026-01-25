#!/usr/bin/env python3
"""
Meshing-Around TUI Client Launcher
Run the terminal user interface for mesh network monitoring.
"""

import sys
import os

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meshing_around_clients.tui.app import main

if __name__ == "__main__":
    main()
