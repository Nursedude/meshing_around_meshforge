"""
Web client module for Meshing-Around Clients.
Provides a FastAPI-based web interface and REST API.
"""

from .app import create_app, WebApplication

__all__ = ['create_app', 'WebApplication']
