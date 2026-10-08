"""
sheets.py — Google Sheets data layer untuk PantauJantung.

Tab yang digunakan:
  - data_pasien   : kolom id_pasien | nama | umur | jenis_kelamin | tanggal_daftar
  - data_sensor   : kolom timestamp | id_pasien | bpm | spo2 | status | catatan_ai
  - riwayat_chat  : kolom id_percakapan | id_pasien | timestamp | role | pesan

Timestamp di data_sensor disimpan sebagai teks "YYYY-MM-DD HH:MM".
Timestamp di riwayat_chat disimpan sebagai teks "YYYY-MM-DD HH:MM:SS".
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

# ── OAuth scope minimal ──────────────────────────────────────────────────────
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# ── Cache TTL (detik) ────────────────────────────────────────────────────────
_CACHE_TTL = 10

# ── Internal state ───────────────────────────────────────────────────────────
_lock          = threading.Lock()
_cache_pasien  = None      # list of dicts
_cache_ts      = 0.0       # epoch detik saat cache terakhir diisi

_cache_chat    = {}        # { id_pasien: (list_of_rows, monotonic_ts) }
_chat_lock     = threading.Lock()

_sensor_lock   = threading.Lock()   # lindungi penulisan ke data_sensor

_cache_sensor_rows = None  # list of dicts — semua baris data_sensor (cache global)
_cache_sensor_ts   = 0.0   # epoch monotonic saat cache sensor terakhir diisi
_sensor_read_lock  = threading.Lock()

_gc            = None      # gspread client (lazy)
_spreadsheet   = None      # Spreadsheet object (lazy)


# ── Formula-injection guard ──────────────────────────────────────────────────
def _safe(value: str) -> str:
    """Tambahkan apostrophe di depan jika nilai dimulai dengan = + - @ agar
    Google Sheets tidak menginterpretasinya sebagai formula."""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@"):
        return "'" + s
    return s


# ── Lazy init client ─────────────────────────────────────────────────────────
def _get_sheet(tab: str):
    """Kembalikan worksheet untuk tab yang diminta. Inisialisasi client jika
    belum ada. Raise RuntimeError jika env vars tidak terkonfigurasi."""
    global _gc, _spreadsheet

    if _gc is None:
        key_file      = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        spreadsheet_id = os.getenv("SPREADSHEET_ID", "")

        if not key_file or not spreadsheet_id:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_FILE atau SPREADSHEET_ID belum dikonfigurasi."
            )

        creds        = Credentials.from_service_account_file(key_file, scopes=_SCOPES)
        _gc          = gspread.authorize(creds)
        _spreadsheet = _gc.open_by_key(spreadsheet_id)

    return _spreadsheet.worksheet(tab)


# ── Baca semua pasien (dengan cache) ────────────────────────────────────────
def _fetch_patients_raw() -> list[dict]:
    """Baca tab data_pasien, kembalikan list of dicts.
    Baris dengan id_pasien kosong dilewati."""
    ws   = _get_sheet("data_pasien")
    rows = ws.get_all_records()  # [{id_pasien, nama, umur, jenis_kelamin}, ...]
    result = []
    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if not pid:
            continue
        result.append({
            "id_pasien"    : pid,
            "nama"         : str(row.get("nama", "")).strip(),
            "umur"         : row.get("umur", ""),
            "jenis_kelamin": str(row.get("jenis_kelamin", "")).strip(),
        })
    return result


def _cached_patients() -> list[dict]:
    global _cache_pasien, _cache_ts
    now = time.monotonic()
    if _cache_pasien is None or (now - _cache_ts) > _CACHE_TTL:
        _cache_pasien = _fetch_patients_raw()
        _cache_ts     = now
    return _cache_pasien


def _invalidate_patient_cache():
    global _cache_pasien, _cache_ts
    _cache_pasien = None
    _cache_ts     = 0.0


# ── Public API ───────────────────────────────────────────────────────────────

def get_patients() -> dict[str, dict]:
    """Kembalikan semua pasien sebagai dict { id_pasien: {...} }."""
    rows = _cached_patients()
    return {r["id_pasien"]: r for r in rows}


def get_patient(id_pasien: str) -> dict | None:
    """Kembalikan data satu pasien, atau None jika tidak ditemukan."""
    patients = get_patients()
    return patients.get(str(id_pasien).strip())


def add_patient(nama: str, umur: int, jenis_kelamin: str) -> str:
    """Tambahkan pasien baru ke tab data_pasien.
    Gunakan threading.Lock untuk mencegah duplicate ID.
    Kembalikan id_pasien baru (string, contoh 'P003')."""
    with _lock:
        # Invalidasi cache agar kita baca data terbaru dari sheet
        _invalidate_patient_cache()
        rows = _fetch_patients_raw()

        # Hitung ID berikutnya
        max_num = 0
        for row in rows:
            pid = row["id_pasien"]
            if pid.startswith("P") and pid[1:].isdigit():
                max_num = max(max_num, int(pid[1:]))
        new_id = f"P{max_num + 1:03d}"

        tz_jakarta    = timezone(timedelta(hours=7))
        tanggal_daftar = datetime.now(tz_jakarta).strftime("%Y-%m-%d")

        ws = _get_sheet("data_pasien")
        ws.append_row(
            [_safe(new_id), _safe(nama), int(umur), _safe(jenis_kelamin), tanggal_daftar],
            value_input_option="RAW",
        )

        # Invalidasi agar get_patients() berikutnya membaca dari sheet
        _invalidate_patient_cache()
        logger.info("add_patient: pasien baru %s (%s) ditambahkan.", new_id, nama)
        return new_id


def _cached_sensor_all(fresh: bool = False) -> list[dict]:
    """Kembalikan semua baris data_sensor dari cache (TTL = _CACHE_TTL detik).

    Setiap item adalah dict gspread get_all_records() dengan tambahan key "baris"
    (nomor baris 1-based di spreadsheet, header = baris 1, data mulai baris 2).

    fresh=True memaksa pembacaan ulang tanpa memedulikan TTL.
    """
    global _cache_sensor_rows, _cache_sensor_ts
    now = time.monotonic()
    with _sensor_read_lock:
        if not fresh and _cache_sensor_rows is not None and (now - _cache_sensor_ts) <= _CACHE_TTL:
            return _cache_sensor_rows
        ws = _get_sheet("data_sensor")
        # get_all_values() mengembalikan list-of-lists; baris 0 = header
        all_values = ws.get_all_values()
        if not all_values:
            _cache_sensor_rows = []
            _cache_sensor_ts   = time.monotonic()
            return _cache_sensor_rows
        headers = [str(h).strip() for h in all_values[0]]
        rows = []
        for idx, vals in enumerate(all_values[1:], start=2):   # baris ke-idx (1-based)
            row = {headers[i]: vals[i] if i < len(vals) else "" for i in range(len(headers))}
            row["baris"] = idx
            rows.append(row)
        _cache_sensor_rows = rows
        _cache_sensor_ts   = time.monotonic()
        return _cache_sensor_rows


def _invalidate_sensor_cache():
    global _cache_sensor_rows, _cache_sensor_ts
    with _sensor_read_lock:
        _cache_sensor_rows = None
        _cache_sensor_ts   = 0.0


def get_sensor_rows(id_pasien: str, limit: int = 50, fresh: bool = False) -> list[dict]:
    """Baca riwayat sensor untuk id_pasien dari tab data_sensor.

    Kolom yang diharapkan: timestamp | id_pasien | bpm | spo2 | status | catatan_ai

    - Diurutkan descending berdasarkan timestamp (string compare "YYYY-MM-DD HH:MM").
    - Baris dengan timestamp malformed dilewati (log warning).
    - Kembalikan maksimal `limit` baris terbaru.
    - fresh=True memaksa pembacaan ulang (bypass TTL cache).
    """
    rows   = _cached_sensor_all(fresh=fresh)
    target = str(id_pasien).strip()
    result = []

    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if pid != target:
            continue

        ts = str(row.get("timestamp", "")).strip()
        # Validasi format minimal: panjang 16, karakter ke-4 dan ke-7 adalah '-'
        if len(ts) < 16 or ts[4] != "-" or ts[7] != "-":
            logger.warning(
                "get_sensor_rows: skip baris dengan timestamp malformed '%s' untuk %s",
                ts, target,
            )
            continue

        bpm        = row.get("bpm", "")
        spo2       = row.get("spo2", "")
        status     = str(row.get("status",     "")).strip()
        catatan_ai = str(row.get("catatan_ai", "")).strip()
        baris      = int(row.get("baris", 0))

        result.append({
            "timestamp" : ts,
            "bpm"       : bpm,
            "spo2"      : spo2,
            "status"    : status,
            "catatan_ai": catatan_ai,
            "baris"     : baris,
        })

    # Urutkan descending berdasarkan nomor baris (bukan timestamp) agar urutan
    # penulisan fisik ke sheet menjadi sumber kebenaran, bukan string waktu per-menit.
    result.sort(key=lambda r: r["baris"], reverse=True)

    return result[:limit]


def ringkasan_harian(id_pasien: str, hari: int = 14) -> str:
    """Ringkasan per hari selama `hari` hari terakhir (termasuk hari ini).

    "N hari terakhir" = dari tanggal (hari_ini - N + 1) sampai hari_ini, inklusif
    (calendar days zona Asia/Jakarta).

    Hanya baris milik `id_pasien` (perbandingan .strip()).
    Menggunakan _cached_sensor_all() — tanpa panggilan Sheets tambahan.

    Format satu baris per hari yang punya data, terbaru dulu:
      - YYYY-MM-DD | jumlah <n> | detak rata-rata <x> (<min>-<maks>) |
        oksigen rata-rata <y> (<min>-<maks>) |
        status: Normal <p>, Waspada <q>, Tinggi <r>, belum dianalisis <s>

    Hari tanpa data tidak ditulis. Jika tidak ada data sama sekali:
      "ringkasan_harian: (kosong)"
    """
    now_jkt  = datetime.now(_TZ_JKT)
    target   = str(id_pasien).strip()

    # Tentukan rentang tanggal yang valid (calendar days)
    date_end   = now_jkt.strftime("%Y-%m-%d")
    date_start = (now_jkt - timedelta(days=hari - 1)).strftime("%Y-%m-%d")

    rows = _cached_sensor_all()

    # ── 1. Filter id_pasien PERTAMA, sebelum filter tanggal ──────────
    per_day: dict[str, list[dict]] = {}
    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if pid != target:           # isolasi pasien — WAJIB sebelum filter lain
            continue
        ts = str(row.get("timestamp", "")).strip()
        if len(ts) < 10 or ts[4] != "-" or ts[7] != "-":
            continue
        date_str = ts[:10]          # "YYYY-MM-DD"
        # ── 2. Filter tanggal (calendar days inklusif) ──────────────
        if date_str < date_start or date_str > date_end:
            continue
        try:
            bpm_val  = float(row.get("bpm",  0) or 0)
            spo2_val = float(row.get("spo2", 0) or 0)
        except (TypeError, ValueError):
            continue
        if bpm_val <= 0 or spo2_val <= 0:
            continue
        per_day.setdefault(date_str, []).append({
            "bpm"   : bpm_val,
            "spo2"  : spo2_val,
            "status": str(row.get("status", "")).strip(),
        })

    total_baris = sum(len(v) for v in per_day.values())
    logger.info(
        "ringkasan_harian: id_pasien=%s rentang=%s..%s hari=%d baris=%d",
        target, date_start, date_end, hari, total_baris,
    )

    # Iterasi dari hari ini mundur, tulis baris per hari
    lines = []
    for d in range(hari):
        day_dt   = now_jkt - timedelta(days=d)
        date_str = day_dt.strftime("%Y-%m-%d")
        day_rows = per_day.get(date_str)
        if not day_rows:
            continue
        n         = len(day_rows)
        bpm_vals  = [r["bpm"]  for r in day_rows]
        spo2_vals = [r["spo2"] for r in day_rows]
        bpm_avg   = round(sum(bpm_vals)  / n)
        bpm_min   = round(min(bpm_vals))
        bpm_max   = round(max(bpm_vals))
        spo2_avg  = round(sum(spo2_vals) / n)
        spo2_min  = round(min(spo2_vals))
        spo2_max  = round(max(spo2_vals))
        cnt_n  = sum(1 for r in day_rows if r["status"] == "Normal")
        cnt_w  = sum(1 for r in day_rows if r["status"] == "Waspada")
        cnt_t  = sum(1 for r in day_rows if r["status"] == "Tinggi")
        cnt_k  = sum(1 for r in day_rows if not r["status"])
        lines.append(
            f"- {date_str} | jumlah {n} | "
            f"detak rata-rata {bpm_avg} ({bpm_min}-{bpm_max}) | "
            f"oksigen rata-rata {spo2_avg} ({spo2_min}-{spo2_max}) | "
            f"status: Normal {cnt_n}, Waspada {cnt_w}, Tinggi {cnt_t}, "
            f"belum dianalisis {cnt_k}"
        )

    if not lines:
        return "ringkasan_harian: (kosong)"
    return "\n".join(lines)


def pengukuran_48_jam(id_pasien: str) -> str:
    """Semua pengukuran milik id_pasien dalam 48 jam terakhir, terbaru dulu.

    Hanya baris milik `id_pasien` (perbandingan .strip()).
    Cutoff = waktu sekarang (Asia/Jakarta) dikurangi 48 jam, perbandingan
    string "YYYY-MM-DD HH:MM" yang sortable.

    Maksimal 40 baris. Jika lebih: tampilkan 40 terbaru + baris
      "(dipotong: 40 dari <n>)"
    Jika kosong: kembalikan "pengukuran_48_jam: (kosong)"

    Format per baris:
      - YYYY-MM-DD HH:MM | detak <bpm> | oksigen <spo2> | status: <status atau belum dianalisis>
    """
    now_jkt    = datetime.now(_TZ_JKT)
    cutoff_dt  = now_jkt - timedelta(hours=48)
    cutoff_str = cutoff_dt.strftime("%Y-%m-%d %H:%M")
    target     = str(id_pasien).strip()

    rows = _cached_sensor_all()

    # ── 1. Filter id_pasien PERTAMA ──────────────────────────────────
    valid = []
    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if pid != target:
            continue
        ts = str(row.get("timestamp", "")).strip()
        if len(ts) < 16 or ts[4] != "-" or ts[7] != "-":
            continue
        # ── 2. Filter waktu ─────────────────────────────────────────
        if ts < cutoff_str:
            continue
        try:
            bpm_val  = float(row.get("bpm",  0) or 0)
            spo2_val = float(row.get("spo2", 0) or 0)
        except (TypeError, ValueError):
            continue
        if bpm_val <= 0 or spo2_val <= 0:
            continue
        valid.append({
            "timestamp": ts,
            "bpm"      : round(bpm_val),
            "spo2"     : round(spo2_val),
            "status"   : str(row.get("status", "")).strip(),
            "baris"    : int(row.get("baris", 0)),
        })

    if not valid:
        logger.info(
            "pengukuran_48_jam: id_pasien=%s cutoff=%s baris=0",
            target, cutoff_str,
        )
        return "pengukuran_48_jam: (kosong)"

    # Urutkan descending (terbaru dulu) berdasarkan nomor baris
    valid.sort(key=lambda r: r["baris"], reverse=True)
    total = len(valid)

    logger.info(
        "pengukuran_48_jam: id_pasien=%s cutoff=%s baris=%d (ditampilkan %d)",
        target, cutoff_str, total, min(total, 40),
    )

    displayed = valid[:40]
    lines = []
    for r in displayed:
        status_str = r["status"] if r["status"] else "belum dianalisis"
        lines.append(
            f"- {r['timestamp']} | detak {r['bpm']} | oksigen {r['spo2']} | "
            f"status: {status_str}"
        )
    if total > 40:
        lines.append(f"(dipotong: 40 dari {total})")
    return "\n".join(lines)


def ringkasan_sensor(id_pasien: str, hari: int = 30) -> str:
    """Baca data_sensor via cache dan kembalikan ringkasan teks satu baris.

    "N hari terakhir" = dari tanggal (hari_ini - N + 1) sampai hari_ini, inklusif
    (calendar days zona Asia/Jakarta).

    Hanya baris milik `id_pasien` (perbandingan .strip()).

    Format:
      jumlah <n> | bpm rata-rata <x> (terendah <a>, tertinggi <b>) |
      spo2 rata-rata <y> (terendah <c>) |
      status: Normal <p>, Waspada <q>, Tinggi <r>, belum dianalisis <s> |
      kecenderungan bpm: <naik/turun/stabil/data belum cukup> |
      kecenderungan spo2: <naik/turun/stabil/data belum cukup>

    Jika tidak ada data dalam periode, kembalikan "(kosong)".
    """
    now_jkt    = datetime.now(_TZ_JKT)
    date_end   = now_jkt.strftime("%Y-%m-%d")
    date_start = (now_jkt - timedelta(days=hari - 1)).strftime("%Y-%m-%d")
    target     = str(id_pasien).strip()

    rows = _cached_sensor_all()

    # ── 1. Filter id_pasien PERTAMA, sebelum filter tanggal ──────────
    valid = []
    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if pid != target:           # isolasi pasien — WAJIB sebelum filter lain
            continue
        ts = str(row.get("timestamp", "")).strip()
        if len(ts) < 16 or ts[4] != "-" or ts[7] != "-":
            continue
        date_str = ts[:10]
        # ── 2. Filter tanggal (calendar days inklusif) ──────────────
        if date_str < date_start or date_str > date_end:
            continue
        try:
            bpm_val  = float(row.get("bpm",  0) or 0)
            spo2_val = float(row.get("spo2", 0) or 0)
        except (TypeError, ValueError):
            continue
        if bpm_val <= 0 or spo2_val <= 0:
            continue
        valid.append({
            "timestamp": ts,
            "bpm"      : bpm_val,
            "spo2"     : spo2_val,
            "status"   : str(row.get("status", "")).strip(),
        })

    logger.info(
        "ringkasan_sensor: id_pasien=%s rentang=%s..%s hari=%d baris=%d",
        target, date_start, date_end, hari, len(valid),
    )

    if not valid:
        return "(kosong)"

    n = len(valid)
    bpm_vals  = [r["bpm"]  for r in valid]
    spo2_vals = [r["spo2"] for r in valid]

    bpm_avg  = round(sum(bpm_vals)  / n)
    bpm_min  = round(min(bpm_vals))
    bpm_max  = round(max(bpm_vals))
    spo2_avg = round(sum(spo2_vals) / n)
    spo2_min = round(min(spo2_vals))

    cnt_normal   = sum(1 for r in valid if r["status"] == "Normal")
    cnt_waspada  = sum(1 for r in valid if r["status"] == "Waspada")
    cnt_tinggi   = sum(1 for r in valid if r["status"] == "Tinggi")
    cnt_kosong   = sum(1 for r in valid if not r["status"])

    # Kecenderungan: urutkan lama→baru, bagi dua paruh, bandingkan rata-rata
    ordered = sorted(valid, key=lambda r: r["timestamp"])

    def _tren(vals: list[float], threshold: float) -> str:
        if len(vals) < 4:
            return "data belum cukup"
        mid   = len(vals) // 2
        lama  = sum(vals[:mid])  / mid
        baru  = sum(vals[mid:])  / (len(vals) - mid)
        delta = baru - lama
        if delta > threshold:
            return "naik"
        if delta < -threshold:
            return "turun"
        return "stabil"

    tren_bpm  = _tren([r["bpm"]  for r in ordered], 5.0)
    tren_spo2 = _tren([r["spo2"] for r in ordered], 2.0)

    return (
        f"jumlah {n} | "
        f"bpm rata-rata {bpm_avg} (terendah {bpm_min}, tertinggi {bpm_max}) | "
        f"spo2 rata-rata {spo2_avg} (terendah {spo2_min}) | "
        f"status: Normal {cnt_normal}, Waspada {cnt_waspada}, Tinggi {cnt_tinggi}, "
        f"belum dianalisis {cnt_kosong} | "
        f"kecenderungan bpm: {tren_bpm} | "
        f"kecenderungan spo2: {tren_spo2}"
    )


# ── Jakarta timezone helper ───────────────────────────────────────────────────
_TZ_JKT = timezone(timedelta(hours=7))


def _now_jkt_str() -> str:
    """Kembalikan timestamp sekarang zona Asia/Jakarta sebagai 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.now(_TZ_JKT).strftime("%Y-%m-%d %H:%M:%S")


# ── Invalidate riwayat_chat cache untuk satu pasien ──────────────────────────
def _invalidate_chat_cache(id_pasien: str):
    with _chat_lock:
        _cache_chat.pop(id_pasien, None)


# ── Baca semua baris riwayat_chat untuk satu pasien (dengan cache) ────────────
def _cached_chat_rows(id_pasien: str) -> list[dict]:
    target = str(id_pasien).strip()
    now    = time.monotonic()

    with _chat_lock:
        entry = _cache_chat.get(target)
        if entry and (now - entry[1]) <= _CACHE_TTL:
            return entry[0]

    ws   = _get_sheet("riwayat_chat")
    rows = ws.get_all_records()

    result = []
    for row in rows:
        pid = str(row.get("id_pasien", "")).strip()
        if pid != target:
            continue
        result.append({
            "id_percakapan": str(row.get("id_percakapan", "")).strip(),
            "timestamp"    : str(row.get("timestamp", "")).strip(),
            "role"         : str(row.get("role", "")).strip(),
            "pesan"        : str(row.get("pesan", "")),
        })

    with _chat_lock:
        _cache_chat[target] = (result, time.monotonic())

    return result


# ── Ringkasan judul percakapan dari pertanyaan pertama user ──────────────────
import re as _re
import difflib as _difflib  # noqa: F401 (kept for any caller that imported it)
from judul import buat_judul as _buat_judul  # noqa: E402

# ── Public: list_conversations ────────────────────────────────────────────────
def list_conversations(id_pasien: str) -> list[dict]:
    """Daftar percakapan milik id_pasien, terbaru dulu.

    Tiap item:
      id_percakapan  – str
      judul          – ringkasan singkat dari pertanyaan pertama user
      waktu_terakhir – timestamp baris terakhir percakapan itu
    """
    rows = _cached_chat_rows(id_pasien)

    # Kelompokkan per id_percakapan
    # Kunci tambahan sementara: "pesan_user" (pesan user pertama) dan
    # "balasan_ai" (teks balasan AI pertama setelah pesan user pertama).
    convos: dict[str, dict] = {}
    for row in rows:
        cid = row["id_percakapan"]
        if not cid:
            continue
        if cid not in convos:
            convos[cid] = {
                "id_percakapan": cid,
                "judul": "",
                "waktu_terakhir": "",
                "_pesan_user": "",
                "_balasan_ai": "",
            }
        # Pesan user pertama
        if not convos[cid]["_pesan_user"] and row["role"] == "user":
            convos[cid]["_pesan_user"] = row["pesan"]
        # Balasan AI pertama setelah pesan user pertama
        if (convos[cid]["_pesan_user"]
                and not convos[cid]["_balasan_ai"]
                and row["role"] in ("ai", "assistant")):
            convos[cid]["_balasan_ai"] = row["pesan"]
        # Waktu terakhir: ambil timestamp terbesar (string YYYY-MM-DD HH:MM:SS sortable)
        if row["timestamp"] > convos[cid]["waktu_terakhir"]:
            convos[cid]["waktu_terakhir"] = row["timestamp"]

    # Bangun judul setelah semua baris diproses
    for cid, c in convos.items():
        if c["_pesan_user"]:
            c["judul"] = _buat_judul(
                c["_pesan_user"],
                c["_balasan_ai"] or None,
            )
        del c["_pesan_user"]
        del c["_balasan_ai"]

    # Urutkan descending berdasarkan waktu_terakhir
    result = sorted(convos.values(), key=lambda c: c["waktu_terakhir"], reverse=True)
    return result


# ── Public: get_conversation ──────────────────────────────────────────────────
def get_conversation(id_pasien: str, id_percakapan: str) -> list[dict] | None:
    """Kembalikan semua pesan percakapan, urut waktu (ascending).

    Kembalikan None jika id_percakapan tidak ada ATAU bukan milik id_pasien.
    """
    rows = _cached_chat_rows(id_pasien)
    msgs = [r for r in rows if r["id_percakapan"] == id_percakapan]
    if not msgs:
        return None
    msgs.sort(key=lambda r: r["timestamp"])
    return msgs


# ── Public: append_sensor ────────────────────────────────────────────────────
def append_sensor(id_pasien: str, bpm: int, spo2: int) -> int:
    """Tambahkan satu baris pengukuran ke tab data_sensor.

    Kolom: timestamp | id_pasien | bpm | spo2 | status | catatan_ai
    status dan catatan_ai dikosongkan; timestamp zona Asia/Jakarta "YYYY-MM-DD HH:MM".
    Kembalikan nomor baris (1-based) dari range yang dikembalikan gspread.
    Raise Exception jika gagal menulis.
    """
    ts = datetime.now(_TZ_JKT).strftime("%Y-%m-%d %H:%M")
    row = [ts, _safe(str(id_pasien)), int(bpm), int(spo2), "", ""]

    with _sensor_lock:
        ws = _get_sheet("data_sensor")
        result = ws.append_rows([row], value_input_option="RAW")

    # Parse nomor baris dari range pembaruan yang dikembalikan gspread.
    # Contoh updatedRange: "data_sensor!A42:F42"
    try:
        updated_range = result.get("updates", {}).get("updatedRange", "")
        # Ambil bagian setelah "!" lalu parse baris akhir dari range "A42:F42"
        range_part = updated_range.split("!")[-1]         # "A42:F42"
        end_cell   = range_part.split(":")[-1]            # "F42"
        row_number = int("".join(c for c in end_cell if c.isdigit()))
    except Exception:
        row_number = 0

    logger.info("append_sensor: baris %d untuk pasien %s", row_number, id_pasien)

    # Invalidasi cache sensor agar get_sensor_rows dan ringkasan_sensor
    # membaca data terbaru pada panggilan berikutnya.
    _invalidate_sensor_cache()

    return row_number


def get_sensor_row_direct(id_pasien: str, row_number: int) -> dict | None:
    """Baca satu baris dari data_sensor berdasarkan nomor baris (tanpa cache).

    Kembalikan dict dengan kunci timestamp, id_pasien, bpm, spo2, status, catatan_ai,
    atau None jika baris tidak ada / id_pasien tidak cocok.
    """
    ws = _get_sheet("data_sensor")
    # Ambil semua nilai baris — get() menerima range A1-notation
    values = ws.row_values(row_number)
    if not values:
        return None

    # Petakan posisi kolom: timestamp(0) id_pasien(1) bpm(2) spo2(3) status(4) catatan_ai(5)
    def _col(idx):
        return str(values[idx]).strip() if idx < len(values) else ""

    pid = _col(1)
    if pid != str(id_pasien).strip():
        return None

    return {
        "timestamp" : _col(0),
        "id_pasien" : pid,
        "bpm"       : _col(2),
        "spo2"      : _col(3),
        "status"    : _col(4),
        "catatan_ai": _col(5),
    }


# ── Public: append_messages ───────────────────────────────────────────────────
def append_messages(
    id_pasien: str,
    id_percakapan: str,
    pesan_user: str,
    balasan_ai: str,
) -> None:
    """Tulis pesan user dan balasan AI ke tab riwayat_chat dalam SATU append_rows.

    - Potong teks ke 4000 karakter.
    - Teks yang diawali = + - @ diberi apostrof.
    - Hapus cache riwayat_chat setelah menulis.
    """
    MAX = 4000
    pesan_user = str(pesan_user)[:MAX]
    balasan_ai = str(balasan_ai)[:MAX]

    ts       = _now_jkt_str()
    safe_pid = _safe(id_pasien)
    safe_cid = _safe(id_percakapan)

    row_user = [safe_cid, safe_pid, ts, "user", _safe(pesan_user)]
    row_ai   = [safe_cid, safe_pid, ts, "ai",   _safe(balasan_ai)]

    ws = _get_sheet("riwayat_chat")
    ws.append_rows([row_user, row_ai], value_input_option="RAW")

    _invalidate_chat_cache(id_pasien)
