# FitWork API (FastAPI)

Backend FitWork — migrasi dari Azure Functions ke **FastAPI**. Logika ML & skor
identik dengan versi lama (dipindah apa adanya di `core.py`); yang berubah hanya
layer HTTP/real-time.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET / POST | `/healthscore` | Skor stress/fatigue/focus dari vitals kamera (model ML) |
| POST | `/assess` | DASS-21 (rumus resmi) + prediksi ML opsional dari faktor hidup |
| WS | `/ws/vitals` | Real-time: client kirim vitals → server balas skor (pengganti SignalR). Opsional `?user_id=<uuid>` untuk ikut menerima data gelang IoT |
| POST | `/iot/vitals` | Data gelang IoT (HR & SpO2) → simpan ke Supabase `iot_vitals` + push ke `/ws/vitals` |
| GET | `/iot/vitals/{user_id}/terbaru?limit=20` | Data gelang terbaru milik user (urut `recorded_at` terbaru) |
| POST | `/iot/room` | Data unit ruangan (suhu, kelembapan, MQ135) → Supabase `iot_room` + push ke `/ws/vitals` |
| GET | `/iot/room/{user_id}/terbaru?limit=20` | Data ruangan terbaru milik user |

`/negotiate` & `/messages` (khas Azure SignalR) **dihapus** — digantikan `/ws/vitals`.

## Menjalankan (lokal)

```powershell
cd c:\laragon\www\fitwork-api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # lalu isi nilainya
.venv\Scripts\uvicorn main:app --reload --port 8000 --env-file .env
```

- API: <http://localhost:8000>  ·  Docs: <http://localhost:8000/docs>
- WebSocket: `ws://localhost:8000/ws/vitals`

## Konfigurasi

Semua dibaca dari environment variable di `config.py`. Lihat `.env.example`.

| Env | Wajib | Keterangan |
|---|---|---|
| `CORS_ORIGINS` | tidak | Origin frontend yang diizinkan, dipisah koma. Default dev Vite (`localhost:5173`) |
| `CORS_ORIGIN_REGEX` | tidak | Regex origin, mis. `https://.*\.vercel\.app` |
| `SUPABASE_URL` | untuk IoT | URL project Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | untuk IoT | Kunci service_role / secret key. Hanya di backend, jangan di frontend |
| `IOT_DEVICE_KEY` | untuk IoT | Kunci bersama gelang; kosong = semua request IoT ditolak 401 |

Client Supabase hanya dibuat di `db.py` (`get_supabase()`), lazy dan di-cache.

## Gelang IoT

Firmware (ESP32-C3 + MAX30102) mengirim tiap ~15 detik:

```http
POST /iot/vitals
Content-Type: application/json
X-Device-Key: <IOT_DEVICE_KEY>

{"device_id": "gelang-01", "user_id": "<uuid profiles.id>", "heart_rate": 78, "spo2": 97}
```

| Field | Tipe | Aturan |
|---|---|---|
| `device_id` | string | wajib, 1 sampai 64 karakter |
| `user_id` | string UUID | wajib, harus ada di `profiles.id` |
| `heart_rate` | int | wajib, 30 sampai 220 |
| `spo2` | int | opsional, 70 sampai 100 (kirim `null`/hilangkan bila sensor belum valid) |

Respons:

| Status | Arti |
|---|---|
| 200 `{"status": "ok"}` | Tersimpan |
| 401 | `X-Device-Key` kosong/salah, atau `IOT_DEVICE_KEY` belum di-set di server |
| 404 | `user_id` tidak ada di `profiles` |
| 422 | Body tidak valid (mis. `heart_rate` di luar 30 sampai 220) |
| 503 / 500 | Supabase belum dikonfigurasi / gagal menulis |

Realtime: frontend yang membuka `wss://<host>/ws/vitals?user_id=<uuid>` akan
menerima pesan berformat sama seperti pesan `/ws/vitals` biasa, dengan
`"source": "iot"`, `userId` berisi UUID user, plus `deviceId` dan
`vitals.spo2`. Klien lama tanpa `user_id` tidak berubah perilakunya.
Hub realtime disimpan di memori proses (`vitals_hub.py`), jadi cukup untuk satu
proses uvicorn seperti di `Procfile`.

Migrasi tabel: `supabase/migrations/20261019000000_create_iot_vitals.sql`
(tabel `iot_vitals`, index `user_id, recorded_at desc`, RLS select milik sendiri).

## Unit ruangan

Firmware `ruang_fitlearn.ino` (Wemos D1 Mini, DHT11 + MQ135) mengirim tiap ~30 detik
dengan header `X-Device-Key` yang sama:

```json
{"device_id": "ruang-01", "user_id": "<uuid>", "suhu": 27.4, "kelembapan": 68.2,
 "suhu_dummy": true, "gas_adc": 412, "gas_ppm": 620}
```

| Field | Tipe | Aturan |
|---|---|---|
| `suhu` | float | opsional, -20 sampai 70 |
| `kelembapan` | float | opsional, 0 sampai 100 |
| `suhu_dummy` | bool | opsional, default `false`; `true` = suhu & kelembapan simulasi (DHT gagal dibaca) |
| `gas_adc` | int | opsional, 0 sampai 1023 |
| `gas_ppm` | float | opsional, 0 ke atas (kosong selama MQ135 pemanasan) |

Push realtime ke `/ws/vitals?user_id=<uuid>` berbentuk
`{"source": "iot_room", "room": {"suhu", "kelembapan", "suhuDummy", "gasAdc", "gasPpm"}, ...}`.
Migrasi tabel: `supabase/migrations/20261020000000_create_iot_room.sql` (sudah
termasuk `notify pgrst, 'reload schema';`).

## Uji lokal dengan gelang

Gelang tidak bisa memakai `localhost` (itu alamat gelang sendiri), jadi backend
harus bisa diakses dari jaringan:

1. Laptop dan gelang terhubung ke WiFi yang sama. WiFi kampus/publik sering
   memblokir koneksi antarperangkat dan broadcast, jadi paling aman pakai
   hotspot HP untuk keduanya.
2. Terminal 1, backend (perhatikan `--host 0.0.0.0`):

   ```powershell
   .venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
   ```

3. Terminal 2, penanda server agar gelang menemukan IP laptop otomatis:

   ```powershell
   .venv\Scripts\python penanda_server.py
   ```

4. Saat Windows Firewall bertanya, izinkan untuk **Private networks** (port TCP
   8000 dan UDP 45454). Pastikan profil jaringan WiFi/hotspot di Windows diset
   *Private*.
5. Firmware: URL `http://<IP laptop>:8000/iot/vitals` (HTTP biasa, bukan HTTPS),
   header `X-Device-Key` sama dengan `IOT_DEVICE_KEY` di `.env`, dan `user_id`
   diisi ID akun dari kartu "Gelang FitLearn" di frontend.
6. Cek cepat tanpa gelang: buka <http://localhost:8000/docs>, POST `/iot/vitals`,
   isi header dan body, lalu lihat datanya di tabel `iot_vitals` Supabase.

## Test

```powershell
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

Supabase di-mock, jadi test tidak butuh koneksi atau env asli.

## Deploy

FastAPI butuh proses berjalan (bukan serverless seperti Azure Functions). Opsi:
Railway, Render, Fly.io, VPS + uvicorn/gunicorn, atau Azure Container Apps.
Jalankan produksi mis.:

```
uvicorn main:app --host 0.0.0.0 --port 8000
```

Set `CORS_ORIGINS` ke domain frontend produksi.

Untuk fitur IoT, tambahkan juga di Railway > service > Variables:
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `IOT_DEVICE_KEY`. Lalu jalankan
isi file migrasi di Supabase Dashboard > SQL Editor (sekali saja).

## File model

- `fitwork_model.pkl` — vitals → stress/fatigue/focus (dipakai `/healthscore`, `/ws/vitals`)
- `ml/dass_model.pkl` — opsional; bila ada, `/assess` menambah `mlPrediction`.
  Saat ini hanya tersedia `ml/dass_model.sample.pkl`, jadi prediksi ML DASS di-skip.
