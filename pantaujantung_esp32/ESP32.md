# ESP32 + MAX30102

Dokumen ini digunakan setelah Flask dan Langflow sudah siap.

## 1. Perangkat

-   ESP32
-   MAX30102
-   Kabel jumper
-   Arduino IDE
-   Wi-Fi

## 2. Wiring

``` text
MAX30102    ESP32
VIN         3V3
GND         GND
SDA         GPIO 21
SCL         GPIO 22
```

## 3. Sketch

Gunakan:

``` text
pantaujantung_esp32.ino
```

Buat file lokal:

``` text
secrets.h
```

File ini tidak boleh di-upload ke GitHub karena berisi credential
Wi-Fi/server.

## 4. Isi `secrets.h`

Contoh struktur:

``` cpp
#pragma once

#define WIFI_SSID  "NAMA_WIFI"
#define WIFI_PASS  "PASSWORD_WIFI"
#define SERVER_URL "http://192.168.1.10:5000/api/sensor-data"
#define API_KEY    "API_KEY_YANG_SAMA_DENGAN_BACKEND"
```

Sesuaikan dengan definisi yang digunakan sketch kamu.

## 5. API Key ESP32

`API_KEY` pada `secrets.h` adalah key buatan sendiri untuk komunikasi:

``` text
ESP32 → Flask
```

Nilainya harus sama dengan:

``` env
API_KEY=...
```

di `.env` Flask.

Ini **bukan**:

``` text
COMPOSIO_API_KEY
LANGFLOW_API_KEY
API key model/LLM
```

## 6. Server URL

Jangan menggunakan:

``` text
localhost
```

sebagai alamat Flask dari ESP32.

Cari IPv4 komputer yang menjalankan Flask:

``` bash
ipconfig
```

Contoh:

``` text
192.168.1.10
```

Maka server URL menjadi:

``` text
http://192.168.1.10:5000/api/sensor-data
```

ESP32 dan komputer harus berada pada jaringan yang dapat saling
berkomunikasi.

## 7. Backend

Di `.env` Flask:

``` env
DEMO_MODE=false
API_KEY=API_KEY_YANG_SAMA_DENGAN_ESP32
```

Restart Flask setelah mengubah `.env`.

## 8. Arduino IDE

1.  Install board ESP32.
2.  Pilih board yang sesuai.
3.  Install library yang dibutuhkan sketch MAX3010x/SparkFun.
4.  Hubungkan ESP32.
5.  Pilih COM port.
6.  Compile.
7.  Upload.
8.  Buka Serial Monitor.

## 9. Alur Pengukuran

1.  Jalankan Langflow jika fitur AI digunakan.
2.  Jalankan Flask.
3.  Buka `http://localhost:5000` pada komputer.
4.  Pilih/daftarkan pasien.
5.  Masuk dashboard.
6.  Klik **Mulai Pengukuran**.
7.  Letakkan jari pada MAX30102.
8.  Jaga jari tetap stabil.
9.  ESP32 mengirim hasil ke Flask.
10. Dashboard memproses hasil pengukuran.

## 10. Endpoint

ESP32 mengirim ke:

``` text
POST /api/sensor-data
```

Header:

``` text
x-api-key: API_KEY
```

## 11. Troubleshooting

### ESP32 tidak terhubung Wi-Fi

Periksa SSID dan password pada `secrets.h`.

### ESP32 tidak bisa mengakses Flask

Periksa:

-   IP komputer.
-   Port Flask.
-   `SERVER_URL`.
-   Firewall.
-   Koneksi jaringan ESP32 dan komputer.

### HTTP 401

API key ESP32 berbeda dengan `API_KEY` Flask.

### HTTP 503

Backend belum memiliki API key ESP32 yang diperlukan.

### Sensor tidak membaca stabil

Periksa:

-   Wiring.
-   Posisi jari.
-   Tekanan jari.
-   Gerakan tangan.
-   Koneksi MAX30102.
-   Serial Monitor.

## 12. Template Credential

Untuk repository publik, sediakan `secrets.example.h`, bukan `secrets.h`
asli:

``` cpp
#pragma once

#define WIFI_SSID  "YOUR_WIFI_NAME"
#define WIFI_PASS  "YOUR_WIFI_PASSWORD"
#define SERVER_URL "http://YOUR_PC_IP:5000/api/sensor-data"
#define API_KEY    "YOUR_API_KEY"
```

`secrets.h` asli tetap hanya di komputer pengguna.
