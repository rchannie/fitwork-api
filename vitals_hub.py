"""
vitals_hub.py — Hub sederhana untuk mendorong data ke klien WebSocket /ws/vitals.

Sebelumnya /ws/vitals murni echo per-koneksi (tidak tahu koneksi milik siapa).
Hub ini menambah kemampuan push dari server ke koneksi milik user tertentu,
dipakai saat gelang IoT mengirim data lewat POST /iot/vitals.

- Klien yang ingin menerima data IoT membuka  /ws/vitals?user_id=<uuid>.
- Klien lama tanpa user_id tidak didaftarkan → perilaku echo tetap sama persis.
- Disimpan di memori proses. Cukup untuk 1 proses uvicorn (Procfile sekarang);
  kalau nanti di-scale ke banyak worker/replica, perlu pub/sub (mis. Redis).
"""

import asyncio
import json
import logging
from collections import defaultdict
from uuid import UUID

from fastapi import WebSocket

log = logging.getLogger("fitwork")


def normalize_user_id(user_id) -> str | None:
    """UUID dalam bentuk kanonis (huruf kecil, bertanda hubung) atau None bila
    kosong/tidak valid. Dipakai agar kunci hub dari WS dan dari POST selalu sama."""
    if not user_id:
        return None
    try:
        return str(UUID(str(user_id)))
    except (ValueError, TypeError, AttributeError):
        return None


class VitalsHub:
    def __init__(self):
        self._conns: dict[str, set[WebSocket]] = defaultdict(set)
        # Satu lock per koneksi: echo loop dan push IoT bisa mengirim bersamaan
        # ke socket yang sama, lock mencegah frame saling tumpang tindih.
        self._locks: dict[WebSocket, asyncio.Lock] = {}

    def connect(self, user_id, ws: WebSocket) -> str | None:
        key = normalize_user_id(user_id)
        if key is None:
            return None
        self._conns[key].add(ws)
        self._locks[ws] = asyncio.Lock()
        return key

    def disconnect(self, key: str | None, ws: WebSocket) -> None:
        if key is None:
            return
        conns = self._conns.get(key)
        if conns is not None:
            conns.discard(ws)
            if not conns:
                self._conns.pop(key, None)
        self._locks.pop(ws, None)

    def has_listeners(self, user_id) -> bool:
        key = normalize_user_id(user_id)
        return bool(key and self._conns.get(key))

    async def send_text(self, ws: WebSocket, text: str) -> None:
        """Kirim ke satu socket; pakai lock bila socket terdaftar di hub."""
        lock = self._locks.get(ws)
        if lock is None:
            await ws.send_text(text)
            return
        async with lock:
            await ws.send_text(text)

    async def broadcast(self, user_id, payload: dict) -> int:
        """Kirim payload ke semua koneksi milik user. Mengembalikan jumlah
        koneksi yang berhasil dikirimi. Koneksi yang gagal dilepas dari hub."""
        key = normalize_user_id(user_id)
        if key is None:
            return 0
        text = json.dumps(payload)
        sent = 0
        for ws in list(self._conns.get(key, ())):
            try:
                await self.send_text(ws, text)
                sent += 1
            except Exception:  # noqa: BLE001 (socket putus; jangan ganggu yang lain)
                log.warning("ws push gagal, koneksi dilepas (user %s)", key)
                self.disconnect(key, ws)
        return sent


hub = VitalsHub()
