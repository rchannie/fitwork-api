"""
core.py — Logika bisnis & ML FitWork.

Dipindahkan APA ADANYA dari Azure Functions (function_app.py) supaya perilaku
model & skor identik. File ini TIDAK tahu apa-apa soal HTTP/WebSocket — hanya
menerima dict vitals dan mengembalikan dict hasil. Layer FastAPI (main.py) yang
mengurus request/response.
"""

import os
from datetime import datetime, timezone


# ── Model di-cache antar request agar tidak di-load tiap panggilan ──
_BUNDLE = None
_DASS_BUNDLE = None


def build_break_warning(stress_level, fatigue_score, active_work_hours):
    """
    Tentukan apakah user perlu istirahat.
    - triggered = True jika stress > 65 ATAU fatigue > 60 ATAU activeWorkHours > 2.5
    - reason mengikuti prioritas kondisi yang terdeteksi
    - recommendedMinutes = 10 saat triggered
    """
    high_stress = stress_level > 65
    high_fatigue = fatigue_score > 60
    long_session = active_work_hours > 2.5

    triggered = high_stress or high_fatigue or long_session

    reason = None
    if high_stress and high_fatigue:
        reason = "cognitive_overload"
    elif high_stress:
        reason = "stress_index_high"
    elif high_fatigue:
        reason = "fatigue_detected"
    elif long_session:
        reason = "long_session"

    return {
        "triggered": triggered,
        "reason": reason,
        "recommendedMinutes": 10 if triggered else None,
    }


def read_vitals(body: dict | None, params: dict | None = None) -> dict:
    """
    Ambil vitals dari body JSON dan/atau query params, dengan fallback ke
    baseline yang masuk akal bila tidak dikirim. Semua nilai di-clamp ke
    rentang fisiologis agar prediksi model tetap stabil.

    body    : dict hasil parse JSON request (boleh None).
    params  : dict query string (boleh None) — dipakai untuk GET /healthscore.
    """
    body = body if isinstance(body, dict) else {}
    params = params if isinstance(params, dict) else {}

    def pick(key, default):
        if body.get(key) is not None:
            val = body.get(key)
        else:
            val = params.get(key, default)
        try:
            return float(val)
        except (TypeError, ValueError):
            return float(default)

    def clamp(x, lo, hi):
        return max(lo, min(hi, x))

    return {
        "heart_rate": clamp(pick("heartRate", 72), 40, 200),
        "perclos": clamp(pick("perclos", 0.18), 0.0, 1.0),
        "pupil_dilation": clamp(pick("pupilDilation", 0.64), 0.0, 1.5),
        # Fitur model ke-4 = is_slumping (postur membungkuk: 0/1)
        "is_slumping": 1.0 if pick("isSlumping", 0) >= 0.5 else 0.0,
        "active_work_hours": clamp(pick("activeWorkHours", 5.4), 0, 16),
        "deep_work_blocks": int(clamp(pick("deepWorkBlocks", 2), 0, 20)),
        "break_compliance": clamp(pick("breakCompliance", 68), 0, 100),
        "had_input": len(body) > 0,
    }


def _load_bundle():
    global _BUNDLE
    if _BUNDLE is None:
        import pickle
        path = os.path.join(os.path.dirname(__file__), "fitwork_model.pkl")
        with open(path, "rb") as f:
            _BUNDLE = pickle.load(f)
    return _BUNDLE


def compute_health(v: dict) -> dict:
    """
    Jalankan model ML pada vitals (hasil read_vitals) dan bangun payload lengkap
    yang dikonsumsi frontend. Dipakai oleh /healthscore maupun WebSocket /ws/vitals
    — satu sumber kebenaran.
    """
    bundle = _load_bundle()
    models = bundle["models"]
    scaler = bundle["scaler"]
    features = bundle.get("features", [])

    # Petakan nama fitur model → nilai vitals, dipilih dari bundle["features"]
    # sehingga urutan/komposisi fitur otomatis mengikuti model yang dimuat.
    feat_value = {
        "heart_rate": v["heart_rate"], "perclos": v["perclos"],
        "pupil_dilation": v["pupil_dilation"], "is_slumping": v["is_slumping"],
        "session_hours": v["active_work_hours"], "active_work_hours": v["active_work_hours"],
    }
    row = [float(feat_value.get(name, 0.0)) for name in features]
    X = scaler.transform([row])

    def clamp01(x):
        return round(max(0.0, min(100.0, float(x))), 1)

    # Model regresi bisa keluar dari 0–100; clamp agar gauge tidak rusak.
    stress = clamp01(models["stress_score"].predict(X)[0])
    fatigue = clamp01(models["fatigue_score"].predict(X)[0])
    focus = clamp01(models["focus_score"].predict(X)[0])

    return {
        "status": "ok",
        "userId": "raditya-001",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "live" if v["had_input"] else "baseline",
        "focusScore": focus,
        "stressLevel": stress,
        "fatigueScore": fatigue,
        "vitals": {
            "heartRate": round(v["heart_rate"]),
            "pupilDilation": round(v["pupil_dilation"], 2),
            "perclos": round(v["perclos"], 2),
        },
        "breakWarning": build_break_warning(stress, fatigue, v["active_work_hours"]),
        "sessionInfo": {
            "activeWorkHours": v["active_work_hours"],
            "deepWorkBlocks": v["deep_work_blocks"],
            "breakCompliance": v["break_compliance"],
        },
    }


# ════════════════════════════════════════════════════════════════════
#  DASS-21 Mental Health Assessment
#  - Skor DASS dihitung dgn RUMUS RESMI (deterministik, valid klinis).
#  - Model ML (dass_model.pkl) memprediksi risiko dari FAKTOR HIDUP,
#    sbg pelengkap (opsional; jika model tidak ada, bagian ini di-skip).
# ════════════════════════════════════════════════════════════════════

# Ambang keparahan DASS-21 (skor sudah dikali 2 sesuai konvensi).
DASS_BANDS = {
    "stress": [(14, "Normal"), (18, "Mild"), (25, "Moderate"), (33, "Severe"), (999, "Extremely Severe")],
    "anxiety": [(7, "Normal"), (9, "Mild"), (14, "Moderate"), (19, "Severe"), (999, "Extremely Severe")],
    "depression": [(9, "Normal"), (13, "Mild"), (20, "Moderate"), (27, "Severe"), (999, "Extremely Severe")],
}

# Indeks pertanyaan (1..21) per sub-skala DASS-21 (urutan standar).
DASS_INDEX = {
    "stress": [1, 6, 8, 11, 12, 14, 18],
    "anxiety": [2, 4, 7, 9, 15, 19, 20],
    "depression": [3, 5, 10, 13, 16, 17, 21],
}


def _severity(scale, score):
    for limit, label in DASS_BANDS[scale]:
        if score <= limit:
            return label
    return "Unknown"


def _load_dass():
    global _DASS_BUNDLE
    if _DASS_BUNDLE is None:
        path = os.path.join(os.path.dirname(__file__), "ml", "dass_model.pkl")
        if os.path.exists(path):
            import pickle
            with open(path, "rb") as f:
                _DASS_BUNDLE = pickle.load(f)
        else:
            _DASS_BUNDLE = False  # tandai "tidak tersedia"
    return _DASS_BUNDLE


def compute_assessment(body: dict) -> dict:
    """
    body:
      {
        "answers": [0..3] × 21,            # jawaban DASS-21 (wajib)
        "lifeFactors": { ... }             # faktor hidup (opsional, untuk ML)
      }
    Mengembalikan skor + tingkat keparahan tiap sub-skala, plus prediksi ML
    risiko stres dari faktor hidup bila model tersedia. Melempar ValueError bila
    answers tidak valid (dipetakan ke HTTP 400 di layer FastAPI).
    """
    answers = body.get("answers", [])
    if not isinstance(answers, list) or len(answers) < 21:
        raise ValueError("answers harus berisi 21 nilai (0-3)")
    ans = [max(0, min(3, int(a))) for a in answers[:21]]

    result = {}
    for scale, idxs in DASS_INDEX.items():
        raw = sum(ans[i - 1] for i in idxs)  # 0..21
        score = raw * 2                       # konvensi DASS-21
        result[scale] = {
            "score": score,
            "severity": _severity(scale, score),
            "percent": round(score / 42 * 100, 1),
        }

    out = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dass21": result,
    }

    # ── Prediksi ML risiko stres dari faktor hidup (opsional) ──
    bundle = _load_dass()
    life = body.get("lifeFactors")
    if bundle and isinstance(life, dict):
        try:
            import numpy as np
            feats = bundle["features"]
            row = [float(life.get(f, 0) or 0) for f in feats]
            pred = float(bundle["model"].predict(np.array([row]))[0])
            out["mlPrediction"] = {
                "predictedStress": round(max(0, min(100, pred)), 1),
                "basedOn": "life_factors",
                "modelMAE": bundle.get("meta", {}).get("mae"),
                "note": "Prediksi korelasional dari faktor hidup, bukan diagnosis.",
            }
        except Exception as e:
            out["mlPrediction"] = {"error": str(e)}

    return out
