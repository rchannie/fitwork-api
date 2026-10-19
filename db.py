"""
db.py — Satu-satunya client Supabase di backend.

Client dibuat sekali (lazy) lalu di-cache, sama seperti model ML di core.py,
supaya tidak membuat koneksi baru tiap request. Modul lain cukup memanggil
get_supabase(); jangan memanggil create_client() di tempat lain.

Memakai SUPABASE_SERVICE_ROLE_KEY sehingga backend bisa menulis ke tabel yang
dilindungi RLS (mis. iot_vitals, yang untuk user biasa hanya boleh SELECT).
"""

import config

_CLIENT = None


class SupabaseNotConfigured(RuntimeError):
    """SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY belum di-set di environment."""


def get_supabase():
    global _CLIENT
    if _CLIENT is None:
        if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_ROLE_KEY:
            raise SupabaseNotConfigured(
                "SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY belum di-set"
            )
        from supabase import create_client  # import di sini agar startup tetap ringan

        _CLIENT = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    return _CLIENT
