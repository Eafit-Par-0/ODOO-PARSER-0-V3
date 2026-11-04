"""Plain pytest setup: load the pure services as top-level modules.

This folder has no ``__init__.py`` on purpose, so pytest never imports the
Odoo package (which needs Odoo installed).
"""
import os
import sys

SERVICES = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'services'))
if SERVICES not in sys.path:
    sys.path.insert(0, SERVICES)
