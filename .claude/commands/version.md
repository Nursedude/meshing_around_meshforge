# Version Check

Check and display meshing_around_meshforge version information.

## Instructions

1. Check version in `meshing_around_clients/__init__.py`
2. Check `CHANGELOG.md` for recent changes
3. Show current version and status
4. Cross-check with ecosystem versions:
   - meshforge NOC: `python3 -c "import sys; sys.path.insert(0,'/opt/meshforge/src'); from __version__ import __version__; print('NOC:', __version__)"`
   - meshforge-maps: `python3 -c "import sys; sys.path.insert(0,'/opt/meshforge-maps'); from src import __version__; print('Maps:', __version__)"`
