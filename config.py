"""
config.py — Konfigurasi runtime dari environment variable.

CORS_ORIGINS       : daftar origin frontend yang diizinkan (persis), dipisah koma.
                     Default cocok untuk dev Vite (5173).
CORS_ORIGIN_REGEX  : (opsional) regex origin yang diizinkan — berguna untuk domain
                     preview Vercel yang berubah-ubah, mis:
                       https://.*\\.vercel\\.app

SUPABASE_URL              : URL project Supabase, mis. https://xxxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY : kunci service_role / secret key Supabase. Hanya untuk
                            backend (bypass RLS), JANGAN dipakai di frontend.
IOT_DEVICE_KEY            : kunci bersama gelang IoT; dikirim firmware lewat header
                            X-Device-Key ke POST /iot/vitals. Kosong → semua
                            request IoT ditolak (401).
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

# ── Supabase (dipakai fitur IoT: tabel iot_vitals) ──
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip()
SUPABASE_SERVICE_ROLE_KEY = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

# ── Autentikasi perangkat IoT ──
IOT_DEVICE_KEY = (os.getenv("IOT_DEVICE_KEY") or "").strip()
