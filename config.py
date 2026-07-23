"""
config.py — Konfigurasi runtime dari environment variable.

CORS_ORIGINS       : daftar origin frontend yang diizinkan (persis), dipisah koma.
                     Default cocok untuk dev Vite (5173).
CORS_ORIGIN_REGEX  : (opsional) regex origin yang diizinkan — berguna untuk domain
                     preview Vercel yang berubah-ubah, mis:
                       https://.*\\.vercel\\.app
"""

import os

_DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
    if o.strip()
]

# Kosong/None → tidak dipakai. Diteruskan ke CORSMiddleware(allow_origin_regex=...).
ALLOWED_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or None
