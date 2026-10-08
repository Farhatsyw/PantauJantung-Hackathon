# PantauJantung

PantauJantung adalah aplikasi pemantauan kesehatan jantung berbasis IoT
yang menggabungkan web Flask, ESP32 + MAX30102, Google Sheets, dan
Langflow.

## Urutan Setup

Ikuti urutan berikut agar konfigurasi antarbagian tidak tertukar:

1.  Siapkan repository dan Python.
2.  Siapkan Google Sheets dari `hackathon.xlsx`.
3.  Buat Google Cloud Service Account untuk Flask.
4.  Download `service-account.json` dan bagikan spreadsheet ke email
    Service Account.
5.  Buat file `.env` untuk Flask.
6.  Jalankan Langflow.
7.  Import `hackathon.json`.
8.  Siapkan Composio dan Google Sheets connection.
9.  Isi Spreadsheet ID pada flow.
10. Siapkan credential model/LLM Agent dan Guardrails sesuai environment
    Langflow.
11. Jalankan dan tes flow di Playground.
12. Salin Flow ID ke `.env` Flask.
13. Jalankan Flask dan tes mode demo.
14. Siapkan ESP32 + MAX30102 jika ingin memakai sensor nyata.

Dokumen detail:

-   [WEB.md](WEB.md) --- Flask, Google Sheets, Service Account, `.env`,
    dan penggunaan web.
-   [LANGFLOW.md](LANGFLOW.md) --- import flow, Composio, Google Sheets,
    Agent, Guardrails, dan Flow ID.
-   [ESP32.md](ESP32.md) --- wiring, Wi-Fi, API key, upload, dan
    pengukuran.

## Arsitektur

``` text
MAX30102
   ↓
 ESP32
   ↓ HTTP
 Flask
   ├── Google Sheets
   └── Langflow
         ├── Guardrails
         ├── Agent
         └── Composio Google Sheets
```

## File Utama

``` text
app.py
sheets.py
judul.py
requirements.txt
.env.example
hackathon.json
hackathon.xlsx
static/
pantaujantung_esp32/pantaujantung_esp32.ino
```

## Credential yang Tidak Boleh Di-commit

Jangan upload credential pribadi ke repository publik:

``` text
.env
service-account.json
secrets.h
```

Selain itu, jangan menaruh API key berikut sebagai nilai asli di file
flow:

``` text
Composio API key
API key model/LLM
Langflow API key
API key ESP32 → Flask
Wi-Fi password
SECRET_KEY Flask
```

Untuk repository publik, `hackathon.json` menggunakan
`YOUR_SPREADSHEET_ID`. Pengguna yang memakai repository harus
menggantinya dengan Spreadsheet ID mereka sendiri.

## Perbedaan Credential

Credential di project ini jangan disamakan:

  -----------------------------------------------------------------------
  Credential                          Dipakai untuk
  ----------------------------------- -----------------------------------
  Google Service Account              Flask → Google Sheets

  Composio API key                    Langflow → Composio

  Google OAuth2 pada Composio         Akses Google Sheets melalui
                                      Composio

  API key model/LLM                   Agent/Guardrails sesuai konfigurasi
                                      Langflow

  Langflow API key                    Flask → endpoint Langflow jika
                                      instance memerlukannya

  `API_KEY`                           ESP32 → Flask
  -----------------------------------------------------------------------

## Mode Demo

Tanpa ESP32, gunakan:

``` env
DEMO_MODE=true
```

Untuk sensor nyata:

``` env
DEMO_MODE=false
```

## Catatan Data

`hackathon.xlsx` harus diperlakukan sebagai template. Jangan memasukkan
data pasien nyata ke repository publik.

PantauJantung adalah prototype pemantauan dan analisis data sensor,
bukan pengganti diagnosis tenaga kesehatan.
