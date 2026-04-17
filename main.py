"""
Punto de entrada para Vercel: expone `app` (FastAPI).
En local seguí usando: uvicorn app.main:app
"""

from app.main import app

__all__ = ["app"]
