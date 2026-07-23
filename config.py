"""
config.py — Konfigurasi runtime dari environment variable.

CORS_ORIGINS : daftar origin frontend yang diizinkan, dipisah koma.
               Default cocok untuk dev Vite (5173).
"""

import os

_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]
