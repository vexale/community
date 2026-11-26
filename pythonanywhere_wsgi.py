import sys
from pathlib import Path

from dotenv import load_dotenv

project_path = Path("/home/vexale/community")
if str(project_path) not in sys.path:
    sys.path.insert(0, str(project_path))

# Local development can use this project's .env; PythonAnywhere may instead
# provide environment variables through its WSGI configuration.
load_dotenv(project_path / ".env", override=False)

from webhook_app import application
