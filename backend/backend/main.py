"""SambaWave backend entrypoint."""

from backend.app_factory import create_application


app = create_application()
