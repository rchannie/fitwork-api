# FitWork API (FastAPI)

Backend FitWork — migrasi dari Azure Functions ke **FastAPI**. Logika ML & skor
identik dengan versi lama (dipindah apa adanya di `core.py`); yang berubah hanya
layer HTTP/real-time.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| GET / POST | `/healthscore` | Skor stress/fatigue/focus dari vitals kamera (model ML) |
| POST | `/assess` | DASS-21 (rumus resmi) + prediksi ML opsional dari faktor hidup |
| WS | `/ws/vitals` | Real-time: client kirim vitals → server balas skor (pengganti SignalR) |

`/negotiate` & `/messages` (khas Azure SignalR) **dihapus** — digantikan `/ws/vitals`.

## Menjalankan (lokal)

```powershell
cd c:\laragon\www\fitwork-api
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\uvicorn main:app --reload --port 8000
```

- API: <http://localhost:8000>  ·  Docs: <http://localhost:8000/docs>
- WebSocket: `ws://localhost:8000/ws/vitals`

## Konfigurasi

`CORS_ORIGINS` (env, opsional) — origin frontend yang diizinkan, dipisah koma.
Lihat `.env.example`. Default sudah mencakup dev Vite (`localhost:5173`).

## Deploy

FastAPI butuh proses berjalan (bukan serverless seperti Azure Functions). Opsi:
Railway, Render, Fly.io, VPS + uvicorn/gunicorn, atau Azure Container Apps.
Jalankan produksi mis.:

```
uvicorn main:app --host 0.0.0.0 --port 8000
```

Set `CORS_ORIGINS` ke domain frontend produksi.

## File model

- `fitwork_model.pkl` — vitals → stress/fatigue/focus (dipakai `/healthscore`, `/ws/vitals`)
- `ml/dass_model.pkl` — opsional; bila ada, `/assess` menambah `mlPrediction`.
  Saat ini hanya tersedia `ml/dass_model.sample.pkl`, jadi prediksi ML DASS di-skip.
