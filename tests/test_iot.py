"""
Test endpoint IoT (/iot/vitals) dan push realtime ke /ws/vitals.

Supabase di-mock (MagicMock) sehingga test tidak butuh koneksi/env asli.
Model ML juga di-mock pada test WebSocket supaya test cepat dan tidak
bergantung pada file .pkl.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import config
import db
import iot
import main
from vitals_hub import hub

KEY = "kunci-rahasia-test"
USER = "7f3c2a1e-4b5d-4c6e-8f90-123456789abc"
USER_LAIN = "0b8e1f52-9c3d-4a7e-b1f2-abcdefabcdef"
VALID = {"device_id": "gelang-01", "user_id": USER, "heart_rate": 78, "spo2": 97}


def fake_compute_health(v: dict) -> dict:
    """Tiruan compute_health dengan bentuk payload yang sama seperti aslinya."""
    return {
        "status": "ok",
        "userId": "raditya-001",
        "timestamp": "2026-10-19T00:00:00+00:00",
        "source": "live" if v["had_input"] else "baseline",
        "focusScore": 70.0,
        "stressLevel": 30.0,
        "fatigueScore": 20.0,
        "vitals": {
            "heartRate": round(v["heart_rate"]),
            "pupilDilation": round(v["pupil_dilation"], 2),
            "perclos": round(v["perclos"], 2),
        },
        "breakWarning": {"triggered": False, "reason": None, "recommendedMinutes": None},
        "sessionInfo": {"activeWorkHours": 5.4, "deepWorkBlocks": 2, "breakCompliance": 68.0},
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
    supa.table.assert_called_with("iot_vitals")
    insert = supa.table.return_value.insert
    insert.assert_called_once()
    insert.return_value.execute.assert_called_once()
    return insert.call_args.args[0]


# ── Autentikasi X-Device-Key ──

def test_key_salah_401(client, supa):
    r = client.post("/iot/vitals", json=VALID, headers=auth("kunci-salah"))
    assert r.status_code == 401
    supa.table.assert_not_called()


def test_tanpa_key_401(client, supa):
    r = client.post("/iot/vitals", json=VALID)
    assert r.status_code == 401
    supa.table.assert_not_called()


def test_server_belum_set_iot_device_key_401(client, supa, monkeypatch):
    monkeypatch.setattr(config, "IOT_DEVICE_KEY", "")
    r = client.post("/iot/vitals", json=VALID, headers=auth(""))
    assert r.status_code == 401
    supa.table.assert_not_called()


def test_key_salah_dicek_sebelum_validasi_body(client, supa):
    r = client.post("/iot/vitals", json={"heart_rate": 999}, headers=auth("kunci-salah"))
    assert r.status_code == 401


# ── Payload ──

def test_payload_valid_200(client, supa):
    r = client.post("/iot/vitals", json=VALID, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert inserted_row(supa) == {
        "user_id": USER,
        "device_id": "gelang-01",
        "heart_rate": 78,
        "spo2": 97,
    }


def test_tanpa_spo2_tetap_200(client, supa):
    body = {k: v for k, v in VALID.items() if k != "spo2"}
    r = client.post("/iot/vitals", json=body, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert inserted_row(supa)["spo2"] is None


def test_spo2_null_tetap_200(client, supa):
    r = client.post("/iot/vitals", json={**VALID, "spo2": None}, headers=auth())
    assert r.status_code == 200
    assert inserted_row(supa)["spo2"] is None


@pytest.mark.parametrize("hr", [29, 221, 0, 500])
def test_heart_rate_di_luar_rentang_422(client, supa, hr):
    r = client.post("/iot/vitals", json={**VALID, "heart_rate": hr}, headers=auth())
    assert r.status_code == 422
    supa.table.assert_not_called()


@pytest.mark.parametrize("hr", [30, 220])
def test_heart_rate_batas_rentang_200(client, supa, hr):
    r = client.post("/iot/vitals", json={**VALID, "heart_rate": hr}, headers=auth())
    assert r.status_code == 200


@pytest.mark.parametrize("spo2", [69, 101])
def test_spo2_di_luar_rentang_422(client, supa, spo2):
    r = client.post("/iot/vitals", json={**VALID, "spo2": spo2}, headers=auth())
    assert r.status_code == 422
    supa.table.assert_not_called()


@pytest.mark.parametrize("field", ["device_id", "user_id", "heart_rate"])
def test_field_wajib_hilang_422(client, supa, field):
    body = {k: v for k, v in VALID.items() if k != field}
    r = client.post("/iot/vitals", json=body, headers=auth())
    assert r.status_code == 422


def test_user_id_bukan_uuid_422(client, supa):
    r = client.post("/iot/vitals", json={**VALID, "user_id": "bukan-uuid"}, headers=auth())
    assert r.status_code == 422


def test_user_id_tidak_ada_di_profiles_404(client, supa):
    err = Exception("insert or update violates foreign key constraint")
    err.code = "23503"
    supa.table.return_value.insert.return_value.execute.side_effect = err
    r = client.post("/iot/vitals", json=VALID, headers=auth())
    assert r.status_code == 404


def test_supabase_error_lain_500(client, supa):
    supa.table.return_value.insert.return_value.execute.side_effect = RuntimeError("timeout")
    r = client.post("/iot/vitals", json=VALID, headers=auth())
    assert r.status_code == 500


def test_supabase_belum_dikonfigurasi_503(client, monkeypatch):
    monkeypatch.setattr(iot, "get_supabase", db.get_supabase)
    monkeypatch.setattr(db, "_CLIENT", None)
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_ROLE_KEY", "")
    r = client.post("/iot/vitals", json=VALID, headers=auth())
    assert r.status_code == 503


# ── GET /iot/vitals/{user_id}/terbaru ──

def _query(supa):
    return supa.table.return_value.select.return_value.eq.return_value.order.return_value.limit


def test_get_terbaru_default_limit_20(client, supa):
    rows = [{"id": 2, "heart_rate": 80}, {"id": 1, "heart_rate": 78}]
    _query(supa).return_value.execute.return_value = MagicMock(data=rows)
    r = client.get(f"/iot/vitals/{USER}/terbaru")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "count": 2, "data": rows}
    supa.table.assert_called_with("iot_vitals")
    supa.table.return_value.select.return_value.eq.assert_called_once_with("user_id", USER)
    supa.table.return_value.select.return_value.eq.return_value.order.assert_called_once_with(
        "recorded_at", desc=True
    )
    _query(supa).assert_called_once_with(20)


def test_get_terbaru_limit_custom(client, supa):
    _query(supa).return_value.execute.return_value = MagicMock(data=[])
    r = client.get(f"/iot/vitals/{USER}/terbaru?limit=5")
    assert r.status_code == 200
    assert r.json()["count"] == 0
    _query(supa).assert_called_once_with(5)


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_get_terbaru_limit_tidak_valid_422(client, supa, limit):
    r = client.get(f"/iot/vitals/{USER}/terbaru?limit={limit}")
    assert r.status_code == 422


def test_get_terbaru_user_id_bukan_uuid_422(client, supa):
    r = client.get("/iot/vitals/abc/terbaru")
    assert r.status_code == 422


# ── Realtime /ws/vitals ──

@pytest.fixture
def fake_model(monkeypatch):
    monkeypatch.setattr(iot, "compute_health", fake_compute_health)
    monkeypatch.setattr(main, "compute_health", fake_compute_health)


def test_ws_dengan_user_id_menerima_push_iot(client, supa, fake_model):
    with client.websocket_connect(f"/ws/vitals?user_id={USER}") as ws:
        r = client.post("/iot/vitals", json=VALID, headers=auth())
        assert r.status_code == 200
        msg = ws.receive_json()

    lama = fake_compute_health({
        "heart_rate": 78, "perclos": 0.18, "pupil_dilation": 0.64, "had_input": True,
    })
    # Semua field lama tetap ada dengan tipe yang sama.
    assert set(lama) <= set(msg)
    assert set(lama["vitals"]) <= set(msg["vitals"])
    # Yang berbeda hanya penanda IoT.
    assert msg["source"] == "iot"
    assert msg["userId"] == USER
    assert msg["deviceId"] == "gelang-01"
    assert msg["vitals"]["heartRate"] == 78
    assert msg["vitals"]["spo2"] == 97
    for k in ("status", "focusScore", "stressLevel", "fatigueScore", "breakWarning", "sessionInfo"):
        assert msg[k] == lama[k]
    assert not hub.has_listeners(USER)  # koneksi dilepas setelah ditutup


def test_ws_user_id_huruf_besar_tetap_cocok(client, supa, fake_model):
    with client.websocket_connect(f"/ws/vitals?user_id={USER.upper()}") as ws:
        client.post("/iot/vitals", json=VALID, headers=auth())
        assert ws.receive_json()["source"] == "iot"


def test_ws_user_lain_tidak_menerima_push(client, supa, fake_model):
    with client.websocket_connect(f"/ws/vitals?user_id={USER_LAIN}") as ws:
        client.post("/iot/vitals", json=VALID, headers=auth())
        # Pesan pertama yang diterima harus balasan echo, bukan push IoT.
        ws.send_text('{"heartRate": 90}')
        msg = ws.receive_json()
        assert msg["source"] == "live"
        assert msg["vitals"]["heartRate"] == 90


def test_ws_tanpa_user_id_tetap_echo_seperti_dulu(client, supa, fake_model):
    with client.websocket_connect("/ws/vitals") as ws:
        ws.send_text('{"heartRate": 85}')
        msg = ws.receive_json()
    assert msg == fake_compute_health({
        "heart_rate": 85.0, "perclos": 0.18, "pupil_dilation": 0.64, "had_input": True,
    })
    assert "deviceId" not in msg


def test_push_gagal_tidak_mengganggu_post(client, supa, monkeypatch):
    def rusak(_v):
        raise RuntimeError("model hilang")

    monkeypatch.setattr(iot, "compute_health", rusak)
    with client.websocket_connect(f"/ws/vitals?user_id={USER}"):
        r = client.post("/iot/vitals", json=VALID, headers=auth())
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── Endpoint lama tidak berubah ──

def test_root_tidak_berubah(client):
    assert client.get("/").json() == {"status": "ok", "service": "fitwork-api"}


def test_assess_tidak_berubah(client):
    r = client.post("/assess", json={"answers": [1] * 21})
    assert r.status_code == 200
    assert r.json()["dass21"]["stress"] == {"score": 14, "severity": "Normal", "percent": 33.3}
    assert client.post("/assess", json={"answers": [1]}).status_code == 400


# ── Client Supabase asli ──

def test_client_supabase_asli_bisa_dibuat_dan_dicache(monkeypatch):
    """Menjaga agar tidak ada modul proyek yang menimpa paket dependensi supabase
    (mis. file bernama realtime.py) dan client hanya dibuat sekali."""
    monkeypatch.setattr(db, "_CLIENT", None)
    monkeypatch.setattr(config, "SUPABASE_URL", "https://contoh.supabase.co")
    monkeypatch.setattr(
        config,
        "SUPABASE_SERVICE_ROLE_KEY",
        "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJl",
    )
    pertama = db.get_supabase()
    assert db.get_supabase() is pertama
