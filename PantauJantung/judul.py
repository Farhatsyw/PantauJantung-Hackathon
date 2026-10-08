"""
judul.py — Logika pembuatan judul percakapan sidebar PantauJantung.

Fungsi publik:
    buat_judul(pesan: str, balasan_ai: str | None = None) -> str

Prinsip:
- Pesan user adalah sumber kebenaran.  Kamus hanya merapikan (singkatan, typo,
  bahasa gaul).  Judul tidak pernah memuat kata yang tidak bisa dilacak ke
  pesan asli.
- Tanpa I/O, tanpa dependensi luar (stdlib saja).
- Semua regex dan indeks kamus di-pre-kompilasi sekali saat import.
"""

from __future__ import annotations
import re as _re
import difflib as _difflib
import os as _os

# ══════════════════════════════════════════════════════════════════════════════
# ALIAS_EJAAN  — singkatan / typo / gaul → baku (token-level, case-insensitive)
# Hanya untuk token PERSIS — bukan substring.
# ══════════════════════════════════════════════════════════════════════════════
ALIAS_EJAAN: dict[str, str] = {}
_alias_ejaan_raw = """
jntung jntg jantg jantng jtung jatung jantnug jnatung > jantung
dtak detk > detak
blkngan blkgn blakangan belakangn blkang > terakhir
cra > cara
gmna gimn bgmn bgmna gmana bagaimn > bagaimana
knpa knapa napa kenapaa > kenapa
kpan kapn > kapan
brp brapa berapaa > berapa
dmn dmana dimana > di mana
apkah apakh > apakah
bs bsa > bisa
bleh bole > boleh
tdk tdak > tidak
gk gx ngk > tidak
udh udah > sudah
belom blom > belum
masi > masih
lg > lagi
sy sya aku gw gue gua > saya
krg kurg > kurang
byk bnyak > banyak
tp tpi > tapi
jd jdi > jadi
dlm > dalam
sblm sebelom > sebelum
stlh setelh stelah > setelah
sbg > sebagai
spt kyk kayak > seperti
cuma > hanya
emg emang > memang
bnr bener > benar
slh > salah
mw > mau
pengen pgn pngn pingin pengin > ingin
nanya ntanya > bertanya
tau > tahu
dpt dapet > dapat
pake > pakai
bkin bikin bikn > membuat
ngukur > mengukur
nurunin turunin nurunkan > menurunkan
naikin naikkin > menaikkan
cek > periksa
ngecek > memeriksa
lemes lms > lemas
capek cape > lelah
pening pusng > pusing
skt skit sakitt > sakit
kpl kpala > kepala
dda > dada
nafas nfs > napas
ssak sesk > sesak
brdebar > berdebar
nyri > nyeri
mkn mkan makn > makan
mknan mkanan makanann > makanan
mnum minun > minum
syur > sayur
tkanan tknan > tekanan
drh drah > darah
tensi > tekanan darah
darting > darah tinggi
oksign oksgn oksijen oxigen > oksigen
kolestrl cholesterol > kolesterol
olga olrga olahrga > olahraga
tdr tdur tidr > tidur
istrht istirhat istrahat > istirahat
stress setres setress strs > stres
kwatir kuatir > khawatir
cmas > cemas
hml hamel > hamil
bpk > bapak
klg klrg > keluarga
pkm puskes pusksmas > puskesmas
rs > rumah sakit
dktr dkter doktr > dokter
pngukuran pengkuran pngkuran > pengukuran
hsl > hasil
tgl > tanggal
thn taun > tahun
mnt > menit
kemaren kmaren kmarin > kemarin
sekrang skarang sekarng > sekarang
tdi > tadi
mlm malem > malam
smalem semalem > semalam
pgi > pagi
hri > hari
"""
for _ln in _alias_ejaan_raw.strip().splitlines():
    _ln = _ln.strip()
    if not _ln or ">" not in _ln:
        continue
    _v2, _, _b = _ln.partition(">")
    _b = _b.strip().lower()
    for _v in _v2.split():
        _v = _v.strip().lower()
        if _v:
            ALIAS_EJAAN[_v] = _b
del _alias_ejaan_raw, _ln, _v2, _b, _v  # type: ignore[name-defined]


# ══════════════════════════════════════════════════════════════════════════════
# ALIAS_OBAT  — ejaan Inggris → nama Indonesia (token-level)
# ══════════════════════════════════════════════════════════════════════════════
ALIAS_OBAT: dict[str, str] = {}
_alias_obat_raw = """
amlodipine > amlodipin
furosemide > furosemid
spironolactone > spironolakton
digoxin > digoksin
nifedipine > nifedipin
candesartan > kandesartan
amiodarone > amiodaron
nitroglycerin > nitrogliserin
paracetamol > parasetamol
pseudoephedrine pseudoephedrin pseudoefedrine > pseudoefedrin
ephedrine > efedrin
diclofenac > diklofenak
naproxen > naproksen
omeprazole > omeprazol
ranitidine > ranitidin
cetirizine > cetirizin
loratadine > loratadin
hydrochlorothiazide hct > hidroklorotiazid
rivaroxaban > rivaroksaban
apixaban > apiksaban
"""
for _ln in _alias_obat_raw.strip().splitlines():
    _ln = _ln.strip()
    if not _ln or ">" not in _ln:
        continue
    _v2, _, _b = _ln.partition(">")
    _b = _b.strip().lower()
    for _v in _v2.split():
        _v = _v.strip().lower()
        if _v:
            ALIAS_OBAT[_v] = _b
del _alias_obat_raw, _ln, _v2, _b, _v  # type: ignore[name-defined]


# ══════════════════════════════════════════════════════════════════════════════
# DAFTAR_OBAT  — nama obat yang TIDAK boleh dikoreksi
# ══════════════════════════════════════════════════════════════════════════════
DAFTAR_OBAT: set[str] = {
    "amlodipin","bisoprolol","kandesartan","valsartan","losartan","telmisartan",
    "irbesartan","kaptopril","captopril","lisinopril","ramipril","enalapril","nifedipin",
    "diltiazem","verapamil","atenolol","propranolol","metoprolol","carvedilol",
    "furosemid","hidroklorotiazid","spironolakton","digoksin","aspirin","klopidogrel",
    "clopidogrel","tikagrelor","warfarin","rivaroksaban","apiksaban","dabigatran",
    "simvastatin","atorvastatin","rosuvastatin","fenofibrat","gemfibrozil","nitrogliserin",
    "isosorbid","ivabradin","amiodaron","metformin","glimepirid","insulin","omeprazol",
    "ranitidin","antasida","parasetamol","ibuprofen","diklofenak","naproksen",
    "pseudoefedrin","efedrin","fenilefrin","loratadin","cetirizin",
    "concor","norvask","aspilet","plavix","lasix","herbesser","coumadin","simarc",
    "panadol","bodrex","paramex","sanmol","decolgen","tremenza","sudafed","antangin",
    "promag","mylanta","lipitor","crestor","glucophage","ventolin","bisolvon",
}


# ══════════════════════════════════════════════════════════════════════════════
# KAMUS_BAKU  — set kata baku (tidak pernah dikoreksi oleh _koreksi_token)
# ══════════════════════════════════════════════════════════════════════════════
KAMUS_BAKU: set[str] = {
    # Fungsi/umum
    "yang","dan","atau","dengan","untuk","dari","di","ke","pada","oleh","dalam","saat",
    "jika","kalau","karena","agar","supaya","sebelum","sesudah","setelah","sambil",
    "sampai","hingga","tentang","mengenai","soal","antara","sebagai","seperti","hanya",
    "saja","juga","masih","sudah","belum","akan","sedang","pernah","bisa","dapat",
    "boleh","harus","perlu","mau","ingin","sangat","lebih","kurang","cukup","terlalu",
    "sekali","kali","satu","dua","tiga","empat","lima","enam","tujuh","delapan",
    "sembilan","sepuluh","seratus","ribu","pertama","kedua","ketiga","setengah",
    "sekitar","kira","mungkin","pasti","bahwa","bila","ketika","waktu","sementara",
    "sebaiknya","setiap","tiap","banyak","sedikit","semua","beberapa",
    "masalah","contoh","bentuk","jenis","macam","porsi","gelas","sendok","piring",
    "butir","potong","mangkuk","takaran","kadar","angka","nilai","batas","rentang",
    "rata","tertinggi","terendah","paling",
    "ini","itu","saya","anda","kami","kita","dia","mereka","kamu",
    "apa","siapa","kapan","mana","bagaimana","kenapa","mengapa","berapa",
    "apakah","bolehkah","bisakah","tidak","bukan","jangan",
    "tapi","tetapi","namun","lalu","kemudian","lagi","terus",
    "ada","adalah","merupakan","menjadi","jadi","sama","beda","berbeda","mirip",
    "sering","jarang","kadang","selalu","biasanya",
    "tadi","kemarin","sekarang","nanti","besok","lusa",
    "pagi","siang","sore","malam","semalam",
    "hari","minggu","bulan","tahun","jam","menit","detik",
    "terakhir","terkini","baru","lama","dulu","awal","akhir",
    # Kata umum tambahan (tidak boleh dikoreksi otomatis)
    "baik","biar","kok","bagus","buruk","bibi","desa","paha","pil","biasa",
    "ibu","teman","tenang","renang","kali","kaki","kulit","kilo","kolam",
    "kelas","bukan","sama","pakai",
    # Kata kerja
    "cara","cari","makan","minum","tidur","bangun","jalan","lari","olahraga","senam",
    "berenang","bersepeda","duduk","berdiri","berbaring","merokok","begadang",
    "mengukur","ukur","memeriksa","periksa","mengecek","melihat","membaca",
    "memakai","menggunakan","pakai","membuat","bikin",
    "menurunkan","menaikkan","menjaga","mengatasi","mengurangi",
    "menghindari","menghindar","mencegah","mengobati","mengonsumsi","konsumsi",
    "merasa","terasa","berdebar","berdetak","bernapas","berkeringat",
    "pingsan","muntah","mual","batuk","demam","pusing","lemas","lelah","pegal",
    "kesemutan","bengkak","membaik","memburuk","naik","turun","stabil",
    "berubah","berhenti","mulai","lanjut","mengulang","menghitung","menjelaskan",
    "menyimpan","menghapus","menambah","mengubah","masuk","keluar","daftar",
    "bertanya","tahu","mengerti","paham",
    # Tubuh / kesehatan
    "jantung","detak","denyut","nadi","napas","oksigen","saturasi","spo2","bpm",
    "tekanan","darah","kolesterol","lemak","gula","garam","kopi","teh","kafein",
    "rokok","alkohol","santan","gorengan","manis","asin","berat","badan",
    "obesitas","kegemukan","diet","puasa","stres","cemas","khawatir","panik",
    "dada","kepala","perut","punggung","leher","bahu","lengan","tangan",
    "kaki","kuku","bibir","wajah","mata","telinga","jari",
    "kulit","kilo","kelas","kolam","kakak","bukan","pakaian","dokumen",
    "gejala","keluhan","penyakit","diabetes","hipertensi","hipotensi","stroke",
    "aritmia","takikardia","bradikardia","angina","koroner","serangan","gagal",
    "pembuluh","asam","urat","ginjal","paru","asma","ppok","tbc","covid",
    "flu","pilek","darurat","igd","ambulans","puskesmas","rumah","sakit",
    "dokter","apoteker","apotek","perawat","bidan","kader","klinik",
    "laboratorium","ekg","ekokardiografi","tensimeter","oksimeter","termometer",
    "timbangan","hamil","kehamilan","anak","bayi","lansia","remaja","dewasa",
    "umur","usia","laki","perempuan","keluarga","tinggi","rendah",
    "cepat","lambat","kencang","pelan","lemah","normal","waspada","status","sehat",
    "nyeri","sesak",
    # Makanan / minuman
    "nasi","roti","mi","mie","bubur","ikan","ayam","daging","telur","tempe","tahu",
    "kacang","sayur","sayuran","bayam","kangkung","sawi","brokoli","wortel","buncis",
    "kol","tomat","timun","labu","singkong","ubi","jagung","buah","pisang","pepaya",
    "apel","jeruk","semangka","alpukat","mangga","jambu","anggur","pir","kurma",
    "salak","melon","nanas","durian","bawang","putih","jahe","kunyit","madu","susu",
    "keju","mentega","minyak","kelapa","jeroan","seafood","udang","cumi","kerang",
    "kepiting","sosis","kornet","instan","kerupuk","sambal","penyedap","air","jus",
    "soda","minuman","energi","bir","tolak","angin","jamu","herbal","vitamin",
    "suplemen","kalium","magnesium","omega",
    # Aplikasi / alat
    "akun","pasien","data","profil","nama","kata","sandi","password","login",
    "dashboard","grafik","riwayat","chat","percakapan","aplikasi","alat","sensor",
    "kabel","baterai","bluetooth","wifi","internet","sinyal","koneksi","layar",
    "tombol","hasil","pengukuran","laporan","unduh","cetak","tren","perkembangan",
    "perubahan","kondisi","frekuensi","penggunaan","dosis","efek","samping",
    "interaksi","risiko","bahaya","aman","tips","langkah","panduan",
    "arti","maksud","pengertian","definisi",
}
KAMUS_BAKU |= DAFTAR_OBAT

# Muat kata_dasar.txt jika ada di direktori yang sama
_kata_dasar_path = _os.path.join(_os.path.dirname(__file__) or ".", "kata_dasar.txt")
KATA_DASAR_EKSTRA: set[str] = set()
if _os.path.isfile(_kata_dasar_path):
    try:
        with open(_kata_dasar_path, encoding="utf-8") as _f:
            KATA_DASAR_EKSTRA = {w.strip().lower() for w in _f if w.strip()}
        KAMUS_BAKU |= KATA_DASAR_EKSTRA
    except Exception:
        pass

# Semua token yang dikenal (tidak boleh dikoreksi)
_DIKENAL: set[str] = (
    KAMUS_BAKU
    | DAFTAR_OBAT
    | set(ALIAS_EJAAN.keys())
    | set(ALIAS_OBAT.keys())
)


# ══════════════════════════════════════════════════════════════════════════════
# SAPAAN_UJI — token tanpa makna topik (pesan yang hanya berisi ini = tak bermakna)
# ══════════════════════════════════════════════════════════════════════════════
_SAPAAN_UJI: set[str] = {
    "tes","test","tess","testing","coba","cobain","uji","cek","p","pp","ppp","ping",
    "halo","hallo","hai","hi","hello","hey","oi","woi","assalamualaikum","salam",
    "permisi","selamat","pagi","siang","sore","malam","oke","ok","ya","y","siap","sip",
    "mantap","makasih","terima","kasih","thanks","thx","tq","asdf","asd","qwerty","zxcv",
}

# ══════════════════════════════════════════════════════════════════════════════
# KATA_FUNGSI — dipakai oleh _judul_layak
# ══════════════════════════════════════════════════════════════════════════════
# Kata tanya (kapan, bagaimana, kenapa, mengapa, berapa, apakah, bolehkah, bisakah)
# TIDAK masuk KATA_FUNGSI — mereka boleh menjadi kata pertama judul bila
# judul >= 3 kata.  _judul_layak mengecek ini secara khusus.
_KATA_FUNGSI: set[str] = {
    "yang","apa","ke","di","dan","atau","dengan","untuk","dari",
    "ah","eh","hm","oh","ya","jadi","kalau","saya","sama",
    "aja","saja","tidak","dong","nih",
    # partikel tanya yang tidak boleh berdiri sendiri sebagai judul
    "apakah","bolehkah","bisakah","kah",
}

# Kata yang tidak dipilih sebagai kata-kunci judul (langkah 12)
# Lebih longgar dari _KATA_FUNGSI — "ini"/"itu" boleh muncul DI AKHIR
# frasa waktu (minggu ini, hari ini) tapi tidak berdiri sendiri sebagai judul.
_KATA_KUNCI_EXCLUDE: set[str] = _KATA_FUNGSI | {"itu","ini","ada"}

# Kata tanya yang BOLEH menjadi kata pertama judul jika judul >= 3 kata
_KATA_TANYA_BOLEH_AWAL: set[str] = {
    "kapan","bagaimana","kenapa","mengapa","berapa",
    "apakah","bolehkah","bisakah",
}

# ══════════════════════════════════════════════════════════════════════════════
# KATA TEMPLAT — kata yang boleh muncul di judul meski tidak dari pesan asli
# ══════════════════════════════════════════════════════════════════════════════
_KATA_TEMPLAT: set[str] = {
    "yang","cocok","dikonsumsi","aman","dihindari","frekuensi","penggunaan",
    "cara","efek","samping","kondisi","terakhir","saat","ini","dan","jantung",
    "detak","denyut","nadi",   # kata kardiovaskular dasar dalam templat
    "boleh","konsumsi","dosis","interaksi","risiko","gejala","pengertian",
    "olahraga","tekanan","darah","percakapan","baru","terlalu","cepat","lambat",
    "tinggi","rendah","kadar","status","periksa","tenaga","kesehatan","sering",
    "berdebar","koroner","serangan","gagal","darurat","tanda","pertama","hamil",
    "gangguan","tidur","stres","menjaga","badan","berat","membaca","dashboard",
    "atau","sesak","nyeri","saturasi","oksigen","pengukuran","hasil","kata","sandi",
    "lupa","membuat","akun","bermasalah","alat","ukur","memakai","arti","waspada",
    "normal","naik","turun","stabil","berubah","berbeda","layak",
    "keluhan","minggu","bulan",   # tambahan untuk template baru
    "untuk","takaran","makanan","minuman","obat","risiko","berbahaya","kolesterol",
}


# ══════════════════════════════════════════════════════════════════════════════
# REGEX_TAMBAHAN — pola konteks sebelum alias token
# ══════════════════════════════════════════════════════════════════════════════
_REGEX_TAMBAHAN: list[tuple] = [
    (_re.compile(r"(\d+)\s*(?:hr|hri|hari)\b",           _re.I), r"\1 hari"),
    (_re.compile(r"(\d+)\s*(?:mgg|minggu)\b",             _re.I), r"\1 minggu"),
    (_re.compile(r"(\d+)\s*(?:bln|bulan)\b",              _re.I), r"\1 bulan"),
    (_re.compile(r"(\d+)\s*(?:thn|taun|tahun)\b",         _re.I), r"\1 tahun"),
    (_re.compile(r"deg[\s\-]?degan|dag\s*dig\s*dug",      _re.I), "berdebar"),
    (_re.compile(r"\bdtk\s+jantung\b",                    _re.I), "detak jantung"),
    (_re.compile(r"\bgmn\s+cr\b|\bbagaimana\s+cr\b",      _re.I), "bagaimana cara"),
]


# ══════════════════════════════════════════════════════════════════════════════
# _NORM_EJAAN — regex informal → baku (dipakai oleh norm_teks)
# TIDAK membuang kata di tengah kalimat; sapaan ditangani token-level di
# _bersihkan_sapaan (awal/akhir saja).
# ══════════════════════════════════════════════════════════════════════════════
_NORM_EJAAN: list[tuple] = [
    # Kata tanya informal
    (_re.compile(r"\bgimana\b|\bgmn\b|\bgimanaa*\b", _re.I), "bagaimana"),
    (_re.compile(r"\bknp\b|\bknapaa*\b|\bngapain\b",  _re.I), "kenapa"),
    (_re.compile(r"\bkpn\b",                          _re.I), "kapan"),
    # Organ / istilah medis disingkat
    (_re.compile(r"\bjntng\b",                        _re.I), "jantung"),
    (_re.compile(r"\bdrh\b",                          _re.I), "darah"),
    (_re.compile(r"\btd\b",                           _re.I), "tekanan darah"),
    (_re.compile(r"\btkn\s+drh\b",                    _re.I), "tekanan darah"),
    (_re.compile(r"\bkolestrol\b|\bkolest\b",         _re.I), "kolesterol"),
    # Singkatan penghubung / preposisi
    (_re.compile(r"\byg\b",                           _re.I), "yang"),
    (_re.compile(r"\bdgn\b|\bdngan\b|\bdng\b",        _re.I), "dengan"),
    (_re.compile(r"\butk\b|\bu[nt]+k\b",              _re.I), "untuk"),
    (_re.compile(r"\bdr\b(?!\s*[A-Z])",               _re.I), "dari"),
    (_re.compile(r"\bkrn\b|\bkarna\b",                _re.I), "karena"),
    (_re.compile(r"\bkmn\b",                          _re.I), "kemana"),
    (_re.compile(r"\bklo\b|\bkalo\b",                 _re.I), "kalau"),
    (_re.compile(r"\bdari\s+mana\b",                  _re.I), "dari mana"),
    # Kata sifat / keterangan informal
    (_re.compile(r"\baja\b",                          _re.I), "saja"),
    (_re.compile(r"\bbgt\b|\bbangets?\b",             _re.I), "sangat"),
    (_re.compile(r"\bbkl\b|\bbakal\b",                _re.I), "akan"),
    (_re.compile(r"\bpnting\b|\bpntg\b",              _re.I), "penting"),
    (_re.compile(r"\bbnyk\b",                         _re.I), "banyak"),
    (_re.compile(r"\bsdh\b",                          _re.I), "sudah"),
    (_re.compile(r"\bblm\b",                          _re.I), "belum"),
    (_re.compile(r"\bmsh\b",                          _re.I), "masih"),
    (_re.compile(r"\btrs\b",                          _re.I), "terus"),
    (_re.compile(r"\bsmpe\b|\bsampe\b",               _re.I), "sampai"),
    (_re.compile(r"\bbbrp\b",                         _re.I), "beberapa"),
    (_re.compile(r"\bbsk\b",                          _re.I), "besok"),
    (_re.compile(r"\bkmrn\b",                         _re.I), "kemarin"),
    # Boleh informal (spesifik → umum)
    (_re.compile(r"\bblh\s*(?:ga|gak|nggak|tidak)?\b|\bboleh\s*(?:ga|gak|nggak)\b", _re.I), "boleh"),
    (_re.compile(r"\bkalo\s+boleh\b|\bkalau\s+boleh\b", _re.I), "boleh"),
    (_re.compile(r"\bga\s+boleh\b|\bgak\s+boleh\b|\bnggak\s+boleh\b|\btidak\s+boleh\b", _re.I), "dilarang"),
    # Negasi informal
    (_re.compile(r"\bgak\b|\bnggak\b|\bngga\b|\bnda\b|\bndk\b|\bga\b(?!\s+boleh)", _re.I), "tidak"),
    # Waktu informal
    (_re.compile(r"\bblkg\b|\bbelakangan\b",          _re.I), "terakhir"),
    (_re.compile(r"\bskrg\b|\bskrang\b",              _re.I), "sekarang"),
    (_re.compile(r"\bhr\s+ini\b|\bhari\s+ini\b",      _re.I), "hari ini"),
    (_re.compile(r"\bhr\b(?!\s+ini)",                 _re.I), "hari"),
    (_re.compile(r"\bmgg\b",                          _re.I), "minggu"),
    (_re.compile(r"\bbln\b",                          _re.I), "bulan"),
    (_re.compile(r"\bseminggu\s+(?:lalu|yang\s+lalu)\b", _re.I), "7 hari terakhir"),
    (_re.compile(r"\bsebulan\s+(?:lalu|yang\s+lalu)\b",  _re.I), "30 hari terakhir"),
    # Tanda baca berulang
    (_re.compile(r"[,\.]{2,}"),                       ", "),
]


def norm_teks(teks: str) -> str:
    """Terapkan semua normalisasi regex ke teks; bersihkan spasi ganda."""
    for pola, ganti in _NORM_EJAAN:
        teks = pola.sub(ganti, teks)
    return " ".join(teks.split()).strip()


# ══════════════════════════════════════════════════════════════════════════════
# Sapaan & filler — TOKEN UTUH, hanya awal/akhir
# ══════════════════════════════════════════════════════════════════════════════

# Set sapaan yang boleh dibuang di awal (token tunggal atau frasa 2 token)
_SAPAAN_AWAL_SET: set[str] = {
    "kak","dok","dokter","sus","suster","pak","bu",
    "halo","hai","hi","hello","hey","oi","woi","permisi","assalamualaikum",
    "tolong","mohon","bantu",
}
_SAPAAN_AWAL_FRASA: list[tuple[str, ...]] = [
    ("mau","nanya"), ("mau","tanya"), ("numpang","tanya"), ("numpang","nanya"),
    ("boleh","tanya"), ("boleh","nanya"), ("nanya","dong"), ("tanya","dong"),
    ("selamat","pagi"), ("selamat","siang"), ("selamat","sore"), ("selamat","malam"),
]

# Set filler yang boleh dibuang di akhir (token tunggal)
_FILLER_AKHIR_SET: set[str] = {
    "ya","yah","dong","deh","nih","sih","tuh","kok","kan","lho","loh","nah","mah",
    "makasih","thanks","thx","tq",
}
# Frasa filler di akhir
_FILLER_AKHIR_FRASA: list[tuple[str, ...]] = [
    ("terima","kasih"),
    ("mohon","bantuannya"),
    ("tolong","dijawab"),
]
# Sapaan sign-off di akhir — "dokter" tidak dibuang karena bisa jadi obyek
# ("ke dokter", "harus ke dokter"). Hanya "dok" (singkatan sapaan) dan "kak".
_SAPAAN_AKHIR_SET: set[str] = {"dok", "kak"}


def _bersihkan_sapaan_token(tokens: list[str]) -> list[str]:
    """Buang sapaan di awal dan filler di akhir, per token utuh.

    - Sapaan dibuang di AWAL selama sisa masih >= 2 token.
    - Filler/sapaan dibuang di AKHIR selama sisa masih >= 2 token.
    """
    toks = list(tokens)

    # ── awal ──────────────────────────────────────────────────────────
    changed = True
    while changed and len(toks) >= 2:
        changed = False
        tl = toks[0].lower()
        # sapaan tunggal di awal
        if tl in _SAPAAN_AWAL_SET:
            toks = toks[1:]
            changed = True
            continue
        # frasa 2-kata di awal
        if len(toks) >= 3:
            pair = (toks[0].lower(), toks[1].lower())
            for frasa in _SAPAAN_AWAL_FRASA:
                if pair == frasa:
                    toks = toks[2:]
                    changed = True
                    break

    # ── akhir ─────────────────────────────────────────────────────────
    changed = True
    while changed and len(toks) >= 2:
        changed = False
        tl = toks[-1].lower()
        # filler tunggal di akhir
        if tl in _FILLER_AKHIR_SET:
            toks = toks[:-1]
            changed = True
            continue
        # sapaan sign-off tunggal di akhir
        if tl in _SAPAAN_AKHIR_SET:
            toks = toks[:-1]
            changed = True
            continue
        # frasa 2-kata di akhir
        if len(toks) >= 3:
            pair = (toks[-2].lower(), toks[-1].lower())
            for frasa in _FILLER_AKHIR_FRASA:
                if pair == frasa:
                    toks = toks[:-2]
                    changed = True
                    break

    return toks


# ══════════════════════════════════════════════════════════════════════════════
# _koreksi_token — koreksi KETAT, tidak mengubah kata dikenal
# ══════════════════════════════════════════════════════════════════════════════

def _is_subsequence(short: str, long: str) -> bool:
    """Kembalikan True jika semua huruf `short` muncul berurutan di `long`."""
    it = iter(long)
    return all(c in it for c in short)


def _kerangka_konsonan(word: str) -> str:
    """Kerangka konsonan: buang vokal a/i/u/e/o lalu lipat konsonan berulang."""
    vokal = set("aiueo")
    tanpa_vokal = "".join(c for c in word.lower() if c not in vokal)
    # lipat berulang: "kll" → "kl"
    if not tanpa_vokal:
        return ""
    result = [tanpa_vokal[0]]
    for c in tanpa_vokal[1:]:
        if c != result[-1]:
            result.append(c)
    return "".join(result)


# Pool untuk TYPO: DAFTAR_OBAT + kunci ALIAS_OBAT + kata medis/topik inti
_TYPO_POOL: set[str] = (
    DAFTAR_OBAT
    | set(ALIAS_OBAT.keys())
    | {
        "jantung","detak","denyut","nadi","napas","oksigen","saturasi","tekanan",
        "darah","kolesterol","gejala","pusing","sesak","nyeri","dada","berdebar",
        "bradikardia","takikardia","aritmia","hipertensi","hipotensi","angina",
        "koroner","olahraga","pengukuran","tensimeter","oksimeter","laboratorium",
        "diabetes","stroke","penyakit","kondisi","keluhan",
    }
)


def _koreksi_token(token: str) -> str:
    """Koreksi satu token salah ejaan ke bentuk baku.

    Aturan ketat:
    a. Jika token sudah dikenal (KAMUS_BAKU / DAFTAR_OBAT / ALIAS) → biarkan.
    b. Jika punya angka / panjang < 3 / huruf kapital di posisi > 0 → biarkan.
    c. Token <= 4 huruf tidak pernah dikoreksi otomatis (hanya alias eksplisit).
    d. SINGKATAN (subsequence): semua huruf token muncul berurutan di satu kata
       kamus, huruf pertama sama, kerangka konsonan token == kerangka konsonan
       kandidat, len(kerangka) >= 3, len(token) >= 3, len(kandidat) >= 5.
       Kandidat UNIK: selisih panjang >= 1 dari kandidat terpendek berikutnya.
    e. TYPO: difflib ratio >= 0.85, len(token) >= 7, huruf pertama sama,
       selisih panjang <= 2. Kandidat UNIK.
       Sasaran: DAFTAR_OBAT + kunci ALIAS_OBAT + kata medis/topik inti.
       Setelah cocok ke target alias, terapkan ALIAS_OBAT.
    f. Tidak cocok → kembalikan token asli.
    """
    t = token.lower()

    # (a) sudah dikenal
    if t in _DIKENAL:
        return token

    # (b) angka / pendek / kapital tengah
    if _re.search(r"\d", t):
        return token
    if len(t) < 3:
        return token

    # (c) token <= 4 huruf: tidak dikoreksi otomatis
    if len(t) <= 4:
        return token

    # (d) SINGKATAN — subsequence + kerangka konsonan
    kerangka_t = _kerangka_konsonan(t)
    if len(t) >= 3 and len(kerangka_t) >= 3:
        best_word: str | None = None
        best_len: int = 999
        second_len: int = 999
        for word in KAMUS_BAKU:
            if len(word) < 5:
                continue
            if len(word) <= len(t):
                continue
            if word[0] != t[0]:
                continue
            if not _is_subsequence(t, word):
                continue
            if _kerangka_konsonan(word) != kerangka_t:
                continue
            if len(word) < best_len:
                second_len = best_len
                best_len = len(word)
                best_word = word
            elif len(word) < second_len:
                second_len = len(word)
        if best_word and (second_len - best_len) >= 1:
            return best_word

    # (e) TYPO — difflib, sasaran terbatas
    if len(t) >= 7:
        pool = list(_TYPO_POOL)
        matches = _difflib.get_close_matches(t, pool, n=2, cutoff=0.85)
        if matches:
            cand = matches[0]
            # huruf pertama sama, selisih panjang <= 2
            if cand[0] == t[0] and abs(len(cand) - len(t)) <= 2:
                # kandidat unik: jika ada kandidat kedua, skor harus unggul >= 0.03
                if len(matches) >= 2:
                    s1 = _difflib.SequenceMatcher(None, t, matches[0]).ratio()
                    s2 = _difflib.SequenceMatcher(None, t, matches[1]).ratio()
                    if (s1 - s2) < 0.03:
                        return token
                result = ALIAS_OBAT.get(cand, cand)
                return result

    return token


# ══════════════════════════════════════════════════════════════════════════════
# Normalisasi waktu dalam judul
# ══════════════════════════════════════════════════════════════════════════════
_WAKTU_SINGKAT: dict[str, str] = {
    "hari ini":   "hari ini",
    "minggu ini": "minggu ini",
    "bulan ini":  "bulan ini",
    "sekarang":   "saat ini",
    "terkini":    "terkini",
    "terakhir":   "terakhir",
}

def _norm_waktu(s: str) -> str:
    s = s.strip().lower()
    if s in _WAKTU_SINGKAT:
        return _WAKTU_SINGKAT[s]
    m = _re.match(r"(\d+)\s*(hari|hr|minggu|bulan)", s)
    if m:
        n, unit = m.group(1), m.group(2)
        unit = "hari" if unit == "hr" else unit
        return f"{n} {unit} terakhir"
    return s


# ══════════════════════════════════════════════════════════════════════════════
# TOPIK — untuk topik-dulu (langkah 9 pipeline)
# Kategori: makanan, minuman, obat, olahraga, gejala, alat, aplikasi
# ══════════════════════════════════════════════════════════════════════════════
_TOPIK: dict[str, tuple[str, str]] = {}  # token -> (label, kategori)
# makanan
for _w in ["nasi","roti","mi","mie","bubur","ikan","ayam","daging","telur","tempe",
           "tahu","kacang","sayur","sayuran","buah","pisang","pepaya","apel","jeruk",
           "semangka","alpukat","mangga","jambu","anggur","pir","kurma","salak",
           "melon","nanas","durian","bayam","kangkung","sawi","brokoli","wortel",
           "buncis","kol","tomat","timun","labu","singkong","ubi","jagung",
           "bawang","putih","jahe","kunyit","madu","makanan","diet"]:
    _TOPIK[_w] = (_w.title(), "makanan")
# minuman
for _w in ["kopi","teh","susu","jus","soda","air","alkohol","bir","minuman","kafein"]:
    _TOPIK[_w] = (_w.title(), "minuman")
# obat
for _w in DAFTAR_OBAT:
    _TOPIK[_w] = (_w.title(), "obat")
# olahraga
for _w in ["olahraga","senam","berenang","bersepeda","lari","jalan","yoga"]:
    _TOPIK[_w] = (_w.title(), "olahraga")
# gejala
for _w in ["pusing","sesak","nyeri","lemas","dada","berdebar","demam","batuk",
           "mual","pingsan","kesemutan","bengkak","lelah"]:
    _TOPIK[_w] = (_w.title(), "gejala")
# alat
for _w in ["sensor","oksimeter","tensimeter","termometer","alat"]:
    _TOPIK[_w] = (_w.title(), "alat")
# aplikasi
for _w in ["akun","dashboard","grafik","riwayat","chat","aplikasi"]:
    _TOPIK[_w] = (_w.title(), "aplikasi")

del _w

_MAKSUD_COCOK    = _re.compile(r"\b(cocok|baik|bagus|aman|sehat|dianjurkan)\b", _re.I)
_MAKSUD_BOLEH    = _re.compile(r"\b(boleh|bolehkah|dilarang|hindari|pantangan)\b", _re.I)
_MAKSUD_CARA     = _re.compile(r"\b(cara|tips)\b", _re.I)
_MAKSUD_EFEK     = _re.compile(r"\befek\s+samping\b", _re.I)
_MAKSUD_DOSIS    = _re.compile(r"\b(dosis|takaran)\b", _re.I)
_MAKSUD_ARTI     = _re.compile(r"\b(arti|artinya)\b", _re.I)
_MAKSUD_BERAPA   = _re.compile(r"\bberapa\s+(?:kali|mg|dosis|sehari|per\s+hari)\b", _re.I)


def _cari_topik_dan_maksud(teks: str) -> tuple[str | None, str | None, str | None]:
    """Kembalikan (label_topik, kategori, maksud) dari teks, atau None jika tidak ada."""
    tl = teks.lower()
    tokens = tl.split()
    topik_label: str | None = None
    topik_kat: str | None = None
    for tok in tokens:
        if tok in _TOPIK:
            topik_label, topik_kat = _TOPIK[tok]
            break

    maksud: str | None = None
    if _MAKSUD_BERAPA.search(tl):
        maksud = "berapa_kali"
    elif _MAKSUD_EFEK.search(tl):
        maksud = "efek_samping"
    elif _MAKSUD_DOSIS.search(tl):
        maksud = "dosis"
    elif _MAKSUD_ARTI.search(tl):
        maksud = "arti"
    elif _MAKSUD_COCOK.search(tl):
        maksud = "cocok"
    elif _MAKSUD_BOLEH.search(tl):
        maksud = "boleh"
    elif _MAKSUD_CARA.search(tl):
        maksud = "cara"

    return topik_label, topik_kat, maksud


def _template_topik(
    topik_label: str, topik_kat: str, maksud: str | None
) -> str | None:
    if maksud == "berapa_kali":
        return f"Frekuensi penggunaan {topik_label.lower()}"
    if maksud == "efek_samping":
        return f"Efek samping {topik_label.lower()}"
    if maksud == "dosis":
        # 6f: huruf kapital hanya di awal, topik_label lowercase setelah "Dosis"
        return f"Dosis {topik_label.lower()}"
    if maksud == "arti":
        return f"Arti {topik_label.lower()}"
    if maksud == "cocok":
        if topik_kat in ("makanan", "minuman"):
            return f"{topik_label} yang cocok dikonsumsi"
        if topik_kat == "olahraga":
            return "Olahraga yang aman"
    if maksud == "boleh":
        if topik_kat in ("makanan", "minuman", "obat"):
            return f"Boleh konsumsi {topik_label.lower()}?"
        if topik_kat == "olahraga":
            return "Olahraga yang aman"
    if maksud == "cara":
        return f"Cara {topik_label.lower()}"
    # topik tanpa maksud eksplisit
    if topik_kat == "gejala":
        # 6e: gejala → "Keluhan {topik}" bukan "{Topik} dan jantung"
        return f"Keluhan {topik_label.lower()}"
    if topik_kat in ("makanan", "minuman"):
        return f"{topik_label} dan jantung"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# POLA_BARU — dicek sebelum _POLA_JUDUL
# ══════════════════════════════════════════════════════════════════════════════
# Cek apakah teks mengandung topik kategori makanan/minuman/obat
def _ada_topik_mmo(teks: str) -> bool:
    """True jika teks mengandung topik makanan/minuman/obat, kata 'obat'/'minum'/'makan' generik."""
    tl = teks.lower()
    if _re.search(r'\b(?:obat|minum|makan|makanan|minuman)\b', tl):
        return True
    for tok in tl.split():
        if tok in _TOPIK and _TOPIK[tok][1] in ("makanan", "minuman", "obat"):
            return True
    return False

_POLA_BARU: list[tuple] = [
    # cepat/lambat bisa sebelum atau sesudah terlalu/sangat dalam kalimat
    (_re.compile(r"(?:detak\s+jantung|denyut)\s+(?:\w+\s+){0,3}(?:terlalu\s+|sangat\s+)?(?:tinggi|cepat|kencang)", _re.I),
     lambda m: "Detak jantung terlalu cepat"),
    (_re.compile(r"(?:detak\s+jantung|denyut)\s+(?:\w+\s+){0,3}(?:terlalu\s+|sangat\s+)?(?:rendah|lambat|pelan|lemah)", _re.I),
     lambda m: "Detak jantung terlalu lambat"),
    (_re.compile(r"(?:oksigen|saturasi|spo2)\s+(?:saya\s+)?(?:terlalu\s+)?(?:rendah|turun|kurang|menurun)", _re.I),
     lambda m: "Kadar oksigen rendah"),
    # A4: hipertensi/darah tinggi hanya berlaku bila TIDAK ada topik makan/minum/obat
    (_re.compile(r"hipertensi|darah\s+tinggi|tekanan\s+darah\s+(?:saya\s+)?(?:terlalu\s+)?tinggi", _re.I),
     lambda m: None if _ada_topik_mmo(m.string) else "Tekanan darah tinggi"),
    (_re.compile(r"hipotensi|darah\s+rendah|tekanan\s+darah\s+(?:saya\s+)?(?:terlalu\s+)?rendah", _re.I),
     lambda m: None if _ada_topik_mmo(m.string) else "Tekanan darah rendah"),
    (_re.compile(r"arti\s+(?:status\s+)?(normal|waspada|tinggi)", _re.I),
     lambda m: "Arti status " + m.group(1).lower()),
    (_re.compile(r"status\s+(?:saya|pengukuran|terakhir)", _re.I),
     lambda m: "Status pengukuran terakhir"),
    (_re.compile(r"(?:cara\s+)?(?:memakai|pakai|menggunakan|mengukur)\s+(?:alat|sensor|oksimeter)", _re.I),
     lambda m: "Cara memakai alat ukur"),
    (_re.compile(r"(?:alat|sensor)\s+(?:\w+\s+){0,3}(?:error|rusak|tidak\s+(?:terbaca|bisa|berfungsi|menyala|muncul))", _re.I),
     lambda m: "Alat ukur bermasalah"),
    (_re.compile(r"(?:hasil|angka)\s+(?:\w+\s+){0,3}(?:berubah|berbeda|naik\s+turun|tidak\s+stabil|tidak\s+konsisten)", _re.I),
     lambda m: "Hasil pengukuran berubah-ubah"),
    (_re.compile(r"(?:membuat|daftar)\s+(?:\w+\s+)?akun", _re.I),
     lambda m: "Cara membuat akun"),
    (_re.compile(r"lupa\s+(?:kata\s+sandi|password)", _re.I),
     lambda m: "Lupa kata sandi"),
    (_re.compile(r"gagal\s+jantung", _re.I),
     lambda m: "Gagal jantung"),
    (_re.compile(r"serangan\s+jantung", _re.I),
     lambda m: "Serangan jantung"),
    (_re.compile(r"jantung\s+koroner", _re.I),
     lambda m: "Jantung koroner"),
    (_re.compile(r"darurat|pertolongan\s+pertama", _re.I),
     lambda m: "Tanda darurat jantung"),
    (_re.compile(r"(?:kapan|harus)\s+(?:\w+\s+){0,3}(?:ke\s+)?(?:dokter|puskesmas|rumah\s+sakit|igd)", _re.I),
     lambda m: "Kapan harus periksa ke tenaga kesehatan"),
    (_re.compile(r"\bhamil\b|kehamilan", _re.I),
     lambda m: "Jantung saat hamil"),
    (_re.compile(r"(?:susah|sulit|kurang)\s+tidur|insomnia|begadang", _re.I),
     lambda m: "Gangguan tidur dan jantung"),
    (_re.compile(r"\b(?:stres|cemas|panik|khawatir)\b", _re.I),
     lambda m: "Stres dan jantung"),
    # Pola kopi/teh/etc DIHAPUS dari sini — topik-dulu (langkah 10) sudah menangani
    # agar "boleh minum kopi" tidak langsung ke "Kopi dan jantung" sebelum topik-dulu
    (_re.compile(r"(?:menurunkan|mengurangi)\s+berat\s+badan|obesitas|kegemukan", _re.I),
     lambda m: "Menjaga berat badan"),
    (_re.compile(r"(?:grafik|dashboard)", _re.I),
     lambda m: "Cara membaca dashboard"),
]

# ── _POLA_JUDUL lama ─────────────────────────────────────────────────────────
_POLA_JUDUL: list[tuple] = [
    (_re.compile(
        r"kondisi\s+(?:jantung|kesehatan|tubuh|saya)\b"
        r".*?(\d+\s*(?:hari|minggu|bulan)|minggu\s+ini|bulan\s+ini|hari\s+ini|sekarang|terkini|terakhir)",
        _re.I),
     lambda m: "Kondisi jantung " + _norm_waktu(m.group(1))),
    (_re.compile(r"kondisi\s+(?:jantung|kesehatan|tubuh|saya)\b", _re.I),
     lambda m: "Kondisi jantung saat ini"),
    (_re.compile(
        r"(?:hasil|data)\s+pengukuran.*?(\d+\s*(?:hari|minggu|bulan)|hari\s+ini|sekarang|terakhir)",
        _re.I),
     lambda m: "Hasil pengukuran " + _norm_waktu(m.group(1))),
    (_re.compile(r"(?:hasil|data)\s+pengukuran", _re.I),
     lambda m: "Hasil pengukuran terakhir"),
    (_re.compile(
        r"(?:tren|perkembangan|riwayat|perubahan)\s+(?:jantung|kesehatan|bpm|detak|spo2|oksigen)?"
        r".*?(\d+\s*(?:hari|minggu|bulan)|hari\s+ini|sekarang|terakhir)",
        _re.I),
     lambda m: "Tren kesehatan " + _norm_waktu(m.group(1))),
    # 6d: detak jantung + keterangan waktu (tadi pagi, kemarin, dll)
    (_re.compile(
        r"(?:(tadi\s+(?:pagi|siang|sore|malam)|kemarin|pagi|sore|malam|siang)\s+)?(?:detak\s+jantung|(?<!\w)bpm(?!\w)|denyut\s+(?:jantung|nadi))(?:\s+(?:saya\s+)?(?:berapa|tadi\s+(?:pagi|siang|sore|malam)|kemarin))?(?:\s+(tadi\s+(?:pagi|siang|sore|malam)|kemarin|pagi|sore|malam|siang))?",
        _re.I),
     lambda m: ("Detak jantung " + (m.group(1) or m.group(2)).lower().strip()) if (m.group(1) or m.group(2)) else "Detak jantung"),
    (_re.compile(r"detak\s+jantung|(?<!\w)bpm(?!\w)|denyut\s+(?:jantung|nadi)", _re.I),
     lambda m: "Detak jantung"),
    (_re.compile(r"saturasi\s+oksigen|(?<!\w)spo2(?!\w)|kadar\s+oksigen", _re.I),
     lambda m: "Saturasi oksigen"),
    (_re.compile(r"jantung\s+(?:\w+\s+){0,2}(?:berdebar|berdegup|berdetak\s+(?:cepat|kencang|tidak\s+teratur))", _re.I),
     lambda m: "Jantung sering berdebar"),
    (_re.compile(r"(?:nyeri|sakit|sesak|rasa\s+tidak\s+nyaman)\s+(?:di\s+)?dada", _re.I),
     lambda m: "Nyeri atau sesak dada"),
    # 6b: dua obat dalam satu pesan → "X dan Y" — diletakkan SEBELUM pola "boleh"
    (_re.compile(
        r"\b((?:" + "|".join(_re.escape(o) for o in sorted(DAFTAR_OBAT, key=len, reverse=True)) + r"))\b"
        r".*?\b((?:" + "|".join(_re.escape(o) for o in sorted(DAFTAR_OBAT, key=len, reverse=True)) + r"))\b",
        _re.I),
     lambda m: (m.group(1).lower().title() + " dan " + m.group(2).lower())
               if m.group(1).lower() != m.group(2).lower() else None),
    # "X boleh" hanya jika X adalah topik makanan/minuman/obat yang dikenal
    (_re.compile(r"^([\w][\w\-]{2,}(?:\s+[\w\-]+)?)\s+boleh\b", _re.I),
     lambda m: ("Boleh konsumsi " + m.group(1).strip().lower() + "?")
               if m.group(1).strip().lower() in _TOPIK and _TOPIK[m.group(1).strip().lower()][1] in ("makanan","minuman","obat")
               else None),
    # "boleh minum/makan X" hanya jika X dikenal sebagai makanan/minuman/obat
    (_re.compile(
        r"boleh\s+(?:konsumsi|minum|makan|pakai|mengonsumsi|menggunakan)\s+([\w][\w\s\-]{1,30}?)(?:\s*[,?]|$)",
        _re.I),
     lambda m: ("Boleh konsumsi " + m.group(1).strip().lower() + "?")
               if m.group(1).strip().lower().split()[0] in _TOPIK
                  and _TOPIK[m.group(1).strip().lower().split()[0]][1] in ("makanan","minuman","obat")
               else None),
    (_re.compile(
        r"([\w][\w\-]*(?:\s+[\w\-]+)?)\s+berapa\s+(?:kali|mg|dosis|sehari|per\s+hari)",
        _re.I),
     lambda m: "Frekuensi penggunaan " + m.group(1).strip().lower()),
    # A5: "berapa gelas/sendok/porsi" → Takaran, bukan Dosis
    (_re.compile(
        r"(?:minum|makan|konsumsi|pakai)?\s*([\w][\w\s\-]{1,25}?)\s+berapa\s+(?:gelas|sendok|porsi|cangkir|mangkuk)",
        _re.I),
     lambda m: "Takaran " + m.group(1).strip().lower()),
    (_re.compile(
        r"(?:dosis|takaran|frekuensi|minum|pakai)\s+([\w][\w\s\-]{1,25}?)\s+(?:berapa|bagaimana|kapan|sehari|per\s+hari)",
        _re.I),
     # 6f: lowercase setelah "Dosis"
     lambda m: "Dosis " + m.group(1).strip().lower()),
    (_re.compile(r"efek\s+samping\s+([\w][\w\s\-]{1,25}?)(?:\s+(?:itu|ini|adalah|bagi|untuk|pada|ke)|[,?]|$)", _re.I),
     lambda m: "Efek samping " + m.group(1).strip().lower()),
    (_re.compile(r"interaksi\s+(?:obat\s+)?([\w][\w\s\-]{1,25}?)(?:\s+(?:dengan|dan)\s+([\w][\w\s\-]{1,20}))?", _re.I),
     lambda m: "Interaksi " + m.group(1).strip().lower() + (" dan " + m.group(2).strip().lower() if m.group(2) else "")),
    (_re.compile(
        r"sayur(?:an)?\s+(?:apa\s+)?(?:yang\s+)?(?:cocok|boleh|baik|bagus|dianjurkan|disarankan|direkomendasikan)\s*(?:untuk\s+(?:jantung|kesehatan|saya))?",
        _re.I),
     lambda m: "Sayuran yang baik untuk jantung"),
    (_re.compile(
        r"(makanan|minuman|buah|diet)\s+(?:apa\s+)?(?:yang\s+)?(?:cocok|boleh|baik|bagus|dianjurkan|disarankan|direkomendasikan)",
        _re.I),
     lambda m: m.group(1).strip().title() + " yang cocok dikonsumsi"),
    (_re.compile(
        r"(makanan|minuman|buah|sayur(?:an)?)\s+(?:apa\s+)?(?:yang\s+)?(?:harus\s+)?(?:dihindari|tidak\s+boleh|dilarang|berbahaya)",
        _re.I),
     lambda m: m.group(1).strip().title() + " yang harus dihindari"),
    (_re.compile(r"olahraga\s+(?:\w+\s+){0,3}(?:yang\s+)?(?:cocok|boleh|baik|bagus|aman|dianjurkan|disarankan)", _re.I),
     lambda m: "Olahraga yang aman"),
    (_re.compile(r"olahraga\s+(?:\w+\s+){0,3}(?:yang\s+)?(?:dilarang|tidak\s+boleh|berbahaya|dihindari)", _re.I),
     lambda m: "Olahraga yang dihindari"),
    (_re.compile(r"\b(?:risiko|bahaya|ancaman|potensi)\b\s+([\w][\w\s]{1,25}?)(?:\s+(?:itu|ini|bagi|pada|ke|untuk)|[,?]|$)", _re.I),
     lambda m: "Risiko " + m.group(1).strip().lower()),
    # A3: "X berbahaya bagi jantung" — ambil 1-2 kata tepat sebelum "berbahaya",
    # strip kata tanya dari awal grup
    (_re.compile(
        r"(?:(?:apakah|apa|mengapa|kenapa)\s+)?(\w+(?:\s+\w+)?)\s+(?:berbahaya|berisiko|membahayakan)(?:\s+(?:bagi|untuk|pada)\s+(?:jantung|kesehatan|tubuh))?",
        _re.I),
     lambda m: ("Risiko " + m.group(1).strip().lower())
               if m.group(1).strip().lower() not in ("apakah","apa","mengapa","kenapa","ini","itu","yang","jantung","saya")
               else None),
    # A4: "obat darah tinggi apa yang aman" / "obat hipertensi" — sebelum hipertensi pattern
    (_re.compile(
        r"\bobat\b(?:\s+\w+){0,4}\s+(?:hipertensi|darah\s+tinggi|tekanan\s+darah\s+tinggi)",
        _re.I),
     lambda m: "Obat tekanan darah tinggi"),
    # A4: X untuk tekanan darah tinggi / kolesterol tinggi
    (_re.compile(
        r"(makanan|minuman)\s+(?:pantangan|untuk|bagi|penderita)\s+(?:hipertensi|darah\s+tinggi|tekanan\s+darah\s+tinggi)",
        _re.I),
     lambda m: m.group(1).strip().title() + " untuk tekanan darah tinggi"),
    (_re.compile(
        r"(?:hipertensi|darah\s+tinggi|tekanan\s+darah\s+tinggi)\s+(?:minum|makan|konsumsi)\s+(?:apa|yang)?",
        _re.I),
     lambda m: ("Minuman untuk tekanan darah tinggi") if "minum" in m.group(0).lower() else ("Makanan untuk tekanan darah tinggi")),
    # "minum apa untuk darah tinggi" / "tensi tinggi minum apa"
    (_re.compile(
        r"(?:minum|makan)\s+(?:[\w\s]{0,20}?)\s*(?:untuk|buat)\s+(?:hipertensi|darah\s+tinggi|tekanan\s+darah\s+tinggi)",
        _re.I),
     lambda m: ("Minuman untuk tekanan darah tinggi") if "minum" in m.group(0).lower() else ("Makanan untuk tekanan darah tinggi")),
    (_re.compile(
        r"(?:hipertensi|darah\s+tinggi|tekanan\s+darah\s+tinggi)\s+(?:\w+\s+)?minum\s+(?:apa)?",
        _re.I),
     lambda m: "Minuman untuk tekanan darah tinggi"),
    # A5: kolesterol tinggi + makan/minuman apa
    (_re.compile(
        r"(makanan|minuman)\s+(?:untuk|penderita|bagi)\s+kolesterol\s+tinggi"
        r"|kolesterol\s+tinggi\s+(?:makan|minum)\s+(?:apa|yang)?",
        _re.I),
     lambda m: ("Minuman untuk kolesterol tinggi") if _re.search(r"minum", m.group(0), _re.I) else ("Makanan untuk kolesterol tinggi")),
    # A2: "apa itu X" / "apakah itu X" / "apa yang dimaksud X" → "Pengertian X"
    (_re.compile(
        r"^(?:apa|apakah)\s+(?:itu|yang\s+dimaksud(?:\s+dengan)?)\s+([\w][\w\s\-]{1,30}?)$",
        _re.I),
     lambda m: "Pengertian " + " ".join(m.group(1).strip().lower().split()[:3])),
    (_re.compile(r"(?:cara|tips|langkah|panduan)\s+(?:untuk\s+|agar\s+)?([\w][\w\s\-]{2,30}?)(?:\s+(?:yang|agar|supaya|dengan)|[,?]|$)", _re.I),
     lambda m: "Cara " + m.group(1).strip().lower()),
    (_re.compile(r"(?:gejala|tanda(?:-tanda)?)\s+([\w][\w\s\-]{2,25}?)(?:\s+(?:itu|ini|adalah|bagi|pada|ke)|[,?]|$)", _re.I),
     lambda m: "Gejala " + m.group(1).strip().lower()),
    (_re.compile(r"(?:arti|maksud|pengertian|definisi)\s+(?:dari\s+|kata\s+)?([\w][\w\s\-]{1,25}?)(?:\s+(?:itu|ini|adalah)|[,?]|$)", _re.I),
     lambda m: "Pengertian " + m.group(1).strip().lower()),
    (_re.compile(
        r"jantung\b.*?(\d+\s*(?:hari|minggu|bulan)|hari\s+ini|sekarang|terkini|terakhir)",
        _re.I),
     lambda m: "Kondisi jantung " + _norm_waktu(m.group(1))),
]

# ── fallback stopwords / filler ───────────────────────────────────────────────
_STOPWORDS_AWAL = _re.compile(
    r"^(?:"
    r"bagaimana(?:\s+(?:kondisi|cara|status|hasil|dengan))?"
    r"|berapa(?:\s+(?:kali|lama|hari|minggu|bulan))?"
    r"|apakah(?:\s+(?:ini|itu|saya|normal|berbahaya|boleh))?"
    r"|apa(?:\s+(?:saja|itu|ini|yang|arti|itu\s+artinya))?"
    r"|kenapa(?:\s+(?:saya|bisa))?"
    r"|mengapa(?:\s+(?:saya|bisa))?"
    r"|kapan(?:\s+(?:saya|harus|bisa))?"
    r"|siapa(?:\s+(?:yang))?"
    r"|bolehkah(?:\s+saya)?"
    r"|bisakah(?:\s+saya)?"
    r"|boleh(?:\s+(?:saya|tidak|kah))?"
    r"|tolong(?:\s+(?:jelaskan|bantu|ceritakan))?"
    r"|mohon(?:\s+(?:jelaskan|bantu|ceritakan))?"
    r"|jelaskan(?:\s+(?:tentang|mengenai))?"
    r"|ceritakan(?:\s+(?:tentang|mengenai))?"
    r"|saya\s+(?:ingin\s+(?:tahu|bertanya)|mau\s+tanya|mau\s+tahu)\s+(?:tentang|mengenai|soal)?"
    r"|apa\s+yang\s+(?:dimaksud\s+dengan|terjadi\s+(?:pada|dengan)|harus\s+saya)"
    r"|saya\s+(?:mau|ingin|perlu|harus)\s+(?:tahu|tanya)\s*"
    r")\s+",
    _re.IGNORECASE,
)
_FILLER_AKHIR_RE = _re.compile(
    r"(?:"
    r"\s+(?:untuk|buat|bagi)\s+(?:saya|pasien\s+saya|kesehatan\s+saya)"
    r"|\s+(?:itu|ini|ya|yah|dong|deh|nih|sih|kan|kok)(?=\s*$)"
    r"|\s+(?:apakah\s+)?normal(?=\s*$)"
    r")\s*$",
    _re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
# _judul_layak — cek kelayakan judul
# ══════════════════════════════════════════════════════════════════════════════

def _judul_layak(judul: str) -> bool:
    """Kembalikan True jika judul memenuhi syarat kelayakan."""
    if not judul:
        return False
    tokens = judul.split()
    if len(tokens) < 2:
        # boleh 1 kata hanya jika kata topik dikenal
        return bool(tokens) and tokens[0].lower() in KAMUS_BAKU
    first = tokens[0].lower()
    # kata tanya boleh di awal jika judul >= 3 kata (poin 6c)
    if first in _KATA_FUNGSI:
        # kata tanya boleh bila judul >= 3 kata
        if first in _KATA_TANYA_BOLEH_AWAL and len(tokens) >= 3:
            pass  # diizinkan
        else:
            return False
    if tokens[-1].lower() in _KATA_FUNGSI:
        return False
    # token <= 2 huruf yang bukan kata kamus dan bukan angka
    for tok in tokens:
        if len(tok) <= 2 and not tok.isdigit() and tok.lower() not in KAMUS_BAKU:
            return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# _setia — cek bahwa setiap kata isi judul bisa dilacak ke pesan asli
# ══════════════════════════════════════════════════════════════════════════════

def _setia(judul: str, pesan_asli: str, balasan_ai: str | None = None) -> bool:
    """Kembalikan True jika setiap kata isi judul berasal dari pesan/templat/AI."""
    # Bangun set token ternormalisasi dari pesan asli (setelah alias)
    def _norm_token_set(teks: str) -> set[str]:
        hasil = set()
        # Terapkan REGEX_TAMBAHAN dulu agar "4hr" → "4 hari" (angka terpisah)
        teks_norm = teks.lower()
        for pola, ganti in _REGEX_TAMBAHAN:
            teks_norm = pola.sub(ganti, teks_norm)
        for tok in teks_norm.split():
            hasil.add(tok)
            hasil.add(ALIAS_EJAAN.get(tok, tok))
            hasil.add(ALIAS_OBAT.get(tok, tok))
            # juga tambahkan token asli sebelum normalisasi
        for tok in teks.lower().split():
            hasil.add(tok)
            hasil.add(ALIAS_EJAAN.get(tok, tok))
            hasil.add(ALIAS_OBAT.get(tok, tok))
        return hasil

    pesan_tokens = _norm_token_set(pesan_asli)
    ai_tokens = _norm_token_set(balasan_ai) if balasan_ai else set()
    all_source = pesan_tokens | ai_tokens

    for tok in judul.split():
        tl = tok.lower()
        if tl in _KATA_TEMPLAT:
            continue
        if tl in all_source:
            continue
        # ratio >= 0.85 dengan salah satu token sumber
        found = False
        for src in all_source:
            if len(src) >= 3 and _difflib.SequenceMatcher(None, tl, src).ratio() >= 0.85:
                found = True
                break
        if not found:
            return False
    return True


def _judul_aman(pesan: str) -> str:
    """Judul darurat: alias eksplisit + sapaan/filler awal-akhir token, kapital."""
    tokens = pesan.split()
    normed = []
    for tok in tokens:
        tl = tok.lower()
        normed.append(ALIAS_EJAAN.get(tl, ALIAS_OBAT.get(tl, tok)))
    normed = _bersihkan_sapaan_token(normed)
    if not normed:
        return "Percakapan baru"
    result = " ".join(normed)
    result = result[0].upper() + result[1:]
    return result[:45].rstrip(",. ") or "Percakapan baru"


def _potong_45(s: str) -> str:
    """Potong pada batas kata agar tidak melebihi 45 karakter."""
    if len(s) <= 45:
        return s
    # potong di spasi terakhir sebelum karakter ke-45
    cut = s[:45]
    idx = cut.rfind(" ")
    if idx > 0:
        cut = cut[:idx]
    return cut.rstrip(",. ")


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE UTAMA
# ══════════════════════════════════════════════════════════════════════════════

def buat_judul(pesan: str, balasan_ai: str | None = None) -> str:
    """Buat judul ringkas dari pertanyaan pertama user.

    Pipeline:
    1.  Rapikan → cek tak bermakna
    2.  Alias eksplisit (token-level)
    3.  Buang sapaan/filler awal-akhir (token utuh)
    4.  norm_teks (regex informal)
    5.  Koreksi token ketat
    6.  norm_teks lagi
    7.  POLA_BARU → _POLA_JUDUL
    8.  Topik-dulu (dengan fallback ke balasan_ai)
    9.  Fallback kalimat
    10. _judul_layak → _setia → potong 45
    """
    pesan_asli = pesan  # dipakai oleh _setia dan _judul_aman

    # ── 1a. Rapikan spasi & buang tanda baca akhir ────────────────────
    teks = " ".join(pesan.split()).strip()
    teks = _re.sub(r"[?!,\.]+$", "", teks).strip()
    if not teks:
        return "Percakapan baru"

    # ── 1b. Cek pesan tak bermakna ────────────────────────────────────
    teks_lc = teks.lower()
    huruf_saja = _re.sub(r"[^a-z]", "", teks_lc)
    if len(huruf_saja) < 4:
        return "Percakapan baru"
    if len(set(teks_lc.replace(" ", ""))) <= 1:
        return "Percakapan baru"
    tokens_lc = teks_lc.split()
    if tokens_lc and all(t in _SAPAAN_UJI for t in tokens_lc):
        return "Percakapan baru"
    if len(tokens_lc) == 1:
        t1 = tokens_lc[0]
        if (len(t1) >= 4 and t1 not in KAMUS_BAKU and t1 not in DAFTAR_OBAT
                and t1 not in ALIAS_EJAAN):
            vokal = sum(1 for c in t1 if c in "aeiou")
            if vokal == 0 or (vokal / len(t1)) < 0.25:
                return "Percakapan baru"

    # ── 2. Pangkas huruf berulang ─────────────────────────────────────
    teks = _re.sub(r"(.)\1{2,}", r"\1", teks)

    # ── 3. REGEX_TAMBAHAN ─────────────────────────────────────────────
    for pola, ganti in _REGEX_TAMBAHAN:
        teks = pola.sub(ganti, teks)

    # ── 4. Alias token-level (ALIAS_EJAAN + ALIAS_OBAT) ───────────────
    def _terapkan_alias(s: str) -> str:
        out = []
        for tok in s.split():
            tl = tok.lower()
            if tl in ALIAS_EJAAN:
                out.append(ALIAS_EJAAN[tl])
            elif tl in ALIAS_OBAT:
                out.append(ALIAS_OBAT[tl])
            else:
                out.append(tok)
        return " ".join(out)

    teks = _terapkan_alias(teks)

    # ── 5. Buang sapaan/filler awal-akhir (token utuh) ─────────────────
    toks = teks.split()
    toks = _bersihkan_sapaan_token(toks)
    if not toks:
        return "Percakapan baru"
    teks = " ".join(toks)

    # ── 6. norm_teks ──────────────────────────────────────────────────
    teks = norm_teks(teks)

    # ── 7. Koreksi token ketat ────────────────────────────────────────
    def _koreksi_semua(s: str) -> str:
        tokens = s.split()
        hasil = []
        for i, tok in enumerate(tokens):
            # token kapital di tengah kalimat = kemungkinan nama
            if i > 0 and tok and tok[0].isupper():
                hasil.append(tok)
            else:
                hasil.append(_koreksi_token(tok))
        return " ".join(hasil)

    teks = _koreksi_semua(teks)

    # ── 8. norm_teks lagi ─────────────────────────────────────────────
    teks = norm_teks(teks)
    teks = _re.sub(r"[?!,\.]+$", "", teks).strip()
    if not teks:
        return "Percakapan baru"

    # ── 9. POLA_BARU → _POLA_JUDUL ────────────────────────────────────
    for pola, pembuat in _POLA_BARU:
        m = pola.search(teks)
        if m:
            _raw = pembuat(m)
            if _raw is None:
                continue
            judul = _raw.strip()
            if judul and _judul_layak(judul) and _setia(judul, pesan_asli, balasan_ai):
                return _potong_45(judul[0].upper() + judul[1:])

    for pola, pembuat in _POLA_JUDUL:
        m = pola.search(teks)
        if m:
            _raw = pembuat(m)
            if _raw is None:
                continue
            judul = _raw.strip()
            if judul and _judul_layak(judul) and _setia(judul, pesan_asli, balasan_ai):
                return _potong_45(judul[0].upper() + judul[1:])

    # ── 10. Topik-dulu ────────────────────────────────────────────────
    topik_label, topik_kat, maksud = _cari_topik_dan_maksud(teks)
    if topik_label is None and balasan_ai:
        ai_norm = norm_teks(_terapkan_alias(" ".join(balasan_ai.split()[:60])))
        topik_label, topik_kat, maksud = _cari_topik_dan_maksud(ai_norm)
    if topik_label is not None:
        kandidat = _template_topik(topik_label, topik_kat, maksud)  # type: ignore[arg-type]
        if kandidat and _judul_layak(kandidat) and _setia(kandidat, pesan_asli, balasan_ai):
            return _potong_45(kandidat[0].upper() + kandidat[1:])

    # ── 11. Fallback kalimat ──────────────────────────────────────────
    # Coba teks asli (setelah normalisasi) terlebih dulu — mempertahankan
    # kata tanya (kapan, bagaimana, dll) bila judul >= 3 kata (poin 6c)
    _teks_coba = _FILLER_AKHIR_RE.sub("", teks).strip() or teks
    _teks_coba = _teks_coba[0].upper() + _teks_coba[1:]
    _judul_coba = _potong_45(_teks_coba)
    if _judul_layak(_judul_coba) and _setia(_judul_coba, pesan_asli, balasan_ai):
        return _judul_coba

    bersih = _STOPWORDS_AWAL.sub("", teks, count=1).strip()
    if not bersih:
        bersih = teks
    bersih = _FILLER_AKHIR_RE.sub("", bersih).strip()
    if not bersih:
        bersih = teks
    bersih = bersih[0].upper() + bersih[1:]
    judul = _potong_45(bersih)
    if _judul_layak(judul) and _setia(judul, pesan_asli, balasan_ai):
        return judul

    # ── 12. Judul kata kunci (maks 3 kata isi dikenal, urutan asli) ───
    kata_isi = [
        tok for tok in teks.split()
        if tok.lower() in KAMUS_BAKU and tok.lower() not in _KATA_KUNCI_EXCLUDE
    ][:3]
    if kata_isi:
        judul = " ".join(kata_isi)
        judul = judul[0].upper() + judul[1:]
        if _judul_layak(judul):
            return _potong_45(judul)

    # ── 13. Judul aman (tanpa koreksi otomatis) ───────────────────────
    judul = _judul_aman(pesan_asli)
    if _judul_layak(judul):
        return _potong_45(judul)

    return "Percakapan baru"


# ══════════════════════════════════════════════════════════════════════════════
# Alat uji CLI: python judul.py "pesan user" ["balasan ai"]
# Mencetak teks setelah SETIAP tahap pipeline.
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys as _sys

    _argv = _sys.argv[1:]
    _pesan = _argv[0] if _argv else input("Pesan: ")
    _balasan = _argv[1] if len(_argv) > 1 else None

    print(f"\nINPUT  : {_pesan!r}")
    if _balasan:
        print(f"BALASAN: {_balasan!r}")
    print()

    _t = " ".join(_pesan.split()).strip()
    _t = _re.sub(r"[?!,\.]+$", "", _t).strip()
    print(f"[1] rapikan/buang akhir  : {_t!r}")

    _huruf = _re.sub(r"[^a-z]", "", _t.lower())
    _tokens_lc = _t.lower().split()
    print(f"[1b] huruf_saja len={len(_huruf)}, sapaan_semua={all(x in _SAPAAN_UJI for x in _tokens_lc)}")

    _t = _re.sub(r"(.)\1{2,}", r"\1", _t)
    print(f"[2] huruf berulang       : {_t!r}")

    for _p, _g in _REGEX_TAMBAHAN:
        _nt = _p.sub(_g, _t)
        if _nt != _t:
            print(f"[3] REGEX_TAMBAHAN        : {_t!r} -> {_nt!r}")
            _t = _nt
    print(f"[3] setelah REGEX        : {_t!r}")

    _tprev = _t
    _out = []
    for _tok in _t.split():
        _tl = _tok.lower()
        if _tl in ALIAS_EJAAN:
            _out.append(ALIAS_EJAAN[_tl])
        elif _tl in ALIAS_OBAT:
            _out.append(ALIAS_OBAT[_tl])
        else:
            _out.append(_tok)
    _t = " ".join(_out)
    print(f"[4] alias token          : {_t!r}")
    for _a, _b2 in zip(_tprev.split(), _t.split()):
        if _a != _b2:
            print(f"     '{_a}' -> '{_b2}'")

    _toks = _t.split()
    _toks2 = _bersihkan_sapaan_token(_toks)
    _t = " ".join(_toks2)
    print(f"[5] bersihkan_sapaan     : {_t!r}")

    _t = norm_teks(_t)
    print(f"[6] norm_teks            : {_t!r}")

    _out2 = []
    for _i, _tok in enumerate(_t.split()):
        if _i > 0 and _tok and _tok[0].isupper():
            _out2.append(_tok)
            print(f"[7] token[{_i}] '{_tok}' -> SKIP (kapital)")
        else:
            _res = _koreksi_token(_tok)
            if _res != _tok:
                print(f"[7] token[{_i}] '{_tok}' -> '{_res}'  *** CHANGED ***")
            _out2.append(_res)
    _t = " ".join(_out2)
    print(f"[7] koreksi token        : {_t!r}")

    _t = norm_teks(_t)
    print(f"[8] norm_teks lagi       : {_t!r}")

    print()
    print(f"HASIL AKHIR: {buat_judul(_pesan, _balasan)!r}")
