"""
iot.py — Endpoint untuk gelang IoT (ESP32-C3 + MAX30102).

  POST /iot/vitals                     → simpan detak jantung/SpO2 ke tabel
                                         iot_vitals, lalu push ke klien
                                         /ws/vitals?user_id=<uuid> milik user itu
  GET  /iot/vitals/{user_id}/terbaru   → data terbaru user (default 20, urut
                                         recorded_at terbaru dulu)

  POST /iot/room                       → data unit ruangan (Wemos D1 Mini: DHT11
                                         + MQ135) ke tabel iot_room, lalu push ke
                                         /ws/vitals?user_id=<uuid> (source="iot_room")
  GET  /iot/room/{user_id}/terbaru     → data ruangan terbaru user

Semua POST wajib header X-Device-Key yang sama dengan env IOT_DEVICE_KEY.
Router ini didaftarkan di main.py lewat app.include_router(...).
"""

import logging
import secrets
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

import config
from core import compute_health, read_vitals
from db import SupabaseNotConfigured, get_supabase
from vitals_hub import hub

log = logging.getLogger("fitwork")

TABLE = "iot_vitals"
SELECT_COLUMNS = "id,user_id,device_id,heart_rate,spo2,recorded_at"
ROOM_TABLE = "iot_room"
ROOM_COLUMNS = "id,user_id,device_id,suhu,kelembapan,suhu_dummy,gas_adc,gas_ppm,recorded_at"
FK_VIOLATION = "23503"  # kode Postgres: user_id tidak ada di profiles

router = APIRouter(prefix="/iot", tags=["iot"])


class IoTVitalsIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=64, examples=["gelang-01"])
    user_id: UUID
    heart_rate: int = Field(ge=30, le=220, examples=[78])
    spo2: int | None = Field(default=None, ge=70, le=100, examples=[97])


class IoTRoomIn(BaseModel):
    """Data unit ruangan. suhu/kelembapan boleh kosong (DHT gagal & dummy dimatikan).
    suhu_dummy=true berarti suhu & kelembapan adalah data simulasi dari firmware."""
    device_id: str = Field(min_length=1, max_length=64, examples=["ruang-01"])
    user_id: UUID
    suhu: float | None = Field(default=None, ge=-20, le=70, examples=[27.4])
    kelembapan: float | None = Field(default=None, ge=0, le=100, examples=[68.2])
    suhu_dummy: bool = Field(default=False, examples=[True])
    gas_adc: int | None = Field(default=None, ge=0, le=1023, examples=[412])
    gas_ppm: float | None = Field(default=None, ge=0, le=100000, examples=[620])

    @field_validator("suhu_dummy", mode="before")
    @classmethod
    def _null_jadi_false(cls, v):
        # Firmware lama tidak mengirim field ini; null juga dianggap data asli.
        return False if v is None else v


def require_device_key(
    x_device_key: str | None = Header(default=None, alias="X-Device-Key"),
) -> None:
    """Tolak (401) bila header kosong, salah, atau server belum punya IOT_DEVICE_KEY."""
    expected = config.IOT_DEVICE_KEY
    if not expected:
        log.warning("IOT_DEVICE_KEY belum di-set; semua request IoT ditolak")
    if (
        not expected
        or not x_device_key
        or not secrets.compare_digest(x_device_key.encode(), expected.encode())
    ):
        raise HTTPException(status_code=401, detail="X-Device-Key tidak valid")


# ── Akses database (sync, dijalankan di threadpool agar event loop tidak terblokir) ──

def _insert_into(table: str, row: dict) -> None:
    get_supabase().table(table).insert(row).execute()


def _select_latest_from(table: str, columns: str, user_id: str, limit: int) -> list[dict]:
    res = (
        get_supabase()
        .table(table)
        .select(columns)
        .eq("user_id", user_id)
        .order("recorded_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _insert_row(row: dict) -> None:
    _insert_into(TABLE, row)


def _select_latest(user_id: str, limit: int) -> list[dict]:
    return _select_latest_from(TABLE, SELECT_COLUMNS, user_id, limit)


def _insert_room_row(row: dict) -> None:
    _insert_into(ROOM_TABLE, row)


def _select_room_latest(user_id: str, limit: int) -> list[dict]:
    return _select_latest_from(ROOM_TABLE, ROOM_COLUMNS, user_id, limit)


async def _run_db(fn, *args, action: str):
    try:
        return await run_in_threadpool(fn, *args)
    except SupabaseNotConfigured as e:
        log.error("iot: %s", e)
        raise HTTPException(status_code=503, detail="Database belum dikonfigurasi di server")
    except Exception as e:  # noqa: BLE001 (error dari postgrest/jaringan)
        if getattr(e, "code", None) == FK_VIOLATION:
            raise HTTPException(status_code=404, detail="user_id tidak terdaftar di profiles")
        log.exception("iot: gagal %s data", action)
        raise HTTPException(status_code=500, detail=f"Gagal {action} data di database")


# ── Push realtime ke /ws/vitals ──

def build_iot_payload(user_id: str, data: IoTVitalsIn) -> dict:
    """Payload berformat SAMA dengan pesan /ws/vitals lama (hasil compute_health),
    dengan source="iot". Tambahan: deviceId dan vitals.spo2. Fitur selain detak
    jantung (perclos, pupil, dst) memakai baseline read_vitals karena gelang
    hanya mengukur HR/SpO2."""
    payload = compute_health(read_vitals({"heartRate": data.heart_rate}))
    payload["source"] = "iot"
    payload["userId"] = user_id
    payload["deviceId"] = data.device_id
    # Nilai asli sensor (read_vitals meng-clamp HR ke 40-200 khusus untuk model).
    payload["vitals"]["heartRate"] = data.heart_rate
    payload["vitals"]["spo2"] = data.spo2
    return payload


async def push_realtime(user_id: str, data: IoTVitalsIn) -> None:
    if not hub.has_listeners(user_id):
        return  # tidak ada yang mendengarkan → tidak perlu hitung model
    try:
        payload = await run_in_threadpool(build_iot_payload, user_id, data)
    except Exception:  # noqa: BLE001 (data sudah tersimpan; push cukup di-skip)
        log.exception("iot: gagal membangun payload realtime")
        return
    await hub.broadcast(user_id, payload)


def build_room_payload(user_id: str, data: IoTRoomIn) -> dict:
    """Pesan ruangan untuk /ws/vitals. Bentuknya sendiri (bukan pesan vitals),
    ditandai source="iot_room" supaya aplikasi tidak mencampurnya dengan skor."""
    return {
        "status": "ok",
        "source": "iot_room",
        "userId": user_id,
        "deviceId": data.device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "room": {
            "suhu": data.suhu,
            "kelembapan": data.kelembapan,
            "suhuDummy": data.suhu_dummy,
            "gasAdc": data.gas_adc,
            "gasPpm": data.gas_ppm,
        },
    }


async def push_room(user_id: str, data: IoTRoomIn) -> None:
    if not hub.has_listeners(user_id):
        return
    await hub.broadcast(user_id, build_room_payload(user_id, data))


# ── Endpoint ──

@router.post("/vitals", dependencies=[Depends(require_device_key)])
async def post_iot_vitals(data: IoTVitalsIn, background: BackgroundTasks):
    user_id = str(data.user_id)
    row = {
        "user_id": user_id,
        "device_id": data.device_id,
        "heart_rate": data.heart_rate,
        "spo2": data.spo2,
    }
    await _run_db(_insert_row, row, action="menyimpan")
    # Dijalankan setelah respons dikirim, jadi firmware tidak ikut menunggu.
    background.add_task(push_realtime, user_id, data)
    return {"status": "ok"}


@router.get("/vitals/{user_id}/terbaru")
async def get_iot_vitals_terbaru(user_id: UUID, limit: int = Query(20, ge=1, le=100)):
    rows = await _run_db(_select_latest, str(user_id), limit, action="membaca")
    return {"status": "ok", "count": len(rows), "data": rows}


@router.post("/room", dependencies=[Depends(require_device_key)])
async def post_iot_room(data: IoTRoomIn, background: BackgroundTasks):
    user_id = str(data.user_id)
    row = {
        "user_id": user_id,
        "device_id": data.device_id,
        "suhu": data.suhu,
        "kelembapan": data.kelembapan,
        "suhu_dummy": data.suhu_dummy,
        "gas_adc": data.gas_adc,
        "gas_ppm": data.gas_ppm,
    }
    await _run_db(_insert_room_row, row, action="menyimpan")
    background.add_task(push_room, user_id, data)
    return {"status": "ok"}


@router.get("/room/{user_id}/terbaru")
async def get_iot_room_terbaru(user_id: UUID, limit: int = Query(20, ge=1, le=100)):
    rows = await _run_db(_select_room_latest, str(user_id), limit, action="membaca")
    return {"status": "ok", "count": len(rows), "data": rows}
