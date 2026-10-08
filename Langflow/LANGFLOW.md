# Langflow PantauJantung

Dokumen ini khusus untuk flow `hackathon.json` yang digunakan
PantauJantung.

## Urutan Setup

``` text
1. Jalankan Langflow
2. Import hackathon.json
3. Siapkan Composio API key
4. Siapkan koneksi Google Sheets melalui Composio OAuth2
5. Isi Spreadsheet ID
6. Periksa Agent
7. Siapkan credential model/LLM bila diperlukan
8. Periksa Guardrails dan credential modelnya bila diperlukan
9. Tes flow di Playground
10. Ambil Flow ID
11. Masukkan Flow ID ke .env Flask
12. Tes dari website
```

## 1. Import Flow

Import:

``` text
hackathon.json
```

Flow berisi komponen:

``` text
Chat Input
Chat Output
Agent
Guardrails
Composio Google Sheets
Prompt Template (Pesan Tolak)
```

Gunakan file flow publik yang sudah mengganti Spreadsheet ID pribadi
menjadi:

``` text
YOUR_SPREADSHEET_ID
```

## 2. Composio --- WAJIB Dikonfigurasi

Flow memiliki node:

``` text
Composio Google Sheets API Component
```

Pada node tersebut ada field:

``` text
Composio API Key
```

Di export flow, field tersebut bernama `api_key` dan nilainya
direferensikan sebagai:

``` text
COMPOSIO_API_KEY
```

Jadi `COMPOSIO_API_KEY` adalah **credential yang harus disiapkan
sendiri**. Itu bukan placeholder Spreadsheet ID.

### Yang perlu disiapkan

Kamu membutuhkan akun/project Composio dan **Project API Key** milik
sendiri.

API key tersebut jangan ditulis permanen di `hackathon.json` atau
di-commit ke GitHub.

### Memasukkan Composio API Key

Karena component pada flow menggunakan:

``` text
COMPOSIO_API_KEY
```

konfigurasikan secret/global variable dengan nama tersebut pada
environment Langflow yang kamu gunakan, atau isi field **Composio API
Key** pada component jika UI Langflow menampilkannya sebagai input.

Nilai yang dimasukkan harus berupa API key Composio milik pengguna
sendiri.

## 3. Google Sheets pada Composio

Node Composio menggunakan:

``` text
Auth Mode: OAUTH2
Tool Mode: true
```

Ini berbeda dari Google Service Account yang dipakai Flask.

### Perbedaannya

``` text
Flask
  ↓
Google Service Account
  ↓
Google Sheets
```

sedangkan:

``` text
Langflow
  ↓
Composio API Key
  ↓
Composio
  ↓ OAuth2
Google Sheets
```

Jadi meskipun spreadsheet yang digunakan sama, credential-nya tidak
sama.

### Authorization Google

Setelah Composio API key sudah valid, lakukan authorization Google
Sheets pada koneksi Composio sesuai UI/environment Composio yang
digunakan.

Akun Google yang di-authorize harus mempunyai akses ke spreadsheet
target.

## 4. Spreadsheet ID

Pada node Google Sheets Composio terdapat field:

``` text
Spreadsheetid
```

Flow publik berisi:

``` text
YOUR_SPREADSHEET_ID
```

Ganti dengan ID spreadsheet milik pengguna.

Contoh:

``` text
https://docs.google.com/spreadsheets/d/1ABCDEF123456/edit
```

ID-nya:

``` text
1ABCDEF123456
```

### Spreadsheet ID juga ada di Agent

System Prompt Agent berisi informasi spreadsheet dan pada flow publik
juga menggunakan:

``` text
YOUR_SPREADSHEET_ID
```

Jika setelah import bagian tersebut masih berupa placeholder, ganti
dengan ID spreadsheet yang sama.

Dengan demikian ada dua lokasi pada flow yang perlu diperhatikan:

``` text
1. Google Sheets component → Spreadsheet ID
2. Agent System Prompt → Spreadsheet ID
```

Keduanya harus mengarah ke spreadsheet yang sama.

## 5. Agent

Agent pada flow menggunakan:

``` text
Model: daily
Provider: OpenAI Compatible
```

Konfigurasi ini adalah yang tercantum pada flow. File flow **tidak
menyatakan provider layanan tertentu di luar label
`OpenAI Compatible`**, sehingga dokumentasi ini tidak menetapkan
provider tertentu.

### API Key Agent

Pada Agent ada field:

``` text
API Key
```

Informasi field tersebut pada flow menyebut bahwa field ini dapat
meng-override credential provider yang sudah dikonfigurasi dan dapat
dibiarkan kosong jika API key provider sudah dikonfigurasi.

Jadi:

-   gunakan credential provider OpenAI-compatible yang sesuai dengan
    environment Langflow kamu;
-   jika provider sudah dikonfigurasi secara global, field API Key Agent
    dapat menggunakan credential tersebut;
-   jika diperlukan, isi field API Key dengan key milik sendiri;
-   jangan memasukkan key pribadi ke `hackathon.json` publik.

**Jangan menebak provider hanya dari nama model `daily`.** File flow
tidak memberikan informasi provider spesifik yang dapat dipastikan.

## 6. Guardrails

Flow juga memiliki node Guardrails.

Konfigurasi yang tercantum pada flow antara lain:

``` text
Checking Method: Rules + AI
Block Threshold: 0.75
Heuristic Threshold: 0.7
Fail Closed: true
Medium Risk Action: block
Redaction Mode: mask
Sanitize Threshold: 0.35
Scan Encoded Payloads: true
```

Guardrails mencakup pemeriksaan untuk konteks seperti:

-   PII
-   Tokens/Passwords
-   Jailbreak
-   Malicious Code
-   Prompt Injection
-   Offensive Content

Node Guardrails juga memiliki field API Key dan model `daily` dengan
provider `OpenAI Compatible`. Jika environment Langflow memerlukan
credential untuk pemeriksaan AI tersebut, gunakan credential model yang
sesuai.

## 7. Agent dan Google Sheets

Agent menggunakan tool Google Sheets dari Composio.

Pastikan component Google Sheets terhubung ke input tools pada Agent dan
tidak menghasilkan error credential.

## 8. Tes Flow

Sebelum menghubungkan Flask, tes flow langsung dari Playground.

Contoh pertanyaan:

``` text
Apa yang perlu diperhatikan saat mengukur denyut jantung?
```

Kemudian tes pertanyaan yang membutuhkan data pasien/pengukuran.

Pastikan:

-   Agent memberikan respons.
-   Composio dapat mengakses Google Sheets.
-   Spreadsheet ID benar.
-   OAuth2 Google berhasil.
-   Guardrails tidak error.
-   Tidak ada error API key.

### Jika muncul error Composio

Periksa:

``` text
COMPOSIO_API_KEY
```

dan koneksi Google OAuth2.

### Jika muncul error model/API key

Periksa credential provider OpenAI-compatible pada Agent/Guardrails.

### Jika Google Sheets tidak ditemukan

Periksa:

-   Spreadsheet ID.
-   Akun Google yang di-authorize Composio.
-   Akses akun tersebut ke spreadsheet.

## 9. Flow ID

Setelah flow berhasil dijalankan:

1.  Buka flow `hackathon`.
2.  Salin Flow ID.
3.  Masukkan ke `.env` Flask:

``` env
LANGFLOW_FLOW_ID=FLOW_ID_KAMU
```

## 10. Langflow API Key

Ini **berbeda** dari Composio API key dan API key model.

Jika instance Langflow kamu membutuhkan authentication untuk request
dari Flask, masukkan API key Langflow ke:

``` env
LANGFLOW_API_KEY=LANGFLOW_API_KEY_KAMU
```

Jangan memasukkan Langflow API key ke field Composio.

## 11. Hubungkan ke Flask

Contoh:

``` env
LANGFLOW_BASE_URL=http://localhost:7860
LANGFLOW_FLOW_ID=FLOW_ID_KAMU
LANGFLOW_API_KEY=LANGFLOW_API_KEY_KAMU
```

Jika deployment Langflow tidak memerlukan API key pada endpoint yang
dipakai, ikuti konfigurasi instance tersebut.

## 12. Ringkasan Semua Credential

  -----------------------------------------------------------------------
  Nama                    Letak                   Fungsi
  ----------------------- ----------------------- -----------------------
  `COMPOSIO_API_KEY`      Composio                Akses Composio
                          component/environment   

  Google OAuth2           Composio connection     Akses Google Sheets
                                                  melalui Composio

  API Key Agent           Agent/provider Langflow Model OpenAI-compatible

  API Key Guardrails      Guardrails/provider     AI check Guardrails
                          Langflow                bila diperlukan

  `LANGFLOW_API_KEY`      `.env` Flask            Akses endpoint Langflow
                                                  bila diperlukan

  `SPREADSHEET_ID`        Flask `.env`            Spreadsheet untuk Flask

  Spreadsheet ID          Composio Google Sheets  Spreadsheet untuk tool
                                                  Langflow

  `API_KEY`               Flask `.env` + ESP32    ESP32 → Flask
                          `secrets.h`             

  Service Account JSON    Flask                   Flask → Google Sheets
  -----------------------------------------------------------------------

Tidak ada credential di tabel tersebut yang boleh diisi dengan key
credential lain.

## 13. Yang Jangan Di-upload ke GitHub

``` text
.env
service-account.json
secrets.h
API key model
Composio API key
Langflow API key
```

`hackathon.json` publik harus tetap menggunakan placeholder dan tidak
mengandung secret pribadi.
