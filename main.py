"""
main.py — FastAPI app FitWork.

Pengganti Azure Functions. Menyediakan:
  GET/POST /healthscore   → skor kesehatan dari vitals kamera (model ML)
  POST     /assess        → DASS-21 + prediksi ML opsional
  WS       /ws/vitals     → real-time: client kirim vitals → server balas skor
                            (pengganti SignalR echo; per-koneksi, cukup 1 user).
                            Opsional ?user_id=<uuid> → ikut menerima push data
                            gelang IoT milik user tsb (source="iot").
  POST     /iot/vitals                    → data gelang IoT (lihat iot.py)
  GET      /iot/vitals/{user_id}/terbaru  → data gelang terbaru (lihat iot.py)
  POST     /iot/room                      → data unit ruangan (lihat iot.py)
  GET      /iot/room/{user_id}/terbaru    → data ruangan terbaru (lihat iot.py)

CORS diurus di sini via CORSMiddleware (dulu di level platform Azure).
Jalankan lokal:  uvicorn main:app --reload --port 8000
"""

import json
import logging

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core import compute_health, read_vitals, compute_assessment
from config import ALLOWED_ORIGINS, ALLOWED_ORIGIN_REGEX
from iot import router as iot_router
from vitals_hub import hub

log = logging.getLogger("fitwork")

app = FastAPI(title="FitWork API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=ALLOWED_ORIGIN_REGEX,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(iot_router)


@app.get("/")
def root():
    return {"status": "ok", "service": "fitwork-api"}


async def _json_body(req: Request) -> dict:
    """Parse body request jadi dict; toleran terhadap Content-Type text/plain
    (frontend memakainya untuk menghindari CORS preflight) dan body kosong."""
    raw = await req.body()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


@app.api_route("/healthscore", methods=["GET", "POST"])
async def healthscore(req: Request):
    try:
        body = await _json_body(req) if req.method == "POST" else {}
        params = dict(req.query_params)
        data = compute_health(read_vitals(body, params))
    except Exception as e:  # noqa: BLE001 — kembalikan pesan agar UI bisa tampil
        log.exception("healthscore failed")
        data = {"status": "error", "message": str(e)}
    return JSONResponse(data)


@app.post("/assess")
async def assess(req: Request):
    try:
        body = await _json_body(req)
        return JSONResponse(compute_assessment(body))
    except ValueError as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        log.exception("assess failed")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


@app.websocket("/ws/vitals")
async def ws_vitals(ws: WebSocket, user_id: str | None = None):
    """
    Real-time echo (pengganti SignalR):
      1. Client buka koneksi.
      2. Tiap ~2 detik client kirim JSON vitals kamera.
      3. Server hitung skor ML lalu kirim balik payload 'healthUpdate' ke
         client tersebut.
    Karena SignalR lama hanya echo ke pengirim (demo satu user), model
    per-koneksi ini cukup dan jauh lebih sederhana daripada broadcast hub.

    Tambahan IoT: bila client membuka /ws/vitals?user_id=<uuid>, koneksi
    didaftarkan ke hub (vitals_hub.py) sehingga data dari POST /iot/vitals milik
    user itu ikut didorong ke sini dengan format pesan yang sama + source="iot".
    Tanpa user_id (atau user_id tidak valid) perilakunya tetap echo seperti dulu.
    """
    await ws.accept()
    hub_key = hub.connect(user_id, ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = json.loads(raw) if raw else {}
                if not isinstance(body, dict):
                    body = {}
                data = compute_health(read_vitals(body))
            except Exception as e:  # noqa: BLE001
                log.exception("ws compute failed")
                data = {"status": "error", "message": str(e)}
            await hub.send_text(ws, json.dumps(data))
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(hub_key, ws)
