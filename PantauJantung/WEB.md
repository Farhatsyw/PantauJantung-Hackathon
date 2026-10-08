# WEB PantauJantung

Dokumen ini menjelaskan setup aplikasi Flask dan koneksinya ke Google
Sheets serta Langflow.

## 1. Persiapkan Project

``` bash
cd PantauJantung
python -m venv .venv
```

Windows:

``` bash
.venv\Scripts\activate
```

Linux/macOS:

``` bash
source .venv/bin/activate
```

Install dependency:

``` bash
pip install -r requirements.txt
```

## 2. Siapkan Google Sheets

Gunakan `hackathon.xlsx` sebagai template.

Pastikan spreadsheet mempunyai tab dengan nama persis:

``` text
petunjuk
data_pasien
data_sensor
riwayat_chat
referensi
```

Jangan mengubah nama tab yang dipakai aplikasi.

### `data_pasien`

``` text
id_pasien | nama | umur | jenis_kelamin | tanggal_daftar
```

### `data_sensor`

``` text
timestamp | id_pasien | bpm | spo2 | status | catatan_ai
```

### `riwayat_chat`

``` text
id_percakapan | id_pasien | timestamp | role | pesan
```

Gunakan data dummy/anonymized pada file template publik.

## 3. Buat Google Cloud Service Account

Service Account ini digunakan **oleh Flask**, bukan oleh Composio.

1.  Buka Google Cloud Console.
2.  Buat atau pilih project.
3.  Aktifkan Google Sheets API.
4.  Buka IAM & Admin → Service Accounts.
5.  Buat Service Account.
6.  Buka Service Account tersebut.
7.  Pilih Keys → Add Key → Create new key → JSON.
8.  Download JSON.
9.  Rename menjadi:

``` text
service-account.json
```

Letakkan di root project.

**Jangan upload file ini ke GitHub.**

## 4. Bagikan Spreadsheet ke Service Account

Buka `service-account.json`, lalu cari:

``` json
"client_email": "..."
```

Salin email tersebut dan gunakan tombol Share pada Google Sheets.

Berikan akses Editor kepada email Service Account.

Ini adalah akses yang digunakan Flask ketika membaca/menulis
spreadsheet.

## 5. Ambil Spreadsheet ID

Contoh URL:

``` text
https://docs.google.com/spreadsheets/d/1ABCDEF123456/edit
```

Spreadsheet ID adalah:

``` text
1ABCDEF123456
```

Bukan seluruh URL.

### Penting untuk GitHub publik

Jangan memasukkan Spreadsheet ID pribadi ke flow publik.

`hackathon.json` publik menggunakan:

``` text
YOUR_SPREADSHEET_ID
```

Saat menggunakan project sendiri, isi `.env` dengan ID spreadsheet
sendiri:

``` env
SPREADSHEET_ID=SPREADSHEET_ID_KAMU
```

## 6. Buat `.env`

Salin `.env.example` menjadi `.env`.

Contoh konfigurasi:

``` env
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=false
SECRET_KEY=GANTI_DENGAN_SECRET_SENDIRI

LANGFLOW_BASE_URL=http://localhost:7860
LANGFLOW_FLOW_ID=ISI_SETELAH_FLOW_SIAP
LANGFLOW_API_KEY=ISI_JIKA_INSTANCE_LANGFLOW_MEMERLUKANNYA

GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
SPREADSHEET_ID=ISI_SPREADSHEET_ID

API_KEY=BUAT_API_KEY_ESP32_SENDIRI
DEMO_MODE=true
```

Arti credential:

-   `SPREADSHEET_ID` → spreadsheet yang digunakan Flask.
-   `GOOGLE_SERVICE_ACCOUNT_FILE` → file credential Google untuk Flask.
-   `LANGFLOW_FLOW_ID` → ID flow `hackathon` setelah diimport.
-   `LANGFLOW_API_KEY` → credential Langflow jika endpoint yang dipakai
    memerlukannya.
-   `API_KEY` → credential buatan sendiri untuk ESP32 → Flask.

`API_KEY` di sini **bukan** Composio API key dan bukan API key model.

## 7. Siapkan Langflow

Ikuti [LANGFLOW.md](LANGFLOW.md).

Setelah flow berhasil dijalankan di Playground, salin Flow ID ke:

``` env
LANGFLOW_FLOW_ID=FLOW_ID_KAMU
```

## 8. Jalankan Flask

``` bash
python app.py
```

Buka:

``` text
http://localhost:5000
```

## 9. Uji Tanpa ESP32

Gunakan:

``` env
DEMO_MODE=true
```

Restart Flask setelah mengubah `.env`.

Di dashboard, gunakan simulasi pengukuran untuk menguji alur website,
penyimpanan data, status, BPM, SpO2, grafik, dan analisis.

Setelah siap memakai sensor nyata:

``` env
DEMO_MODE=false
```

## 10. Alur Penggunaan Web

1.  Buka halaman utama.
2.  Masukkan data pasien.
3.  Masuk ke dashboard.
4.  Klik **Mulai Pengukuran**.
5.  Gunakan simulasi jika `DEMO_MODE=true`, atau gunakan ESP32 jika mode
    nyata.
6.  Tunggu data pengukuran masuk.
7.  Periksa BPM, SpO2, status, grafik, dan riwayat.
8.  Buka chat untuk bertanya mengenai hasil dan kesehatan jantung.

## 11. Endpoint Sensor

ESP32 mengirim data ke:

``` text
POST /api/sensor-data
```

Backend memeriksa header:

``` text
x-api-key
```

Nilainya harus sama dengan `API_KEY` pada `.env`.

## 12. Troubleshooting

### Google Sheets error

Periksa:

-   `service-account.json` benar.
-   `GOOGLE_SERVICE_ACCOUNT_FILE` benar.
-   Spreadsheet sudah dibagikan ke `client_email`.
-   Akses Service Account adalah Editor.
-   `SPREADSHEET_ID` benar.
-   Nama tab benar.

### Langflow tidak terhubung

Periksa:

``` env
LANGFLOW_BASE_URL
LANGFLOW_FLOW_ID
LANGFLOW_API_KEY
```

Pastikan Langflow aktif dan flow dapat dijalankan dari Playground.

### ESP32 mendapat 401

`API_KEY` ESP32 tidak sama dengan `API_KEY` Flask.

### ESP32 mendapat 503

Backend belum memiliki API key ESP32 yang diperlukan.

## 13. Jangan Commit File Ini

``` text
.env
service-account.json
secrets.h
```
