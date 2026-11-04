"""`python -m kerstin` — start the server with host/port from settings (.env)."""

import uvicorn

from .config import settings

if __name__ == "__main__":
    uvicorn.run("kerstin.main:app", host=settings.host, port=settings.port, log_level=settings.log_level)
