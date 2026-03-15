"""Service package marker.

Avoid importing heavy ML services at package import time. Modules should be
imported directly where needed (for example: ``from app.services import
storage_service`` or ``from app.services.ai_service import summarize_transcript``).
"""
