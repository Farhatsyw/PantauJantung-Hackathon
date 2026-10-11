# PROMPT LOG: PantauJantung

IBM SkillsBuild University Education: National Hackathon 2026
Tema: Healthcare & Wellbeing

## Peran IBM Bob di proyek ini

IBM Bob dipakai sebagai **alat pengembangan (dev tool)** untuk membuat frontend dan backend aplikasi web. Seluruh prompt di bawah dikirim ke Bob secara bertahap, dan setiap hasilnya diuji dan ditinjau sebelum lanjut ke prompt berikutnya.

Pembagian peran komponen:

| Komponen | Peran |
|---|---|
| IBM Bob | Membantu menulis kode web (Flask backend, HTML/JS frontend) |
| Langflow | Alur analisis: Guardrails, Agent, menulis hasil ke Google Sheets (via Composio) |
| ESP32 + MAX30102 | Sumber data detak jantung dan SpO2 |
| Google Sheets | Penyimpanan data pasien, data sensor, dan riwayat chat |

Stack: Python Flask, HTML + JavaScript polos, Tailwind CSS (CDN), Chart.js (CDN), gspread.

Dokumen ini hanya memuat prompt yang paling berpengaruh. Prompt perbaikan kecil (typo, penyesuaian tampilan minor) tidak dicantumkan.

## Ringkasan

| No | Tahap | Tujuan |
|---|---|---|
| 1 | Setup | Struktur proyek dan design system |
| 2 | Frontend | Tiga halaman (daftar pasien, dashboard, chat) dengan data dummy |
| 3 | Backend | Pilih pasien dan proxy chat ke Langflow |
| 4 | Keamanan | Kunci id pasien di session, pesan terstruktur, sanitasi |
| 5 | Keamanan | Cegah salah pasien saat dua tab terbuka |
| 6 | Data | Ganti data dummy dengan Google Sheets, kirim riwayat ke chat |
| 7 | Chat | Ringkasan 30 hari dihitung di backend |
| 8 | Chat | Riwayat percakapan tersimpan dan sidebar |
| 9 | IoT | Terima data ESP32 dan picu analisis otomatis |
| 10 | Demo | Mode simulasi pengukuran untuk juri |
| 11 | Tampilan | Chat bergaya aplikasi chat penuh layar |
| 12 | Keamanan | Id pasien tidak terbawa setelah kembali ke daftar |

---

## Prompt 1: Setup proyek dan design system

**Tujuan:** menyiapkan struktur folder dan arah desain.

```
Saya mau bikin project web untuk aplikasi monitoring kesehatan jantung berbasis IoT. Stack yang saya mau: Python Flask untuk backend, HTML + JavaScript polos untuk frontend (tanpa React/build tools), pakai Tailwind CSS lewat CDN untuk styling, dan Chart.js lewat CDN untuk grafik nanti.

Tolong buatkan struktur folder awal:
- app.py (entry point Flask, serve halaman static)
- .env.example (untuk API key nanti)
- static/index.html (halaman kosong dulu, tapi sudah pasang Tailwind CDN)
- static/css/style.css (untuk custom style di luar Tailwind)

Untuk desain, saya mau nuansa modern dan bersih, terinspirasi dari layout kelarinkuyy.my.id (card dengan sudut membulat, badge kecil, section berbentuk step bernomor, banyak white space), tapi warnanya ganti jadi kombinasi putih dan merah (merah bertema kesehatan jantung, semacam merah darah/crimson, bukan merah terang), font boleh kamu tentukan yang readable dan modern. Ini bukan landing page jasa, tapi aplikasi kesehatan, jadi kesannya harus tenang dan terpercaya, bukan flashy.

Buatkan dulu file dasarnya saja, styling detail per halaman saya minta bertahap.
```

**Hasil:** struktur proyek, `style.css`, dan variabel warna (putih dan merah jantung) terbentuk.

---

## Prompt 2: Tiga halaman frontend (data dummy)

**Tujuan:** membuat halaman sekaligus agar tampilan konsisten, data masih dummy.

```
Lanjutkan project sebelumnya. Sekarang buatkan 3 halaman sekaligus, semua pakai data dummy dulu (belum fetch ke backend), style konsisten (putih + merah jantung, card rounded):

1. static/index.html: halaman depan, 2 bagian:
   - Kiri: form pendaftaran pasien baru (nama, umur, jenis kelamin dropdown), tombol "Simpan dan lanjut ke pengukuran"
   - Kanan: daftar pasien terdaftar sebagai card (avatar inisial bulat, nama, umur+jk), tombol "Ukur" di tiap card yang arahkan ke halaman pengukuran/chat pasien itu
   - Data dummy: 2-3 pasien contoh

2. static/dashboard.html: halaman detail satu pasien:
   - Header: nama, umur, jenis kelamin pasien
   - Badge status besar (Normal=hijau, Waspada=kuning, Tinggi=merah) + teks catatan_ai di bawahnya
   - Grafik Chart.js: BPM dan SpO2 dari waktu ke waktu
   - Tabel riwayat pengukuran (timestamp, bpm, spo2, status)
   - Data dummy hardcode di JavaScript

3. static/chat.html: halaman chat sederhana untuk satu pasien:
   - Header kecil menunjukkan sedang chat untuk pasien siapa
   - Area bubble chat (kiri jawaban AI, kanan pertanyaan user), input box + tombol kirim
   - Untuk sekarang pas kirim pesan, cukup tampilkan balasan dummy "Sedang menghubungi asisten..."
```

**Hasil:** tiga halaman jadi. Tampilan dikoreksi lewat beberapa prompt perbaikan (lihat Prompt 11).

---

## Prompt 3: Backend pilih pasien dan proxy chat ke Langflow

**Tujuan:** menyambungkan chat ke Langflow lewat backend, bukan langsung dari browser (supaya API key tidak terbuka).

```
Sekarang sambungkan backend. Di app.py, buatkan:

1. Endpoint POST /api/select-patient: terima id_pasien, simpan ke session Flask
2. Endpoint POST /api/chat: terima pesan dari frontend, kirim ke Langflow API di http://localhost:7860/api/v1/run/FLOW_ID dengan header x-api-key dari environment variable LANGFLOW_API_KEY, format input_value dan output_type sesuai API Langflow, lalu kembalikan jawabannya ke frontend

Field API key dan Flow ID pakai environment variable (python-dotenv), jangan di-hardcode. Update .env.example juga.

Update static/chat.html supaya betulan fetch ke /api/chat, bukan lagi pesan dummy.
```

**Temuan saat ditinjau:** id pasien dari body request diprioritaskan di atas session (celah: bisa diubah lewat DevTools), pesan dikirim mentah tanpa format yang dibutuhkan Agent, parsing respons di-hardcode, dan respons mentah Langflow ikut dikirim ke frontend. Semuanya diperbaiki di Prompt 4.

---

## Prompt 4: Kunci id pasien di session, pesan terstruktur, sanitasi

**Tujuan:** memastikan chat hanya bisa mengakses pasien yang sedang dipilih.

```
Perbaiki endpoint /api/chat dan /api/select-patient di app.py. Masalah di versi sekarang:

1. id_pasien TIDAK BOLEH diambil dari body request. Ambil hanya dari session["id_pasien"]. Jika tidak ada, return 400. Hapus pengiriman id_pasien dari chat.html; frontend hanya mengirim {"message": "..."}.
2. id_pasien berformat string seperti "P001", bukan angka. /api/select-patient hanya menerima id yang ada di daftar pasien, selain itu return 404.
3. Buat dict sementara PASIEN di app.py (nanti diganti data dari Google Sheets).
4. Kirim ke Langflow, sebagai input_value, teks persis seperti ini, satu field per baris (umur dan jenis_kelamin diambil dari PASIEN, bukan dari user):
   mode: chat
   id_pasien: <dari session>
   umur: <umur>
   jenis_kelamin: <jenis kelamin>
   pertanyaan: <teks dari user>
5. Sanitasi teks user: ganti semua newline dan carriage return dengan spasi, potong maksimal 500 karakter, tolak pesan kosong dengan 400.
6. Hapus tweaks.session_id. Kirim "session_id" di level atas body request ke Langflow.
7. Parsing respons: flow punya DUA Chat Output (jawaban utama dan jalur penolakan), jadi jangan hardcode outputs[0].outputs[0]. Iterasi semua outputs[*].outputs[*], kumpulkan results.message.text yang tidak kosong, gabungkan jika lebih dari satu. Jika semua kosong, return 502.
8. Jangan kirim respons mentah Langflow ke frontend. Catat di log server saja; frontend hanya menerima pesan error umum.
```

**Hasil:** id pasien hanya dari session, pesan dibersihkan dan dipotong, format 5 baris sesuai, kedua Chat Output terbaca. Uji manipulasi id lewat DevTools: nilai dari body diabaikan.

---

## Prompt 5: Cegah salah pasien saat dua tab terbuka

**Tujuan:** session hanya menyimpan satu pasien per browser, jadi tab lama bisa menjawab dengan data pasien lain.

```
Perbaiki risiko dua tab di /api/chat. Frontend mengirim {"message": "...", "id_pasien": "<id yang tampil di halaman>"}. Nilai id_pasien dari body TIDAK BOLEH dipakai untuk mencari data atau dikirim ke Langflow. Gunakan hanya sebagai pemeriksaan konsistensi: jika berbeda dengan session["id_pasien"], return 409 dengan pesan "Pasien aktif telah berubah. Muat ulang halaman ini." dan jangan panggil Langflow. Di chat.html, tampilkan pesan itu sebagai bubble error dan nonaktifkan input sampai halaman dimuat ulang. Juga pastikan chat.html menunggu (await) /api/select-patient selesai sebelum tombol kirim aktif, dan tampilkan error jika hasilnya 404.
```

**Hasil:** uji dua tab (chat P001 di tab A, P002 di tab B, kirim dari tab A) menampilkan "Pasien aktif telah berubah", input terkunci, dan tidak ada panggilan ke Langflow.

---

## Prompt 6: Google Sheets sebagai database dan riwayat untuk chat

**Tujuan:** mengganti data dummy dengan data asli, dan memindahkan pembacaan riwayat dari Agent ke backend.

```
Tambahkan akses Google Sheets ke backend memakai gspread dan google-auth (tambahkan ke requirements.txt). Env di .env.example:
GOOGLE_SERVICE_ACCOUNT_FILE=service-account.json
SPREADSHEET_ID=

Buat file sheets.py berisi fungsi:
- get_patients(): baca tab data_pasien, return dict id_pasien -> {nama, umur, jenis_kelamin}
- get_patient(id_pasien): return dict atau None
- add_patient(nama, umur, jenis_kelamin): buat id berikutnya (P001, P002, dst), tambah baris di data_pasien (kolom: id_pasien, nama, umur, jenis_kelamin, tanggal_daftar format YYYY-MM-DD), return id
- get_sensor_rows(id_pasien, limit=50): baca tab data_sensor, hanya baris milik id_pasien itu, urut terbaru dulu

Aturan sheets.py:
- Bandingkan id_pasien dengan .strip(). Lewati baris yang id-nya kosong.
- Kolom timestamp di data_sensor berformat teks "YYYY-MM-DD HH:MM". Urutkan riwayat dengan membandingkan string timestamp itu (terbaru dulu).
- Menulis pakai value_input_option RAW. Nilai teks yang diawali = + - @ diberi awalan apostrof supaya tidak dieksekusi sebagai formula.
- Cache hasil baca selama 10 detik (limit Sheets API sekitar 60 request per menit).
- Gunakan threading.Lock saat menambah pasien supaya id tidak kembar.
- Jangan pernah mengembalikan pesan error mentah dari Google ke frontend; catat di log server.

Endpoint baru di app.py:
- GET /api/patients: daftar pasien
- POST /api/patients: validasi nama (tidak kosong, maks 100 karakter), umur (bilangan bulat 0-120), jenis_kelamin (hanya "Laki-laki" atau "Perempuan"). Tidak valid = 422.
- GET /api/patient-data/<id_pasien>: profil + riwayat sensor. Return 404 jika id tidak ada.

Ubah endpoint yang ada: hapus dict PASIEN sementara. /api/select-patient dan /api/chat memakai get_patient() dari sheets.py. Logika session, pemeriksaan konsistensi id (409), dan sanitasi jangan diubah.

Di /api/chat, ambil 5 pengukuran terakhir dari get_sensor_rows(id_pasien, limit=5) dan sertakan di input_value sebagai field "riwayat" (satu baris per pengukuran, terbaru dulu, format: "- <timestamp> | bpm <bpm> | spo2 <spo2> | status: <status atau (belum dianalisis)>"), sebelum field pertanyaan. Jika pembacaan Sheets gagal, return 502, jangan lanjut ke Langflow.

Frontend: semua ID pasien berformat string "P001". Buang seluruh data dummy. index.html ambil daftar dari GET /api/patients dan form memanggil POST /api/patients. dashboard.html ambil data dari GET /api/patient-data/<id>; jika id kosong atau 404 tampilkan "Pasien tidak ditemukan" tanpa fallback ke pasien lain; jika status kosong tampilkan "Sedang dianalisis..." dan refresh tiap 10 detik. Semua teks dari server di-escape sebelum masuk innerHTML.
```

**Mengapa riwayat dikirim backend:** saat pengujian, tool baca Sheets di Langflow hanya mengambil baris pertama yang cocok (bukan yang terbaru), kadang gagal menemukan data yang ada, dan lambat (sampai 20 detik). Jawaban chat untuk P001 memakai pengukuran lama (105/94) padahal yang terbaru 135/88. Pembacaan dipindah ke backend supaya data terurut dan pasti benar.

**Hasil uji:** pasien tidak ada ditolak ("Pasien tidak ditemukan"), nama berisi tag HTML tampil sebagai teks biasa, pasien baru masuk ke Sheets, dan chat P001 memakai pengukuran terbaru.

---

## Prompt 7: Ringkasan 30 hari dihitung di backend

**Tujuan:** jawaban tren tidak boleh bergantung pada tebakan AI.

```
Di /api/chat, ubah pengiriman riwayat ke Langflow. Logika lain tidak berubah.

1. Field "riwayat" turun dari 5 menjadi 3 pengukuran terbaru.
2. Tambah field "ringkasan_30_hari" setelah riwayat, dihitung di kode Python (bukan oleh AI) dari baris data_sensor milik pasien dalam 30 hari terakhir (zona Asia/Jakarta). Buat fungsi sheets.ringkasan_sensor(id_pasien, hari=30) yang mengembalikan satu baris teks:
   "jumlah <n> | bpm rata-rata <x> (terendah <a>, tertinggi <b>) | spo2 rata-rata <y> (terendah <c>) | status: Normal <p>, Waspada <q>, Tinggi <r>, belum dianalisis <s> | kecenderungan bpm: <naik/turun/stabil/data belum cukup> | kecenderungan spo2: <naik/turun/stabil/data belum cukup>"
   - Kecenderungan: bagi baris 30 hari menjadi dua paruh berdasarkan urutan waktu, bandingkan rata-ratanya. bpm: selisih lebih dari 5 = naik atau turun, selain itu stabil. spo2: selisih lebih dari 2. Jika jumlah pengukuran kurang dari 4, tulis "data belum cukup".
3. Gunakan cache sheets yang sudah ada. Jika pembacaan gagal, perilaku sama seperti riwayat (502).
4. Jangan sertakan catatan_ai dan nama pasien di ringkasan.
```

---

## Prompt 8: Riwayat percakapan tersimpan dan sidebar

**Tujuan:** pengguna bisa membuka kembali percakapan sebelumnya, dipisah per pasien.

```
Tambahkan riwayat percakapan chat yang disimpan di Google Sheets, dan sidebar daftar percakapan di chat.html. Logika yang sudah ada (session, pemeriksaan konsistensi id 409, sanitasi pesan, format pesan ke Langflow, parsing respons, kunci input 404/409) jangan diubah.

Tab baru "riwayat_chat", kolom: id_percakapan, id_pasien, timestamp, role, pesan. Satu baris per pesan. role hanya "user" atau "ai".

sheets.py: list_conversations(id_pasien), get_conversation(id_pasien, id_percakapan) (kembalikan None jika bukan milik id_pasien itu), append_messages(...) menulis dua baris sekaligus dengan satu append_rows (RAW, awalan apostrof untuk = + - @, maksimal 4000 karakter).

app.py:
- /api/chat menerima field opsional "id_percakapan". Jika kosong, server membuat id baru (secrets.token_hex(6)). Jika ada, wajib cocok /^[0-9a-f]{12}$/ dan milik id_pasien di session, selain itu 404 tanpa memanggil Langflow. "session_id" ke Langflow memakai id_percakapan.
- Simpan pesan HANYA setelah Langflow berhasil menjawab. Jika gagal simpan, catat di log dan tetap kembalikan balasan.
- GET /api/chats dan GET /api/chats/<id_percakapan>: id_pasien SELALU dari session, tidak pernah dari query atau body.

chat.html: sidebar kiri berisi "Percakapan baru" dan daftar percakapan (dikelompokkan Hari ini / Kemarin / Lebih lama), tombol toggle buka/tutup sidebar (pilihan disimpan di localStorage), di layar sempit sidebar tampil sebagai panel yang menimpa konten. Semua teks dari server dipasang dengan textContent atau escape.
```

**Hasil uji:** pesan tersimpan sebagai pasangan baris (user dan ai) dengan id percakapan sama, sidebar menampilkan item baru, dan percakapan pasien lain tidak muncul. Satu temuan: setelah refresh halaman, percakapan aktif tidak diingat sehingga tampil sebagai percakapan baru. Diperbaiki dengan menyimpan id percakapan di URL (`chat.html?id=P001&c=<id>`).

---

## Prompt 9: Terima data ESP32 dan picu analisis otomatis

**Tujuan:** alur lengkap dari sensor sampai status terisi di Sheets.

```
Tambahkan alur pengukuran dari ESP32 di app.py dan sheets.py. Logika yang sudah ada jangan diubah.

1. POST /api/start-measurement: body {"id_pasien"}. Validasi id ada lewat get_patient (404 jika tidak). Simpan di variabel server ACTIVE_PATIENT (id + waktu) dengan threading.Lock. Kedaluwarsa setelah 5 menit.

2. POST /api/sensor-data untuk ESP32:
   - Header x-api-key harus sama dengan API_KEY di .env, dibandingkan dengan hmac.compare_digest. Salah = 401. Jika API_KEY kosong, tolak semua (503).
   - Body JSON {"bpm": angka, "spo2": angka}. Tolak boolean, string, NaN, infinity. Validasi bpm 20-220 dan spo2 50-100. Tidak valid = 422 dan JANGAN menulis apa pun.
   - id_pasien hanya dari ACTIVE_PATIENT. Kosong atau kedaluwarsa = 409. Jangan pernah menerima id_pasien dari body ESP32.
   - Batasi 1 pengukuran per pasien per 5 detik (429).
   - Tambah satu baris di data_sensor (timestamp teks "YYYY-MM-DD HH:MM" Asia/Jakarta, id_pasien, bpm, spo2, status dan catatan_ai kosong). Ambil nomor baris dari hasil append, bukan dihitung sendiri.
   - Segera return 200 ke ESP32, jangan menunggu Langflow. Jalankan analisis di thread terpisah.

3. Thread analisis: sebelum memanggil Langflow, baca baris itu dari Sheets dan pastikan id_pasien dan bpm/spo2 cocok. Kirim ke Langflow input_value:
   mode: analisis
   id_pasien: <id>
   nama: <nama>
   umur: <umur>
   jenis_kelamin: <jenis kelamin>
   bpm: <bpm>
   spo2: <spo2>
   baris_sheet: <nomor baris>
   Maksimal 2 analisis bersamaan (BoundedSemaphore). Setelah selesai, BACA ULANG baris itu dari Sheets: jika status terisi catat sukses; jika kosong coba ulang satu kali setelah 10 detik, lalu catat "analisis tertunda". Jangan log data kesehatan lengkap.

4. dashboard.html: tombol "Mulai Pengukuran" yang memanggil /api/start-measurement, menampilkan "Menunggu data...", lalu polling sampai ada pengukuran baru dan status terisi.
```

**Alasan desain:** status penyimpanan diverifikasi dengan membaca ulang dari Sheets, bukan dari klaim model. Nomor baris dibuat backend supaya Agent tidak menulis ke baris yang salah.

**Hasil uji:** key salah = 401, nilai 0/0 = 422 tanpa baris baru, tanpa pengukuran aktif = 409, 130 bpm = Waspada dan 131 bpm = Tinggi, hasil analisis masuk ke baris yang benar.

---

## Prompt 10: Mode simulasi pengukuran untuk juri

**Tujuan:** juri bisa mencoba seluruh alur tanpa perangkat ESP32.

```
Tambahkan fitur simulasi pengukuran. Gunakan fungsi bersama dengan /api/sensor-data (refactor: proses_pengukuran(id_pasien, bpm, spo2)).

1. Env DEMO_MODE (default false). Hanya jika true, endpoint aktif; selain itu 404.
2. POST /api/simulate-measurement: body {"id_pasien", "skenario"} dengan skenario hanya "normal", "waspada", atau "tinggi" (selain itu 422). Pasien umur di bawah 13 ditolak.
3. Nilai dihasilkan server, acak dalam rentang: normal bpm 62-98 spo2 96-99; waspada bpm 101-125 spo2 92-94; tinggi bpm 135-160 spo2 85-89. Tidak pernah dari input klien.
4. Batasi 1 simulasi per pasien per 30 detik dan 10 per menit global (429).
5. dashboard.html: jika GET /api/config mengembalikan {"demo": true}, tampilkan kartu "Simulasi pengukuran (data contoh, bukan dari sensor)" dengan tombol Normal, Waspada, Tinggi, dan bagian "Isi manual" untuk BPM dan SpO2 (divalidasi server). Beri label jelas bahwa ini data contoh.
```

---

## Prompt 11: Tampilan chat bergaya aplikasi chat penuh layar

**Tujuan:** menghilangkan kesan "kotak di dalam kotak" pada halaman chat.

```
Ubah layout static/chat.html menjadi gaya aplikasi chat penuh layar. Hanya tampilan: jangan ubah logika JS, id elemen, endpoint, formatAi/escapeHtml, kunci input, atau toggle sidebar.

1. Halaman memenuhi layar (100vh dikurangi navbar), tanpa footer di halaman ini; yang scroll hanya daftar pesan.
2. Hapus .pj-card/border/radius/shadow pada pembungkus sidebar dan area chat.
3. Sidebar rata: lebar 260px, hanya garis tipis di sisi kanan, item berupa baris rata dengan hover dan highlight item aktif.
4. Header pasien ramping satu baris: toggle sidebar, nama pasien, tombol "Lihat Dashboard", dan tautan kecil "← Pasien".
5. Pesan mengalir di kolom tengah maksimal 760px. Balasan AI sebagai teks biasa dengan avatar kecil "AI"; pesan user tetap bubble di kanan.
6. Input melayang di bawah kolom yang sama (kotak membulat, tombol Kirim di dalam kotak), disclaimer kecil di bawahnya.
7. Di bawah 700px sidebar tetap panel yang menimpa konten.
8. Pakai variabel warna dan font dari style.css; jangan hardcode.
```

**Prompt tampilan lain yang dikirim:** keseragaman jarak dan sticky footer di semua halaman, kartu pengukuran di dashboard (satu kartu, di atas grafik, dengan bagian "Dari sensor", "Simulasi otomatis", "Isi manual"), serta posisi indikator mengetik (harus di bawah pesan terakhir).

---

## Prompt 12: Id pasien tidak boleh terbawa setelah kembali ke daftar

**Tujuan:** menu Dashboard dan Asisten AI di navbar tidak boleh membuka pasien terakhir setelah pengguna kembali ke daftar pasien.

```
Perbaiki penyimpanan id pasien di navbar. Hanya nav.js, index.html, dan satu endpoint di app.py. Jangan ubah hal lain.

1. static/js/nav.js: jika halaman saat ini adalah daftar pasien (location.pathname "/" atau "/index.html"), hapus sessionStorage "pj_pid". Lakukan juga saat event "pageshow" dengan event.persisted true (tombol Back). Hapus juga jika nilainya tidak cocok /^P\d{3,}$/.
2. Jika tidak ada id aktif yang valid, link navbar "Dashboard" dan "Asisten AI" diarahkan ke "/?pilih=1".
3. Tautan "Kembali" di chat.html dan dashboard.html menuju "/".
4. index.html: jika URL berisi ?pilih=1, tampilkan peringatan "Pilih pasien terlebih dahulu untuk melihat dashboard atau asisten AI." lalu hapus parameter dari URL (history.replaceState). Pesan dipasang dengan textContent.
5. app.py: tambah POST /api/clear-patient yang menghapus session["id_pasien"]. Panggil dari index.html saat halaman dimuat.
```

---

## Temuan pengujian dan perbaikannya

| Temuan | Perbaikan |
|---|---|
| Id pasien dari body request bisa mengubah pasien yang dibaca | Id hanya dari session (Prompt 4) |
| Dua tab membuat jawaban pasien A tampil di halaman pasien B | Pemeriksaan konsistensi id, respons 409 (Prompt 5) |
| Tool baca Sheets di Langflow mengambil baris pertama, bukan terbaru, dan kadang gagal | Backend membaca riwayat dan mengirimnya ke Langflow (Prompt 6) |
| Halaman chat dan dashboard menampilkan nama pasien default saat id tidak ada | Fallback dihapus, tampil "Pasien tidak dikenal" |
| Nama berisi tag HTML dieksekusi sebagai HTML | Semua teks dari server di-escape |
| Agent menulis ke baris 1 (header spreadsheet) saat diuji | Validasi di instruksi Agent dan nomor baris dari backend |
| Kuota Gemini gratis habis, Guardrails memblokir semua pesan (fail-closed) | Dicatat sebagai risiko, billing perlu diaktifkan sebelum demo |
| Kedaluwarsa sesi pengukuran dan duplikasi baris | Batas waktu 5 menit, lock, nomor baris dari hasil append |

## Batasan yang diketahui

- Belum ada login. Siapa pun yang membuka web dapat memilih pasien mana saja. Langkah berikutnya: autentikasi kader dan hak akses per pasien.
- Status Normal, Waspada, atau Tinggi ditentukan oleh model AI mengikuti aturan tertulis, bukan oleh kode. Langkah berikutnya: memindahkan penentuan status ke kode backend dan menyisakan AI untuk penjelasan.
- Data kesehatan dan riwayat chat disimpan di Google Sheets. Untuk produksi diperlukan database terenkripsi.
- SpO2 dari modul MAX30102 bersifat perkiraan dan belum terkalibrasi dengan alat medis.
- Data pada mode simulasi diberi label "data contoh, bukan dari sensor" di antarmuka.
