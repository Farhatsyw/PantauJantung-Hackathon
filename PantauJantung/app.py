import hmac
import logging
import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, jsonify, request, send_from_directory, session
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# ── Secret key — required for signed session cookies ────────────────
app.secret_key = os.getenv("SECRET_KEY", "change_me_in_production")

# ── Environment config ───────────────────────────────────────────────
LANGFLOW_API_KEY  = os.getenv("LANGFLOW_API_KEY", "")
LANGFLOW_FLOW_ID  = os.getenv("LANGFLOW_FLOW_ID", "")
LANGFLOW_BASE_URL = os.getenv("LANGFLOW_BASE_URL", "http://localhost:7860")
API_KEY           = os.getenv("API_KEY", "")
DEMO_MODE         = os.getenv("DEMO_MODE", "false").strip().lower() == "true"

# ── Active measurement state (shared across threads) ─────────────────
_MEASUREMENT_TTL = 300   # 5 menit dalam detik

_active_lock    = threading.Lock()
_active_patient = {
    "id_pasien"  : None,
    "started_at" : 0.0,   # time.monotonic()
}

_rate_lock      = threading.Lock()
_last_sensor_ts = {}   # { id_pasien: time.monotonic() }

# ── Semaphore analisis (maks 2 bersamaan) ─────────────────────────────
_analisis_sem = threading.BoundedSemaphore(2)

# ── Rate limiting simulasi ────────────────────────────────────────────
_sim_patient_lock = threading.Lock()
_sim_patient_ts   = {}     # { id_pasien: time.monotonic() } — per-pasien 30 detik
_sim_global_lock  = threading.Lock()
_sim_global_times = []     # list[time.monotonic()] — global 10 per menit

# ── Status alat (dikirim ESP32 via POST /api/device-status) ──────────
_DEVICE_STATUS_ALLOWLIST = frozenset({
    "siap", "mengukur", "jari_terangkat", "letakkan_kembali",
    "sinyal_lemah", "tidak_stabil", "sensor_error", "terkirim",
    "tidak_ada_pengukuran_aktif", "gagal_kirim",
})
_device_status_lock = threading.Lock()
_DEVICE_STATUS = {"kode": None, "waktu": 0.0}   # waktu = time.monotonic()

# Rate limit POST /api/device-status: maks 10 request per detik (global)
_dev_status_rl_lock  = threading.Lock()
_dev_status_rl_times = []   # list[time.monotonic()]

# ── Retry analisis: state per nomor baris (in-memory) ────────────────
# { row_number: {"attempts": int, "next_try": time.monotonic()} }
_retry_state_lock = threading.Lock()
_retry_state: dict[int, dict] = {}
_RETRY_DELAYS = [60, 120, 240, 480, 900, 1800]  # jeda percobaan ke-1..6 (detik)

# ── Import Google Sheets layer (lazy — error hanya saat dipakai) ─────
import sheets


# ── Static: serve the SPA shell ─────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


# ── Cache-Control: no-store on all /api/* responses ─────────────────
@app.after_request
def set_no_store(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ── Health-check ─────────────────────────────────────────────────────
@app.route("/api/ping")
def ping():
    return jsonify({"status": "ok"})


# ── GET /api/patients — daftar semua pasien ──────────────────────────
@app.route("/api/patients", methods=["GET"])
def get_patients():
    try:
        patients = sheets.get_patients()
        # Kembalikan sebagai list agar mudah diiterasi di frontend
        result = list(patients.values())
        return jsonify(result)
    except RuntimeError as exc:
        logger.error("get_patients config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi. Hubungi administrator."}), 503
    except Exception as exc:
        logger.error("get_patients error: %s", exc)
        return jsonify({"error": "Gagal memuat daftar pasien. Coba beberapa saat lagi."}), 500


# ── POST /api/patients — tambah pasien baru ──────────────────────────
@app.route("/api/patients", methods=["POST"])
def add_patient():
    data = request.get_json(silent=True) or {}

    nama           = str(data.get("nama") or "").strip()
    umur_raw       = data.get("umur")
    jenis_kelamin  = str(data.get("jenis_kelamin") or "").strip()

    # Validasi
    errors = {}
    if not nama:
        errors["nama"] = "Nama tidak boleh kosong."
    elif len(nama) > 100:
        errors["nama"] = "Nama maksimal 100 karakter."

    try:
        umur = int(umur_raw)
        if not (0 <= umur <= 120):
            errors["umur"] = "Umur harus antara 0 dan 120."
    except (TypeError, ValueError):
        errors["umur"] = "Masukkan umur yang valid."

    if jenis_kelamin not in ("Laki-laki", "Perempuan"):
        errors["jenis_kelamin"] = "Jenis kelamin harus 'Laki-laki' atau 'Perempuan'."

    if errors:
        return jsonify({"error": "Validasi gagal.", "fields": errors}), 422

    try:
        new_id = sheets.add_patient(nama, umur, jenis_kelamin)
        return jsonify({"id_pasien": new_id, "nama": nama, "umur": umur, "jenis_kelamin": jenis_kelamin}), 201
    except RuntimeError as exc:
        logger.error("add_patient config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi. Hubungi administrator."}), 503
    except Exception as exc:
        logger.error("add_patient error: %s", exc)
        return jsonify({"error": "Gagal menyimpan pasien. Coba beberapa saat lagi."}), 500


# ── GET /api/patient-data/<id_pasien> — data pasien + sensor terbaru ─
@app.route("/api/patient-data/<id_pasien>")
def patient_data(id_pasien):
    id_pasien = str(id_pasien).strip()
    fresh = request.args.get("fresh") == "1"

    try:
        pasien = sheets.get_patient(id_pasien)
    except RuntimeError as exc:
        logger.error("patient_data config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi. Hubungi administrator."}), 503
    except Exception as exc:
        logger.error("patient_data error: %s", exc)
        return jsonify({"error": "Gagal memuat data pasien."}), 500

    if not pasien:
        return jsonify({"error": f"Pasien '{id_pasien}' tidak ditemukan."}), 404

    try:
        sensor_rows = sheets.get_sensor_rows(id_pasien, limit=50, fresh=fresh)
    except Exception as exc:
        logger.error("get_sensor_rows error for %s: %s", id_pasien, exc)
        sensor_rows = []

    # Tambahkan field `analisis` ke setiap baris
    VALID_STATUS = {"Normal", "Waspada", "Tinggi"}
    now_epoch = time.time()
    for row in sensor_rows:
        status = str(row.get("status", "")).strip()
        if status in VALID_STATUS:
            row["analisis"] = "selesai"
        elif not status:
            # Estimasi umur baris dari timestamp "YYYY-MM-DD HH:MM"
            ts = str(row.get("timestamp", "")).strip()
            try:
                _TZ = timezone(timedelta(hours=7))
                ts_dt = datetime.strptime(ts[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_TZ)
                umur_detik = now_epoch - ts_dt.timestamp()
                row["analisis"] = "menunggu" if umur_detik < 180 else "tertunda"
            except (ValueError, TypeError):
                row["analisis"] = "tertunda"
        else:
            row["analisis"] = "selesai"

    return jsonify({
        "id_pasien"    : pasien["id_pasien"],
        "nama"         : pasien["nama"],
        "umur"         : pasien["umur"],
        "jenis_kelamin": pasien["jenis_kelamin"],
        "sensor"       : sensor_rows,
    })


# ── Clear patient — hapus id_pasien dari session ────────────────────
@app.route("/api/clear-patient", methods=["POST"])
def clear_patient():
    session.pop("id_pasien", None)
    return jsonify({"status": "ok"})


# ── POST /api/start-measurement — mulai sesi pengukuran ──────────────
@app.route("/api/start-measurement", methods=["POST"])
def start_measurement():
    data      = request.get_json(silent=True) or {}
    id_pasien = str(data.get("id_pasien") or "").strip()

    if not id_pasien:
        return jsonify({"error": "id_pasien diperlukan"}), 400

    try:
        pasien = sheets.get_patient(id_pasien)
    except RuntimeError as exc:
        logger.error("start_measurement config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi."}), 503
    except Exception as exc:
        logger.error("start_measurement error: %s", exc)
        return jsonify({"error": "Gagal memverifikasi pasien."}), 500

    if not pasien:
        return jsonify({"error": f"Pasien '{id_pasien}' tidak ditemukan."}), 404

    with _active_lock:
        _active_patient["id_pasien"]  = id_pasien
        _active_patient["started_at"] = time.monotonic()

    logger.info("start_measurement: pasien %s, TTL %ds", id_pasien, _MEASUREMENT_TTL)
    return jsonify({"status": "ok", "kedaluwarsa_detik": _MEASUREMENT_TTL})


# ── Fungsi bersama: tulis sensor + picu analisis ─────────────────────
def proses_pengukuran(id_pasien: str, bpm: int, spo2: int):
    """Tambahkan baris sensor ke Sheets dan jalankan analisis di background.

    Kembalikan nomor baris (int). Raise Exception jika penulisan ke Sheets gagal.
    """
    baris = sheets.append_sensor(id_pasien, bpm, spo2)
    t = threading.Thread(
        target=analisis_pengukuran,
        args=(id_pasien, baris, bpm, spo2),
        daemon=True,
    )
    t.start()
    return baris


# ── POST /api/sensor-data — terima data dari ESP32 ───────────────────
@app.route("/api/sensor-data", methods=["POST"])
def sensor_data():
    # 1. Periksa API_KEY dari environment
    if not API_KEY:
        return jsonify({"error": "Layanan tidak tersedia."}), 503

    incoming_key = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(
        incoming_key.encode("utf-8"),
        API_KEY.encode("utf-8"),
    ):
        return jsonify({"error": "Tidak diizinkan."}), 401

    # 2. Periksa apakah ada pengukuran aktif yang belum kedaluwarsa
    with _active_lock:
        ap_id      = _active_patient["id_pasien"]
        ap_started = _active_patient["started_at"]

    if ap_id is None or (time.monotonic() - ap_started) > _MEASUREMENT_TTL:
        return jsonify({"error": "Tidak ada pengukuran aktif"}), 409

    id_pasien = ap_id

    # 3. Validasi body JSON
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Body JSON diperlukan."}), 422

    bpm_raw  = body.get("bpm")
    spo2_raw = body.get("spo2")

    # Tolak boolean, string, NaN, infinity
    def _valid_number(v):
        if isinstance(v, bool):
            return False
        if isinstance(v, str):
            return False
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False
        return math.isfinite(f)

    if not _valid_number(bpm_raw) or not _valid_number(spo2_raw):
        return jsonify({"error": "bpm dan spo2 harus berupa angka yang valid."}), 422

    bpm  = round(float(bpm_raw))
    spo2 = round(float(spo2_raw))

    if not (20 <= bpm <= 220):
        return jsonify({"error": "BPM harus antara 20 dan 220."}), 422
    if not (50 <= spo2 <= 100):
        return jsonify({"error": "SpO2 harus antara 50 dan 100."}), 422

    # 4. Rate limit: maks 1 pengukuran per pasien setiap 5 detik
    now_mono = time.monotonic()
    with _rate_lock:
        last = _last_sensor_ts.get(id_pasien, 0.0)
        if (now_mono - last) < 5.0:
            return jsonify({"error": "Terlalu banyak permintaan. Tunggu sebentar."}), 429
        _last_sensor_ts[id_pasien] = now_mono

    # 5. Tulis + analisis via fungsi bersama
    try:
        baris = proses_pengukuran(id_pasien, bpm, spo2)
    except Exception as exc:
        logger.error("sensor_data proses_pengukuran pasien %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal menyimpan data pengukuran."}), 502

    return jsonify({"status": "ok", "baris": baris})


# ── GET /api/config — info mode aplikasi ─────────────────────────────
@app.route("/api/config", methods=["GET"])
def api_config():
    return jsonify({"demo": DEMO_MODE})


# ── POST /api/device-status — terima status dari ESP32 ──────────────
@app.route("/api/device-status", methods=["POST"])
def post_device_status():
    # 1. Periksa API_KEY
    if not API_KEY:
        return jsonify({"error": "Layanan tidak tersedia."}), 503

    incoming_key = request.headers.get("x-api-key", "")
    if not hmac.compare_digest(
        incoming_key.encode("utf-8"),
        API_KEY.encode("utf-8"),
    ):
        return jsonify({"error": "Tidak diizinkan."}), 401

    # 2. Rate limit: maks 10 request per detik (global)
    now_mono = time.monotonic()
    with _dev_status_rl_lock:
        cutoff = now_mono - 1.0
        _dev_status_rl_times[:] = [t for t in _dev_status_rl_times if t > cutoff]
        if len(_dev_status_rl_times) >= 10:
            return jsonify({"error": "Terlalu banyak permintaan."}), 429
        _dev_status_rl_times.append(now_mono)

    # 3. Validasi body
    body = request.get_json(silent=True)
    if body is None:
        return jsonify({"error": "Body JSON diperlukan."}), 422

    kode = str(body.get("kode") or "").strip()
    if kode not in _DEVICE_STATUS_ALLOWLIST:
        return jsonify({"error": "Kode tidak dikenali."}), 422

    # 4. Simpan status
    with _device_status_lock:
        _DEVICE_STATUS["kode"]  = kode
        _DEVICE_STATUS["waktu"] = time.monotonic()

    return jsonify({"status": "ok"})


# ── GET /api/device-status — baca status alat untuk dashboard ────────
@app.route("/api/device-status", methods=["GET"])
def get_device_status():
    id_pasien_param = str(request.args.get("id") or "").strip()

    now_mono = time.monotonic()
    with _device_status_lock:
        kode_raw = _DEVICE_STATUS["kode"]
        waktu    = _DEVICE_STATUS["waktu"]

    alat_terhubung = (kode_raw is not None) and ((now_mono - waktu) <= 20.0)
    umur_detik     = int(now_mono - waktu) if kode_raw is not None else 0

    # Periksa apakah pengukuran aktif untuk id_pasien_param masih berlaku
    with _active_lock:
        ap_id      = _active_patient["id_pasien"]
        ap_started = _active_patient["started_at"]

    pengukuran_aktif = (
        id_pasien_param != "" and
        ap_id == id_pasien_param and
        (now_mono - ap_started) <= _MEASUREMENT_TTL
    )

    # kode hanya diisi jika pengukuran aktif untuk pasien yang diminta
    kode_resp = kode_raw if pengukuran_aktif else None

    return jsonify({
        "alat_terhubung"   : alat_terhubung,
        "kode"             : kode_resp,
        "umur_detik"       : umur_detik,
        "pengukuran_aktif" : pengukuran_aktif,
    })


# ── POST /api/simulate-measurement — simulasi tanpa ESP32 ────────────
@app.route("/api/simulate-measurement", methods=["POST"])
def simulate_measurement():
    if not DEMO_MODE:
        return jsonify({"error": "Not found."}), 404

    data      = request.get_json(silent=True) or {}
    id_pasien = str(data.get("id_pasien") or "").strip()
    skenario  = str(data.get("skenario") or "").strip().lower()

    if not id_pasien:
        return jsonify({"error": "id_pasien diperlukan"}), 400

    # Validasi skenario — "manual" juga diterima
    SKENARIO_VALID = {"normal", "waspada", "tinggi", "manual"}
    if skenario not in SKENARIO_VALID:
        return jsonify({"error": "skenario harus salah satu dari: normal, waspada, tinggi, manual."}), 422

    # Validasi pasien
    try:
        pasien = sheets.get_patient(id_pasien)
    except RuntimeError as exc:
        logger.error("simulate_measurement config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi."}), 503
    except Exception as exc:
        logger.error("simulate_measurement error: %s", exc)
        return jsonify({"error": "Gagal memverifikasi pasien."}), 500

    if not pasien:
        return jsonify({"error": f"Pasien '{id_pasien}' tidak ditemukan."}), 404

    # Tolak pasien di bawah 13 tahun
    try:
        umur = int(pasien.get("umur", 0))
    except (TypeError, ValueError):
        umur = 0
    if umur < 13:
        return jsonify({"error": "Simulasi hanya untuk pasien umur 13 tahun ke atas"}), 422

    # Hasilkan BPM dan SpO₂ dari server berdasarkan skenario
    if skenario == "normal":
        bpm  = secrets.randbelow(37) + 62    # 62–98
        spo2 = secrets.randbelow(4)  + 96    # 96–99
    elif skenario == "waspada":
        bpm  = secrets.randbelow(25) + 101   # 101–125
        spo2 = secrets.randbelow(3)  + 92    # 92–94
    elif skenario == "tinggi":
        bpm  = secrets.randbelow(26) + 135   # 135–160
        spo2 = secrets.randbelow(5)  + 85    # 85–89
    else:
        # skenario == "manual" — baca bpm/spo2 dari body, validasi ketat
        bpm_raw  = data.get("bpm")
        spo2_raw = data.get("spo2")

        def _is_int(v):
            if isinstance(v, bool):
                return False
            if not isinstance(v, int):
                try:
                    v2 = float(v)
                    return v2 == int(v2) and math.isfinite(v2)
                except (TypeError, ValueError):
                    return False
            return True

        errors = {}
        if not _is_int(bpm_raw):
            errors["bpm"] = "BPM harus berupa bilangan bulat."
        else:
            bpm_val = int(float(bpm_raw))
            if not (20 <= bpm_val <= 220):
                errors["bpm"] = "BPM harus antara 20 dan 220."

        if not _is_int(spo2_raw):
            errors["spo2"] = "SpO₂ harus berupa bilangan bulat."
        else:
            spo2_val = int(float(spo2_raw))
            if not (50 <= spo2_val <= 100):
                errors["spo2"] = "SpO₂ harus antara 50 dan 100."

        if errors:
            return jsonify({"error": "Nilai tidak valid.", "fields": errors}), 422

        bpm  = int(float(bpm_raw))
        spo2 = int(float(spo2_raw))

    # Rate limit per-pasien: 1 simulasi per 30 detik
    now_mono = time.monotonic()
    with _sim_patient_lock:
        last_p = _sim_patient_ts.get(id_pasien, 0.0)
        if (now_mono - last_p) < 30.0:
            return jsonify({"error": "Tunggu 30 detik sebelum simulasi berikutnya untuk pasien ini."}), 429
        _sim_patient_ts[id_pasien] = now_mono

    # Rate limit global: maks 10 simulasi dalam 60 detik
    with _sim_global_lock:
        cutoff = now_mono - 60.0
        _sim_global_times[:] = [t for t in _sim_global_times if t > cutoff]
        if len(_sim_global_times) >= 10:
            return jsonify({"error": "Batas simulasi global tercapai. Coba lagi sebentar."}), 429
        _sim_global_times.append(now_mono)

    # Tulis + picu analisis
    try:
        baris = proses_pengukuran(id_pasien, bpm, spo2)
    except Exception as exc:
        logger.error("simulate_measurement proses_pengukuran pasien %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal menyimpan data simulasi."}), 502

    logger.info("simulate_measurement: pasien %s skenario %s baris %d", id_pasien, skenario, baris)
    return jsonify({"status": "ok", "baris": baris, "bpm": bpm, "spo2": spo2})


# ── Analisis pengukuran (background thread) ───────────────────────────
def analisis_pengukuran(id_pasien: str, baris: int, bpm: int, spo2: int):
    """Kirim data pengukuran ke Langflow, lalu pantau status di Sheets.
    Maksimal 2 analisis bersamaan (BoundedSemaphore).
    """
    VALID_STATUS = {"Normal", "Waspada", "Tinggi"}

    def _sanitize(value: str, max_len: int = 100) -> str:
        return " ".join(str(value).split()).strip()[:max_len]

    def _run_langflow(session_id: str, input_value: str) -> bool:
        """Panggil Langflow. Kembalikan True jika berhasil, False jika gagal."""
        if not LANGFLOW_FLOW_ID:
            logger.warning("analisis_pengukuran: LANGFLOW_FLOW_ID tidak dikonfigurasi")
            return False
        url     = f"{LANGFLOW_BASE_URL}/api/v1/run/{LANGFLOW_FLOW_ID}"
        headers = {"Content-Type": "application/json"}
        if LANGFLOW_API_KEY:
            headers["x-api-key"] = LANGFLOW_API_KEY
        payload = {
            "input_value" : input_value,
            "output_type" : "chat",
            "input_type"  : "chat",
            "session_id"  : session_id,
            "tweaks"      : {},
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.error(
                "analisis_pengukuran: Langflow error pasien %s baris %d: %s",
                id_pasien, baris, type(exc).__name__,
            )
            return False

    def _check_status() -> str:
        """Baca baris dari Sheets tanpa cache; kembalikan status atau string kosong."""
        try:
            row = sheets.get_sensor_row_direct(id_pasien, baris)
            if row is None:
                return ""
            return row.get("status", "").strip()
        except Exception as exc:
            logger.error(
                "analisis_pengukuran: gagal baca baris %d pasien %s: %s",
                baris, id_pasien, type(exc).__name__,
            )
            return ""

    with _analisis_sem:
        try:
            # 1. Verifikasi baris sebelum memanggil Langflow
            try:
                baris_data = sheets.get_sensor_row_direct(id_pasien, baris)
            except Exception as exc:
                logger.error(
                    "analisis_pengukuran: gagal baca verifikasi baris %d pasien %s: %s",
                    baris, id_pasien, type(exc).__name__,
                )
                return

            if baris_data is None:
                logger.error(
                    "analisis_pengukuran: baris %d tidak ditemukan untuk pasien %s",
                    baris, id_pasien,
                )
                return

            # Periksa konsistensi id_pasien, bpm, spo2
            try:
                baris_bpm  = round(float(baris_data["bpm"]))
                baris_spo2 = round(float(baris_data["spo2"]))
            except (TypeError, ValueError):
                logger.error(
                    "analisis_pengukuran: nilai baris %d tidak dapat diparse untuk pasien %s",
                    baris, id_pasien,
                )
                return

            if baris_bpm != bpm or baris_spo2 != spo2:
                logger.error(
                    "analisis_pengukuran: data baris %d tidak sesuai untuk pasien %s "
                    "(bpm %d!=%d atau spo2 %d!=%d)",
                    baris, id_pasien, baris_bpm, bpm, baris_spo2, spo2,
                )
                return

            # 2. Ambil data pasien
            try:
                pasien = sheets.get_patient(id_pasien)
            except Exception as exc:
                logger.error(
                    "analisis_pengukuran: gagal ambil pasien %s: %s",
                    id_pasien, type(exc).__name__,
                )
                return
            if not pasien:
                logger.error("analisis_pengukuran: pasien %s tidak ditemukan", id_pasien)
                return

            # 3. Susun input_value — satu field per baris, sanitasi sama seperti /api/chat
            nama_bersih    = _sanitize(pasien["nama"], 100)
            jk_bersih      = _sanitize(pasien["jenis_kelamin"], 50)
            epoch_now      = int(time.time())
            session_id_lf  = f"analisis-{id_pasien}-{baris}-{epoch_now}"

            input_value = (
                f"mode: analisis\n"
                f"id_pasien: {id_pasien}\n"
                f"nama: {nama_bersih}\n"
                f"umur: {pasien['umur']}\n"
                f"jenis_kelamin: {jk_bersih}\n"
                f"bpm: {bpm}\n"
                f"spo2: {spo2}\n"
                f"baris_sheet: {baris}"
            )

            # 4. Panggil Langflow
            _run_langflow(session_id_lf, input_value)

            # 5. Cek status hasil analisis
            status = _check_status()
            if status in VALID_STATUS:
                logger.info(
                    "analisis_pengukuran: selesai pasien %s baris %d status %s",
                    id_pasien, baris, status,
                )
                return

            # 6. Satu kali retry setelah 10 detik
            time.sleep(10)
            _run_langflow(session_id_lf + "-retry", input_value)
            status = _check_status()
            if status in VALID_STATUS:
                logger.info(
                    "analisis_pengukuran: selesai (retry) pasien %s baris %d status %s",
                    id_pasien, baris, status,
                )
            else:
                logger.warning(
                    "analisis tertunda: pasien %s baris %d",
                    id_pasien, baris,
                )

        except Exception as exc:
            logger.error(
                "analisis_pengukuran: exception tak terduga pasien %s baris %d: %s",
                id_pasien, baris, type(exc).__name__,
            )


# ── Select patient — validasi id lalu simpan ke session ──────────────
@app.route("/api/select-patient", methods=["POST"])
def select_patient():
    data      = request.get_json(silent=True) or {}
    id_pasien = str(data.get("id_pasien") or "").strip()

    if not id_pasien:
        return jsonify({"error": "id_pasien diperlukan"}), 400

    try:
        pasien = sheets.get_patient(id_pasien)
    except RuntimeError as exc:
        logger.error("select_patient config error: %s", exc)
        return jsonify({"error": "Layanan data belum dikonfigurasi. Hubungi administrator."}), 503
    except Exception as exc:
        logger.error("select_patient error: %s", exc)
        return jsonify({"error": "Gagal memverifikasi pasien."}), 500

    if not pasien:
        return jsonify({"error": f"Pasien '{id_pasien}' tidak ditemukan."}), 404

    session["id_pasien"] = id_pasien
    return jsonify({"status": "ok", "id_pasien": id_pasien})


_CONVO_ID_RE = re.compile(r"^[0-9a-f]{12}$")


# ── GET /api/chats — daftar percakapan pasien dari session ───────────
@app.route("/api/chats", methods=["GET"])
def list_chats():
    id_pasien = session.get("id_pasien")
    if not id_pasien:
        return jsonify({"error": "Sesi pasien belum dipilih."}), 400
    try:
        convos = sheets.list_conversations(id_pasien)
        return jsonify(convos)
    except Exception as exc:
        logger.error("list_chats error for %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal memuat riwayat percakapan."}), 500


# ── GET /api/chats/<id_percakapan> — pesan satu percakapan ───────────
@app.route("/api/chats/<id_percakapan>", methods=["GET"])
def get_chat(id_percakapan):
    id_pasien = session.get("id_pasien")
    if not id_pasien:
        return jsonify({"error": "Sesi pasien belum dipilih."}), 400
    if not _CONVO_ID_RE.match(id_percakapan):
        return jsonify({"error": "ID percakapan tidak valid."}), 404
    try:
        msgs = sheets.get_conversation(id_pasien, id_percakapan)
    except Exception as exc:
        logger.error("get_chat error %s/%s: %s", id_pasien, id_percakapan, exc)
        return jsonify({"error": "Gagal memuat percakapan."}), 500
    if msgs is None:
        return jsonify({"error": "Percakapan tidak ditemukan."}), 404
    return jsonify(msgs)


# ── Chat — proxy ke Langflow API ─────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    # 1. Ambil id_pasien hanya dari session
    id_pasien = session.get("id_pasien")
    if not id_pasien:
        return jsonify({"error": "Sesi pasien belum dipilih. Silakan pilih pasien terlebih dahulu."}), 400

    try:
        pasien = sheets.get_patient(id_pasien)
    except Exception as exc:
        logger.error("chat get_patient error: %s", exc)
        return jsonify({"error": "Gagal memuat data pasien. Coba beberapa saat lagi."}), 500

    if not pasien:
        return jsonify({"error": "Data pasien tidak ditemukan di server."}), 400

    # 2. Ambil body dan lakukan pemeriksaan konsistensi id_pasien
    data               = request.get_json(silent=True) or {}
    id_pasien_frontend = str(data.get("id_pasien") or "").strip()

    if id_pasien_frontend and id_pasien_frontend != id_pasien:
        # Tab lain telah memilih pasien berbeda — tolak tanpa memanggil Langflow
        return jsonify({
            "error" : "Pasien aktif telah berubah. Muat ulang halaman ini.",
            "code"  : "SESSION_MISMATCH",
        }), 409

    # 2b. Validasi / buat id_percakapan
    id_percakapan_req = str(data.get("id_percakapan") or "").strip()
    if id_percakapan_req:
        if not _CONVO_ID_RE.match(id_percakapan_req):
            return jsonify({"error": "ID percakapan tidak valid."}), 400
        # Pastikan percakapan ini benar-benar milik pasien di session
        try:
            existing = sheets.get_conversation(id_pasien, id_percakapan_req)
        except Exception as exc:
            logger.error("chat get_conversation error: %s", exc)
            return jsonify({"error": "Gagal memverifikasi percakapan."}), 500
        if existing is None:
            return jsonify({"error": "Percakapan tidak ditemukan."}), 404
        id_percakapan = id_percakapan_req
    else:
        id_percakapan = secrets.token_hex(6)  # 12 hex chars

    # 3. Ambil dan sanitasi pesan dari body
    pesan = str(data.get("message") or "")
    pesan = " ".join(pesan.splitlines()).strip()[:500]

    if not pesan:
        return jsonify({"error": "Pesan tidak boleh kosong"}), 400

    # 4. Cek konfigurasi server
    if not LANGFLOW_FLOW_ID:
        return jsonify({"error": "Layanan AI belum dikonfigurasi. Hubungi administrator."}), 503

    # 5. Tanggal hari ini zona Jakarta, nama hari bahasa Indonesia
    _TZ_JKT = timezone(timedelta(hours=7))
    _HARI_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    now_jkt = datetime.now(_TZ_JKT)
    tanggal_sekarang = now_jkt.strftime("%Y-%m-%d") + " (" + _HARI_ID[now_jkt.weekday()] + ")"

    # 5a. Bangun konteks: riwayat 3 baris terbaru
    try:
        sensor_rows = sheets.get_sensor_rows(id_pasien, limit=3)
    except Exception as exc:
        logger.warning("chat: gagal ambil sensor untuk %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal membaca riwayat sensor. Coba beberapa saat lagi."}), 502

    if sensor_rows:
        riwayat_lines = []
        for r in sensor_rows:
            status_str = r["status"] if r["status"] else "(belum dianalisis)"
            riwayat_lines.append(
                f"- {r['timestamp']} | bpm {r['bpm']} | spo2 {r['spo2']} | status: {status_str}"
            )
        riwayat = "\n".join(riwayat_lines)
    else:
        riwayat = "(kosong)"

    # 5b. Pengukuran 48 jam terakhir
    try:
        pengukuran_48j_raw = sheets.pengukuran_48_jam(id_pasien)
    except Exception as exc:
        logger.warning("chat: gagal ambil pengukuran 48 jam untuk %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal membaca data sensor. Coba beberapa saat lagi."}), 502

    # Pastikan label "pengukuran_48_jam:" muncul tepat sekali
    if pengukuran_48j_raw.startswith("pengukuran_48_jam:"):
        pengukuran_48j = pengukuran_48j_raw
    else:
        pengukuran_48j = f"pengukuran_48_jam:\n{pengukuran_48j_raw}\n"

    # 5c. Ringkasan harian 30 hari
    try:
        ringkasan_harian_str = sheets.ringkasan_harian(id_pasien, hari=30)
    except Exception as exc:
        logger.warning("chat: gagal ambil ringkasan harian untuk %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal membaca data sensor. Coba beberapa saat lagi."}), 502

    # 5d. Ringkasan 7 dan 30 hari
    try:
        ringkasan_7 = sheets.ringkasan_sensor(id_pasien, hari=7)
    except Exception as exc:
        logger.warning("chat: gagal ambil ringkasan 7 hari untuk %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal membaca ringkasan sensor. Coba beberapa saat lagi."}), 502

    try:
        ringkasan_30 = sheets.ringkasan_sensor(id_pasien, hari=30)
    except Exception as exc:
        logger.warning("chat: gagal ambil ringkasan 30 hari untuk %s: %s", id_pasien, exc)
        return jsonify({"error": "Gagal membaca ringkasan sensor. Coba beberapa saat lagi."}), 502

    # 5e. Deteksi rentang waktu dari pertanyaan untuk ringkasan_periode
    _pesan_lower = pesan.lower()

    def _deteksi_hari(teks: str) -> int | None:
        """Kembalikan jumlah hari jika ada rentang yang dikenali, atau None."""
        if re.search(r"\btahun\b", teks):
            return -1  # sentinel: di luar jangkauan
        # <angka> bulan: 1 bulan → 30; lebih dari 1 → di luar jangkauan
        m = re.search(r"\b(\d+)\s*bulan\b", teks)
        if m:
            return 30 if int(m.group(1)) == 1 else -1
        # "hari ini" → 1
        if re.search(r"\bhari\s+ini\b", teks):
            return 1
        # "sebulan" / "satu bulan" / "bulan ini" → 30
        if re.search(r"\bsebulan\b|\bsatu\s+bulan\b|\bbulan\s+ini\b", teks):
            return 30
        # "dua minggu" → 14
        if re.search(r"\bdua\s+minggu\b", teks):
            return 14
        # "seminggu" / "satu minggu" / "minggu ini" → 7
        if re.search(r"\bseminggu\b|\bsatu\s+minggu\b|\bminggu\s+ini\b", teks):
            return 7
        # <angka> minggu → 7 × angka
        m = re.search(r"\b(\d+)\s*minggu\b", teks)
        if m:
            return 7 * int(m.group(1))
        # <angka> hari / <angka> hr (termasuk "4 hari belakangan/terakhir")
        m = re.search(r"\b(\d+)\s*(?:hari|hr)\b", teks)
        if m:
            return int(m.group(1))
        return None

    hari_periode = _deteksi_hari(_pesan_lower)

    ringkasan_periode_str: str | None = None
    if hari_periode is not None:
        if hari_periode < 0 or hari_periode > 30:
            ringkasan_periode_str = "ringkasan_periode: (di luar jangkauan, data tersedia 30 hari terakhir)"
        else:
            hari_periode = max(1, hari_periode)
            # Tanggal awal dan akhir yang benar-benar digunakan (calendar days)
            tanggal_akhir = now_jkt.strftime("%Y-%m-%d")
            tanggal_awal  = (now_jkt - timedelta(days=hari_periode - 1)).strftime("%Y-%m-%d")
            try:
                isi_periode = sheets.ringkasan_sensor(id_pasien, hari=hari_periode)
            except Exception as exc:
                logger.warning("chat: gagal ambil ringkasan periode untuk %s: %s", id_pasien, exc)
                return jsonify({"error": "Gagal membaca ringkasan sensor. Coba beberapa saat lagi."}), 502
            label = f"{hari_periode} hari terakhir ({tanggal_awal} sampai {tanggal_akhir})"
            ringkasan_periode_str = f"{label}\n{isi_periode}"

    # 6. Susun input_value — urutan field sesuai spesifikasi:
    #    mode, id_pasien, nama, umur, jenis_kelamin, tanggal_sekarang,
    #    riwayat, pengukuran_48_jam, ringkasan_harian (30 hari),
    #    ringkasan_7_hari, ringkasan_30_hari, [ringkasan_periode], pertanyaan
    nama_bersih = " ".join(str(pasien["nama"]).split()).strip()[:100]
    input_value = (
        f"mode: chat\n"
        f"id_pasien: {id_pasien}\n"
        f"nama: {nama_bersih}\n"
        f"umur: {pasien['umur']}\n"
        f"jenis_kelamin: {pasien['jenis_kelamin']}\n"
        f"tanggal_sekarang: {tanggal_sekarang}\n"
        f"riwayat:\n{riwayat}\n"
        f"{pengukuran_48j}\n"
        f"ringkasan_harian:\n{ringkasan_harian_str}\n"
        f"ringkasan_7_hari: {ringkasan_7}\n"
        f"ringkasan_30_hari: {ringkasan_30}\n"
    )
    if ringkasan_periode_str is not None:
        input_value += f"ringkasan_periode: {ringkasan_periode_str}\n"
    input_value += f"pertanyaan: {pesan}"

    # 7. Build request ke Langflow
    url     = f"{LANGFLOW_BASE_URL}/api/v1/run/{LANGFLOW_FLOW_ID}"
    headers = {"Content-Type": "application/json"}
    if LANGFLOW_API_KEY:
        headers["x-api-key"] = LANGFLOW_API_KEY

    payload = {
        "input_value" : input_value,
        "output_type" : "chat",
        "input_type"  : "chat",
        "session_id"  : id_percakapan,   # satu memori Langflow per percakapan
        "tweaks"      : {},
    }

    # 8. Kirim ke Langflow (log di debug — data kesehatan pasien tidak masuk log produksi)
    logger.debug("Langflow input:\n%s", input_value)
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        logger.error("Langflow connection error")
        return jsonify({"error": "Tidak dapat terhubung ke layanan AI. Coba beberapa saat lagi."}), 502
    except requests.exceptions.Timeout:
        logger.error("Langflow timeout")
        return jsonify({"error": "Layanan AI tidak merespons. Coba beberapa saat lagi."}), 504
    except requests.exceptions.HTTPError as exc:
        logger.error("Langflow HTTP error: %s — %s", exc.response.status_code, exc.response.text)
        return jsonify({"error": "Layanan AI mengembalikan kesalahan. Coba beberapa saat lagi."}), 502

    # 9. Parse respons — iterasi semua outputs[*].outputs[*]
    try:
        body  = resp.json()
        texts = []
        for outer in body.get("outputs", []):
            for inner in outer.get("outputs", []):
                try:
                    text = inner["results"]["message"]["text"]
                    if text and text.strip():
                        texts.append(text.strip())
                except (KeyError, TypeError):
                    continue

        if not texts:
            logger.error("Langflow response contained no non-empty text. Body: %s", body)
            return jsonify({"error": "Layanan AI tidak menghasilkan jawaban. Coba beberapa saat lagi."}), 502

        reply = "\n\n".join(texts)

    except (ValueError, AttributeError) as exc:
        logger.error("Failed to parse Langflow response: %s", exc)
        return jsonify({"error": "Format respons AI tidak dikenali. Hubungi administrator."}), 502

    # 10. Simpan ke riwayat_chat (HANYA setelah Langflow berhasil)
    try:
        sheets.append_messages(id_pasien, id_percakapan, pesan, reply)
    except Exception as exc:
        logger.error("append_messages gagal %s/%s: %s", id_pasien, id_percakapan, exc)
        # Tetap kembalikan balasan — penyimpanan gagal tidak menghentikan respons

    return jsonify({"reply": reply, "id_percakapan": id_percakapan})


# ── POST /api/reanalyze — minta ulang analisis satu baris ─────────────
@app.route("/api/reanalyze", methods=["POST"])
def reanalyze():
    data      = request.get_json(silent=True) or {}
    id_pasien = str(data.get("id_pasien") or "").strip()
    baris_raw = data.get("baris")

    # Validasi baris
    try:
        baris = int(baris_raw)
        if baris < 2:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "baris harus bilangan bulat >= 2."}), 422

    if not id_pasien:
        return jsonify({"error": "id_pasien diperlukan."}), 422

    # Cek keberadaan baris di Sheets dan konsistensi id_pasien
    try:
        row_data = sheets.get_sensor_row_direct(id_pasien, baris)
    except Exception as exc:
        logger.error("reanalyze: gagal baca baris %d: %s", baris, type(exc).__name__)
        return jsonify({"error": "Gagal membaca data pengukuran."}), 502

    if row_data is None:
        return jsonify({"error": "Baris tidak ditemukan atau bukan milik pasien ini."}), 404

    status = str(row_data.get("status", "")).strip()
    if status in ("Normal", "Waspada", "Tinggi"):
        return jsonify({"error": "Baris ini sudah memiliki status analisis."}), 409

    # Rate limit: minimal 30 detik per nomor baris
    now_mono = time.monotonic()
    with _retry_state_lock:
        state = _retry_state.get(baris, {})
        last_manual = state.get("last_manual", 0.0)
        if (now_mono - last_manual) < 30.0:
            return jsonify({"error": "Tunggu sebentar sebelum mencoba lagi."}), 429
        _retry_state.setdefault(baris, {})["last_manual"] = now_mono

    # Cek Langflow health
    try:
        h = requests.get(
            f"{LANGFLOW_BASE_URL}/health", timeout=5,
            headers={"Accept": "application/json"},
        )
        if not h.ok:
            raise requests.exceptions.HTTPError(response=h)
    except Exception:
        return jsonify({"error": "Layanan analisis belum aktif"}), 503

    # Ambil bpm/spo2 untuk diteruskan ke analisis_pengukuran
    try:
        bpm  = round(float(row_data["bpm"]))
        spo2 = round(float(row_data["spo2"]))
    except (TypeError, ValueError):
        return jsonify({"error": "Data baris tidak valid."}), 422

    # Reset hitungan percobaan retry loop agar diprioritaskan
    with _retry_state_lock:
        _retry_state.setdefault(baris, {})["attempts"] = 0
        _retry_state[baris]["next_try"] = 0.0

    t = threading.Thread(
        target=analisis_pengukuran,
        args=(id_pasien, baris, bpm, spo2),
        daemon=True,
    )
    t.start()
    logger.info("reanalyze: memulai analisis pasien %s baris %d", id_pasien, baris)
    return jsonify({"status": "ok"}), 202


# ── Background loop: retry analisis baris yang tertunda ───────────────
def _analysis_retry_loop():
    """Daemon thread yang berjalan setiap 30 detik.

    Pada setiap siklus:
    1. Cek Langflow /health (timeout 3 detik). Jika mati, catat WARNING sekali
       per periode mati lalu skip.
    2. Baca data_sensor tanpa cache. Cari baris yang memenuhi semua syarat:
       - bpm dan spo2 valid (> 0)
       - id_pasien ada di data_pasien
       - status masih kosong
       - timestamp dalam 24 jam terakhir (Asia/Jakarta)
       - percobaan < 6 dan waktu next_try sudah terlewati
    3. Proses maks 3 baris per siklus, dari baris terlama ke terbaru.
    """
    _TZ_JKT = timezone(timedelta(hours=7))
    _was_down = False  # untuk log WARNING sekali saat Langflow mati

    while True:
        time.sleep(30)
        try:
            # 1. Cek Langflow health
            lf_ok = False
            try:
                h = requests.get(
                    f"{LANGFLOW_BASE_URL}/health", timeout=3,
                    headers={"Accept": "application/json"},
                )
                lf_ok = h.ok
            except Exception:
                pass

            if not lf_ok:
                if not _was_down:
                    logger.warning("analysis_retry_loop: Langflow tidak aktif, lewati siklus")
                    _was_down = True
                continue
            _was_down = False  # Langflow aktif kembali

            # 2. Baca semua pasien untuk validasi id_pasien
            try:
                all_patients = sheets.get_patients()  # { id_pasien: {...} }
            except Exception as exc:
                logger.warning("analysis_retry_loop: gagal baca data_pasien: %s", type(exc).__name__)
                continue

            # 3. Baca data_sensor tanpa cache
            try:
                all_rows = sheets._cached_sensor_all(fresh=True)
            except Exception as exc:
                logger.warning("analysis_retry_loop: gagal baca data_sensor: %s", type(exc).__name__)
                continue

            cutoff_dt  = datetime.now(_TZ_JKT) - timedelta(hours=24)
            cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M")
            now_mono   = time.monotonic()

            candidates = []
            for row in all_rows:
                pid = str(row.get("id_pasien", "")).strip()
                if pid not in all_patients:
                    continue
                ts = str(row.get("timestamp", "")).strip()
                if len(ts) < 16 or ts[4] != "-" or ts[7] != "-":
                    continue
                if ts < cutoff_str:
                    continue
                status = str(row.get("status", "")).strip()
                if status:
                    continue
                try:
                    bpm_val  = float(row.get("bpm",  0) or 0)
                    spo2_val = float(row.get("spo2", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if bpm_val <= 0 or spo2_val <= 0:
                    continue
                row_num = int(row.get("baris", 0))
                if row_num < 2:
                    continue

                with _retry_state_lock:
                    state    = _retry_state.get(row_num, {})
                    attempts = state.get("attempts", 0)
                    next_try = state.get("next_try", 0.0)

                if attempts >= 6:
                    continue
                if now_mono < next_try:
                    continue

                candidates.append((row_num, pid, round(bpm_val), round(spo2_val), attempts))

            # Urutkan lama ke baru (nomor baris terkecil dulu), maks 3
            candidates.sort(key=lambda c: c[0])
            for row_num, pid, bpm, spo2, attempts in candidates[:3]:
                delay = _RETRY_DELAYS[min(attempts, len(_RETRY_DELAYS) - 1)]
                with _retry_state_lock:
                    _retry_state.setdefault(row_num, {})["attempts"] = attempts + 1
                    _retry_state[row_num]["next_try"] = now_mono + delay
                logger.info(
                    "analysis_retry_loop: mencoba ulang pasien %s baris %d (percobaan %d)",
                    pid, row_num, attempts + 1,
                )
                t = threading.Thread(
                    target=analisis_pengukuran,
                    args=(pid, row_num, bpm, spo2),
                    daemon=True,
                )
                t.start()

        except Exception as exc:
            logger.error("analysis_retry_loop: exception tak terduga: %s", type(exc).__name__)


# Mulai loop retry saat modul dimuat (daemon — ikut mati saat proses utama mati)
_retry_loop_thread = threading.Thread(target=_analysis_retry_loop, daemon=True, name="analysis-retry")
_retry_loop_thread.start()


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", 5000)),
        debug=debug_mode,
    )
