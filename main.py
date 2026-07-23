"""
main.py — FastAPI app FitWork.

Pengganti Azure Functions. Menyediakan:
  GET/POST /healthscore   → skor kesehatan dari vitals kamera (model ML)
  POST     /assess        → DASS-21 + prediksi ML opsional
  WS       /ws/vitals     → real-time: client kirim vitals → server balas skor
                            (pengganti SignalR echo; per-koneksi, cukup 1 user)

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
async def ws_vitals(ws: WebSocket):
    """
    Real-time echo (pengganti SignalR):
      1. Client buka koneksi.
      2. Tiap ~2 detik client kirim JSON vitals kamera.
      3. Server hitung skor ML lalu kirim balik payload 'healthUpdate' ke
         client tersebut.
    Karena SignalR lama hanya echo ke pengirim (demo satu user), model
    per-koneksi ini cukup dan jauh lebih sederhana daripada broadcast hub.
    """
    await ws.accept()
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
            await ws.send_text(json.dumps(data))
    except WebSocketDisconnect:
        pass
