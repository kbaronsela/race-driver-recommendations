# PythonAnywhere WSGI entry point.
# In the Web app "Code" section, set: WSGI configuration file = .../wsgi.py
# and ensure the project path and virtualenv are set to this project.

import sys
from pathlib import Path

# Add project directory to path (in case it's not the working directory)
project_home = Path(__file__).resolve().parent
if str(project_home) not in sys.path:
    sys.path.insert(0, str(project_home))

from server import app as application
