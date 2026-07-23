# FitWork — ML Training

Dua model, dua tujuan berbeda:

| Model | Input | Output | Dipakai oleh |
|---|---|---|---|
| `fitwork_model.pkl` | vitals kamera (HR, perclos, pupil, slumping, hours) | stress/fatigue/focus | `/healthscore`, `/messages` |
| `dass_model.pkl` | faktor hidup (sosmed, keuangan, dll) | prediksi skor stres DASS | `/assess` (pelengkap) |

> Catatan jujur: skor DASS-21 di `/assess` dihitung dengan **rumus resmi**
> (deterministik, valid). Model ML hanya **memprediksi** skor dari faktor
> hidup sebagai insight tambahan — korelasional, bukan diagnosis.

## 1. Model DASS-21 (data sudah ada)

**Dataset**: `ml/data/Survey-Survey.csv` (~280 responden, label DASS short-form).
Sudah ada file `DASS21_v1.csv` (kuesioner) + `Survey-Survey.sample.csv` (15 baris, untuk uji cepat).

**Untuk model final**, salin dataset penuh:
```
ml/data/Survey-Survey.csv   ← 280 baris penuh
```

Lalu latih:
```powershell
cd fitwork-functions
.venv\Scripts\python.exe ml\train_dass_model.py
```
Output: `ml/dass_model.pkl` + laporan MAE/R²/feature-importance.
Restart Function App → `/assess` otomatis memakai model.

## 2. Model SWELL-KW (vitals → stres, butuh download)

Lebih dekat ke proposal (stres dari kamera real-time). **Belum diimplementasi**
karena menunggu dataset:

1. Download dari Kaggle (butuh login):
   `kaggle.com/datasets/qiriro/swell-heart-rate-variability-hrv`
2. Taruh CSV di `ml/data/swell_hrv.csv`
3. Beri tahu Claude → akan dibuatkan `train_swell_model.py` yang menghasilkan
   `fitwork_model.pkl` baru (menggantikan model sintetis lama).

## Dependensi training (lokal saja, bukan runtime)
```
pandas, scikit-learn, xgboost, numpy
```
