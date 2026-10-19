"""
Test endpoint unit ruangan (/iot/room) termasuk field suhu_dummy dan push
realtime ke /ws/vitals. Supabase di-mock (MagicMock).
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import config
import iot
import main

KEY = "kunci-rahasia-test"
USER = "a75c8994-fbd3-4485-abe0-e7448aca1ff2"
USER_LAIN = "0b8e1f52-9c3d-4a7e-b1f2-abcdefabcdef"
# Persis seperti yang dikirim firmware ruang_fitlearn.ino (ArduinoJson)
FIRMWARE_DUMMY = {
    "device_id": "ruang-01", "user_id": USER, "suhu": 27.4, "kelembapan": 68.2,
    "suhu_dummy": True, "gas_adc": 412, "gas_ppm": 620,
}


@pytest.fixture
def supa(monkeypatch):
    fake = MagicMock(name="supabase_client")
    monkeypatch.setattr(iot, "get_supabase", lambda: fake)
    monkeypatch.setattr(config, "IOT_DEVICE_KEY", KEY)
    return fake


@pytest.fixture
def client(supa):
    with TestClient(main.app) as c:
        yield c


def auth(key=KEY):
    return {"X-Device-Key": key}


def inserted_row(supa):
    supa.table.assert_called_with("iot_room")
    insert = supa.table.return_value.insert
    insert.assert_called_once()
    return insert.call_args.args[0]


# ── Autentikasi ──

def test_room_key_salah_401(client, supa):
    assert client.post("/iot/room", json=FIRMWARE_DUMMY, headers=auth("salah")).status_code == 401
    supa.table.assert_not_called()


def test_room_tanpa_key_401(client, supa):
    assert client.post("/iot/room", json=FIRMWARE_DUMMY).status_code == 401


# ── suhu_dummy ──

def test_room_payload_firmware_dummy_200(client, supa):
    r = client.post("/iot/room", json=FIRMWARE_DUMMY, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert inserted_row(supa) == {
        "user_id": USER, "device_id": "ruang-01", "suhu": 27.4, "kelembapan": 68.2,
        "suhu_dummy": True, "gas_adc": 412, "gas_ppm": 620,
    }


def test_room_suhu_dummy_false_200(client, supa):
    r = client.post("/iot/room", json={**FIRMWARE_DUMMY, "suhu_dummy": False}, headers=auth())
    assert r.status_code == 200
    assert inserted_row(supa)["suhu_dummy"] is False


def test_room_tanpa_suhu_dummy_default_false(client, supa):
    body = {k: v for k, v in FIRMWARE_DUMMY.items() if k != "suhu_dummy"}
    r = client.post("/iot/room", json=body, headers=auth())
    assert r.status_code == 200
    assert inserted_row(supa)["suhu_dummy"] is False


def test_room_suhu_dummy_null_jadi_false(client, supa):
    r = client.post("/iot/room", json={**FIRMWARE_DUMMY, "suhu_dummy": None}, headers=auth())
    assert r.status_code == 200
    assert inserted_row(supa)["suhu_dummy"] is False


def test_room_suhu_dummy_bukan_boolean_422(client, supa):
    r = client.post("/iot/room", json={**FIRMWARE_DUMMY, "suhu_dummy": "ya"}, headers=auth())
    assert r.status_code == 422
    supa.table.assert_not_called()


def test_room_dht_gagal_dummy_mati_tanpa_suhu_200(client, supa):
    """IZINKAN_DUMMY_DHT = false: firmware tidak mengirim suhu & kelembapan."""
    body = {"device_id": "ruang-01", "user_id": USER, "suhu_dummy": False, "gas_adc": 401}
    r = client.post("/iot/room", json=body, headers=auth())
    assert r.status_code == 200
    row = inserted_row(supa)
    assert row["suhu"] is None and row["kelembapan"] is None and row["gas_ppm"] is None


@pytest.mark.parametrize("field,value", [("kelembapan", 120), ("suhu", 95), ("gas_adc", 2000), ("gas_ppm", -5)])
def test_room_nilai_di_luar_rentang_422(client, supa, field, value):
    r = client.post("/iot/room", json={**FIRMWARE_DUMMY, field: value}, headers=auth())
    assert r.status_code == 422


def test_room_user_tidak_ada_404(client, supa):
    err = Exception("fk")
    err.code = "23503"
    supa.table.return_value.insert.return_value.execute.side_effect = err
    assert client.post("/iot/room", json=FIRMWARE_DUMMY, headers=auth()).status_code == 404


def test_vitals_tetap_ke_tabel_iot_vitals(client, supa):
    body = {"device_id": "gelang-01", "user_id": USER, "heart_rate": 80}
    assert client.post("/iot/vitals", json=body, headers=auth()).status_code == 200
    supa.table.assert_called_with("iot_vitals")


# ── GET terbaru ──

def test_room_get_terbaru(client, supa):
    q = supa.table.return_value.select.return_value.eq.return_value.order.return_value.limit
    rows = [{"id": 2, "suhu": 27.5, "suhu_dummy": True}]
    q.return_value.execute.return_value = MagicMock(data=rows)
    r = client.get(f"/iot/room/{USER}/terbaru?limit=5")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "count": 1, "data": rows}
    supa.table.assert_called_with("iot_room")
    supa.table.return_value.select.assert_called_once_with(iot.ROOM_COLUMNS)
    assert "suhu_dummy" in iot.ROOM_COLUMNS
    q.assert_called_once_with(5)


# ── Realtime ──

def test_room_push_ke_ws_dengan_flag_dummy(client, supa):
    with client.websocket_connect(f"/ws/vitals?user_id={USER}") as ws:
        assert client.post("/iot/room", json=FIRMWARE_DUMMY, headers=auth()).status_code == 200
        msg = ws.receive_json()
    assert msg["source"] == "iot_room"
    assert msg["userId"] == USER
    assert msg["deviceId"] == "ruang-01"
    assert msg["room"] == {"suhu": 27.4, "kelembapan": 68.2, "suhuDummy": True, "gasAdc": 412, "gasPpm": 620}
    assert "focusScore" not in msg  # bukan pesan vitals


def test_room_push_tidak_ke_user_lain(client, supa, monkeypatch):
    monkeypatch.setattr(main, "compute_health", lambda v: {"status": "ok", "source": "live"})
    with client.websocket_connect(f"/ws/vitals?user_id={USER_LAIN}") as ws:
        client.post("/iot/room", json=FIRMWARE_DUMMY, headers=auth())
        ws.send_text('{"heartRate": 90}')
        assert ws.receive_json()["source"] == "live"
