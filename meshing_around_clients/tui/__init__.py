"""
TUI (Terminal User Interface) module for Meshing-Around Clients.
Provides a rich terminal interface for monitoring and interacting with the mesh network.
"""

from .app import MeshingAroundTUI
from .whiptail_tui import WhiptailTUI

__all__ = ["MeshingAroundTUI", "WhiptailTUI"]
