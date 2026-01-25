#!/usr/bin/env python3
"""
Meshing-Around Web Client Launcher
Run the web interface for mesh network monitoring.
"""

import sys
import os

# Add package to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from meshing_around_clients.web.app import main

if __name__ == "__main__":
    main()
