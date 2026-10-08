#include <Wire.h>
#include <math.h>
#include <string.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "MAX30105.h"
#include "secrets.h"

#define DRY_RUN 0
#define DEBUG_RAW 1

#define LED_PIN 2
#define SDA_PIN 21
#define SCL_PIN 22

#define SENSOR_LED_BRIGHTNESS 80
#define SENSOR_ADC_RANGE 16384
#define FINGER_IR_THRESHOLD 10000
#define FINGER_STOP_THRESHOLD 3000

#define HEARTBEAT_MS 5000UL
#define STATUS_TIMEOUT_MS 1500

#define SAMPLE_MS 10
#define SKIP_SAMPLES 400
#define MEASURE_TIMEOUT_MS 30000UL
#define RING_SIZE 1024
#define MAX_SAMPLES 2500
#define FAILFAST_SAMPLES 1100
#define FAILFAST_MIN_BEATS 4

#define MAX_BEATS 14
#define MAX_INTERVALS 13
#define NEEDED_BEATS 6
#define MIN_GOOD_PERCENT 60
#define BEAT_MIN_MS 300
#define BEAT_MAX_MS 1500
#define INTERVAL_TOLERANCE 0.25
#define REFRACTORY_RATIO 0.6

#define BP_LP_ALPHA 0.25
#define BP_BASE_ALPHA 0.02
#define AC_WIN 200
#define PEAK_RATIO 0.35
#define MIN_SWING 4.0

#define AUTO_WIN 500
#define AUTO_LAG_MIN 30
#define AUTO_LAG_MAX 150
#define AUTO_MIN_QUALITY 0.55
#define AUTO_MIN_QUALITY_SOLO 0.65
#define EVAL_START_SAMPLES 900
#define EVAL_STEP 100
#define BPM_AGREE_ABS 6
#define BPM_AGREE_REL 0.10
#define STABLE_BPM_TOL 4
#define STABLE_SPO2_TOL 2

#define CORR_WIN 500
#define MIN_RED_IR_CORR 0.80

#define MIN_PI 0.005
#define MAX_PI 0.06
#define MIN_VALID_R 4
#define R_OUTLIER 0.15
#define MAX_R_SPREAD 0.30
#define R_MIN 0.2
#define R_MAX 1.5

#define SPO2_FORMULA 1
#define USE_LOCAL_SPO2_CALIBRATION 0
#define LOCAL_SPO2_A 1.0
#define LOCAL_SPO2_B 0.0
#define USE_BPM_CALIBRATION 0
#define BPM_CAL_A 1.0
#define BPM_CAL_B 0.0

#define BPM_MIN 40
#define BPM_MAX 200

#define COOLDOWN_MS 6000UL

MAX30105 sensor;

enum Fail {
  FAIL_NONE,
  FAIL_NO_FINGER,
  FAIL_SENSOR,
  FAIL_TIMEOUT,
  FAIL_LOW_QUALITY
};

Fail lastFail = FAIL_NONE;
const char *idleCode = "siap";

void blinkLed(int times, int ms) {
  for (int i = 0; i < times; i++) {
    digitalWrite(LED_PIN, HIGH);
    delay(ms);
    digitalWrite(LED_PIN, LOW);
    delay(ms);
  }
}

int medianOf(const int *a, int n) {
  int b[MAX_INTERVALS];

  for (int i = 0; i < n; i++) b[i] = a[i];

  for (int i = 1; i < n; i++) {
    int key = b[i];
    int j = i - 1;

    while (j >= 0 && b[j] > key) {
      b[j + 1] = b[j];
      j--;
    }

    b[j + 1] = key;
  }

  if (n % 2) return b[n / 2];

  return (b[n / 2 - 1] + b[n / 2] + 1) / 2;
}

double medianD(const double *a, int n) {
  double b[MAX_BEATS + 2];

  for (int i = 0; i < n; i++) b[i] = a[i];

  for (int i = 1; i < n; i++) {
    double key = b[i];
    int j = i - 1;

    while (j >= 0 && b[j] > key) {
      b[j + 1] = b[j];
      j--;
    }

    b[j + 1] = key;
  }

  if (n % 2) return b[n / 2];

  return (b[n / 2 - 1] + b[n / 2]) / 2.0;
}

bool readOne(uint32_t &red, uint32_t &ir) {
  uint32_t start = millis();

  while (!sensor.available()) {
    sensor.check();

    if (millis() - start > 1000) return false;

    delay(1);
  }

  red = sensor.getFIFORed();
  ir = sensor.getFIFOIR();
  sensor.nextSample();

  return true;
}

void flushSensor() {
  sensor.clearFIFO();
  delay(30);
  sensor.check();

  while (sensor.available()) sensor.nextSample();
}

bool fingerPresent() {
  return sensor.getIR() > FINGER_IR_THRESHOLD;
}

void waitFingerRemoved() {
  uint32_t clearSince = 0;

  while (true) {
    if (sensor.getIR() > FINGER_STOP_THRESHOLD) {
      clearSince = 0;
    } else {
      if (clearSince == 0) clearSince = millis();

      if (millis() - clearSince > 1000) return;
    }

    delay(100);
  }
}

bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  Serial.printf("Menghubungkan WiFi \"%s\"", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint32_t t = millis();

  while (WiFi.status() != WL_CONNECTED && millis() - t < 20000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi tersambung. IP: %s\n",
                  WiFi.localIP().toString().c_str());
    return true;
  }

  Serial.println("\nWiFi gagal tersambung.");
  return false;
}

void reportStatus(const char *kode) {
#if !DRY_RUN
  if (WiFi.status() != WL_CONNECTED) return;

  String url = SERVER_URL;
  int p = url.indexOf("/api/sensor-data");

  if (p < 0) return;

  url = url.substring(0, p) + "/api/device-status";

  char body[64];
  snprintf(body, sizeof(body), "{\"kode\":\"%s\"}", kode);

  HTTPClient http;
  WiFiClient plain;
  WiFiClientSecure secure;
  bool ok;

  if (url.startsWith("https://")) {
    secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);
  }

  if (!ok) return;

  http.setTimeout(STATUS_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("x-api-key", API_KEY);
  http.POST(body);
  http.end();
#endif
}

int sendReading(int bpm, int spo2) {
  if (!connectWifi()) return -1;

  char body[48];
  snprintf(body, sizeof(body),
           "{\"bpm\":%d,\"spo2\":%d}", bpm, spo2);

  String url = SERVER_URL;
  HTTPClient http;
  WiFiClient plain;
  WiFiClientSecure secure;
  bool ok;

  if (url.startsWith("https://")) {
    secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(plain, url);
  }

  if (!ok) return -1;

  http.setTimeout(10000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("x-api-key", API_KEY);

  int code = http.POST(body);
  http.end();

  return code;
}

bool explainCode(int code) {
  switch (code) {
    case 200:
      Serial.println("Terkirim. Data diterima server, analisis berjalan di latar belakang.");
      return false;

    case 401:
      Serial.println("GAGAL 401: API key salah.");
      return false;

    case 409:
      Serial.println("GAGAL 409: tidak ada pengukuran aktif. Tekan Mulai Pengukuran di dashboard.");
      return false;

    case 422:
      Serial.println("GAGAL 422: nilai ditolak server.");
      return false;

    case 429:
      Serial.println("GAGAL 429: terlalu cepat.");
      return true;

    case -1:
      Serial.println("GAGAL: tidak bisa terhubung ke server.");
      return true;

    default:
      if (code >= 500) {
        Serial.printf("GAGAL %d: server bermasalah.\n", code);
        return true;
      }

      Serial.printf("GAGAL %d.\n", code);
      return false;
  }
}

double formulaValue(double R) {
#if SPO2_FORMULA == 1
  return -45.060 * R * R + 30.354 * R + 94.845;
#elif SPO2_FORMULA == 2
  return 110.0 - 25.0 * R;
#else
  return 104.0 - 17.0 * R;
#endif
}

bool spo2FromR(double R, int &spo2) {
  if (R < R_MIN || R > R_MAX) return false;

  double value = formulaValue(R);

#if USE_LOCAL_SPO2_CALIBRATION
  value = LOCAL_SPO2_A * value + LOCAL_SPO2_B;
#endif

  if (value < 70) return false;
  if (value > 100) value = 100;

  spo2 = (int)(value + 0.5);
  return true;
}

double smoothAt(const uint32_t *ring, uint32_t i) {
  double s = 0;

  for (int k = -2; k <= 2; k++) {
    s += ring[((int)i + k) % RING_SIZE];
  }

  return s / 5.0;
}

bool beatRatio(const uint32_t *redRing, const uint32_t *irRing, uint32_t n,
               uint32_t s, uint32_t e, double &R, double &perf) {
  if (e <= s) return false;

  uint32_t len = e - s + 1;

  if (len < 30 || len > 170) return false;
  if (n - s >= RING_SIZE - 5) return false;

  uint32_t a = s + 2;
  uint32_t b = e - 2;
  double span = (double)(b - a);

  if (span < 10) return false;

  double r0 = smoothAt(redRing, a), r1 = smoothAt(redRing, b);
  double i0 = smoothAt(irRing, a), i1 = smoothAt(irRing, b);

  double rMin = 1e12, rMax = -1e12, iMin = 1e12, iMax = -1e12;
  double rSum = 0, iSum = 0;
  int cnt = 0;

  for (uint32_t i = a; i <= b; i++) {
    double t = (double)(i - a) / span;
    double sr = smoothAt(redRing, i);
    double si = smoothAt(irRing, i);
    double dr = sr - (r0 + (r1 - r0) * t);
    double di = si - (i0 + (i1 - i0) * t);

    if (dr < rMin) rMin = dr;
    if (dr > rMax) rMax = dr;
    if (di < iMin) iMin = di;
    if (di > iMax) iMax = di;

    rSum += sr;
    iSum += si;
    cnt++;
  }

  double dcR = rSum / cnt;
  double dcI = iSum / cnt;
  double acR = rMax - rMin;
  double acI = iMax - iMin;

  if (dcR <= 0 || dcI <= 0 || acR <= 0 || acI <= 0) return false;

  perf = acI / dcI;

  if (perf < MIN_PI || perf > MAX_PI) return false;

  R = (acR / dcR) / perf;

  return R >= R_MIN && R <= R_MAX;
}

bool aggregateR(const double *beatR, const double *beatPI, const bool *beatRok, int nBeat,
                double &Rout, double &piOut, int &used) {
  double vals[MAX_BEATS], pis[MAX_BEATS];
  int nv = 0;

  for (int i = 0; i < nBeat; i++) {
    if (beatRok[i]) {
      vals[nv] = beatR[i];
      pis[nv] = beatPI[i];
      nv++;
    }
  }

  if (nv < MIN_VALID_R) {
#if DEBUG_RAW
    Serial.printf("  [spo2] ditolak: R valid hanya %d (minimal %d)\n", nv, MIN_VALID_R);
#endif
    return false;
  }

  double med = medianD(vals, nv);
  double kept[MAX_BEATS], keptPI[MAX_BEATS];
  int nk = 0;
  double mn = 1e9, mx = -1e9;

  for (int i = 0; i < nv; i++) {
    if (fabs(vals[i] - med) <= R_OUTLIER) {
      kept[nk] = vals[i];
      keptPI[nk] = pis[i];
      if (vals[i] < mn) mn = vals[i];
      if (vals[i] > mx) mx = vals[i];
      nk++;
    }
  }

  if (nk < MIN_VALID_R || nk * 100 < nv * 60) {
#if DEBUG_RAW
    Serial.printf("  [spo2] ditolak: R tidak konsisten antar denyut (%d dari %d dekat median %.3f)\n", nk, nv, med);
#endif
    return false;
  }

  if (mx - mn > MAX_R_SPREAD) {
#if DEBUG_RAW
    Serial.printf("  [spo2] ditolak: sebaran R terlalu lebar (%.3f)\n", mx - mn);
#endif
    return false;
  }

  Rout = medianD(kept, nk);
  piOut = medianD(keptPI, nk);
  used = nk;

  return true;
}

double redIrCorr(const float *aR, const float *aI, uint32_t n, int win) {
  if (n < (uint32_t)win) return 0;

  uint32_t start = n - win;
  double sRI = 0, sRR = 0, sII = 0;

  for (int i = 0; i < win; i++) {
    double r = aR[(start + i) % RING_SIZE];
    double q = aI[(start + i) % RING_SIZE];

    sRI += r * q;
    sRR += r * r;
    sII += q * q;
  }

  if (sRR <= 0 || sII <= 0) return 0;

  return sRI / sqrt(sRR * sII);
}

bool computeBpm(const uint32_t *idx, int nb, int &bpm, int &good, int &total) {
  int ni = nb - 1;

  if (ni < 1) return false;

  int iv[MAX_INTERVALS];

  for (int i = 0; i < ni; i++) iv[i] = (int)(idx[i + 1] - idx[i]) * SAMPLE_MS;

  int med = medianOf(iv, ni);

  if (med < BEAT_MIN_MS || med > BEAT_MAX_MS) return false;

  int tol = (int)(med * INTERVAL_TOLERANCE);
  int periods = 0;

  good = 0;
  total = ni;

  for (int i = 0; i < ni; i++) {
    if (abs(iv[i] - med) <= tol) good++;

    periods += (int)((double)iv[i] / med + 0.5);
  }

  if (good * 100 < ni * MIN_GOOD_PERCENT) return false;

  uint32_t span = (idx[nb - 1] - idx[0]) * SAMPLE_MS;

  if (span == 0 || periods < NEEDED_BEATS - 1) return false;

  int value = (int)(60000.0 * periods / span + 0.5);

#if USE_BPM_CALIBRATION
  value = (int)(BPM_CAL_A * value + BPM_CAL_B + 0.5);
#endif

  if (value < BPM_MIN || value > BPM_MAX) return false;

  bpm = value;
  return true;
}

bool autoBpm(const float *acRing, uint32_t n, int &bpm, double &quality) {
  static float x[AUTO_WIN];
  static double r[AUTO_LAG_MAX + 2];

  quality = 0;

  if (n < AUTO_WIN + 100) return false;

  uint32_t start = n - AUTO_WIN;
  double mean = 0;

  for (int i = 0; i < AUTO_WIN; i++) {
    x[i] = acRing[(start + i) % RING_SIZE];
    mean += x[i];
  }

  mean /= AUTO_WIN;

  double energy = 0;

  for (int i = 0; i < AUTO_WIN; i++) {
    x[i] -= (float)mean;
    energy += (double)x[i] * x[i];
  }

  if (energy < 1.0) return false;

  for (int lag = AUTO_LAG_MIN - 1; lag <= AUTO_LAG_MAX + 1; lag++) {
    double s = 0;

    for (int i = 0; i + lag < AUTO_WIN; i++) s += (double)x[i] * x[i + lag];

    r[lag] = (s / energy) * ((double)AUTO_WIN / (AUTO_WIN - lag));
  }

  int best = -1;
  double bestVal = 0;

  for (int lag = AUTO_LAG_MIN; lag <= AUTO_LAG_MAX; lag++) {
    if (r[lag] > r[lag - 1] && r[lag] >= r[lag + 1] && r[lag] > bestVal) {
      bestVal = r[lag];
      best = lag;
    }
  }

  if (best < 0) return false;

  int half = best / 2;

  if (half >= AUTO_LAG_MIN) {
    int hb = -1;
    double hv = 0;

    for (int lag = half - 3; lag <= half + 3; lag++) {
      if (lag < AUTO_LAG_MIN || lag > AUTO_LAG_MAX) continue;

      if (r[lag] > r[lag - 1] && r[lag] >= r[lag + 1] && r[lag] > hv) {
        hv = r[lag];
        hb = lag;
      }
    }

    if (hb > 0 && hv >= 0.75 * bestVal) {
      best = hb;
      bestVal = hv;
    }
  }

  double lagF = best;
  double a = r[best - 1], b = r[best], c = r[best + 1];
  double den = a - 2 * b + c;

  if (den < 0) {
    double off = 0.5 * (a - c) / den;

    if (off > 1) off = 1;
    if (off < -1) off = -1;

    lagF += off;
  }

  int value = (int)(6000.0 / lagF + 0.5);

#if USE_BPM_CALIBRATION
  value = (int)(BPM_CAL_A * value + BPM_CAL_B + 0.5);
#endif

  quality = bestVal;

  if (value < BPM_MIN || value > BPM_MAX) return false;
  if (bestVal < AUTO_MIN_QUALITY) return false;

  bpm = value;
  return true;
}

bool evaluate(const uint32_t *redRing, const uint32_t *irRing,
              const float *acIR, const float *acRed, uint32_t n,
              const uint32_t *beatIdx, const double *beatR, const double *beatPI,
              const bool *beatRok, int nBeat, int &bpmOut, int &spo2Out) {
  int abpm = 0;
  double q = 0;
  bool okAuto = autoBpm(acIR, n, abpm, q);

#if DEBUG_RAW
  Serial.printf("  [cek] periodisitas=%.2f (minimal %.2f)\n", q, AUTO_MIN_QUALITY);
#endif

  if (!okAuto) return false;

  int bpm = abpm;
  bool viaBeat = false;
  int bb = 0, good = 0, total = 0;

  if (nBeat >= NEEDED_BEATS && computeBpm(beatIdx, nBeat, bb, good, total)) {
    int tol = (int)(abpm * BPM_AGREE_REL);

    if (tol < BPM_AGREE_ABS) tol = BPM_AGREE_ABS;

    if (abs(bb - abpm) <= tol) {
      bpm = bb;
      viaBeat = true;
    } else {
#if DEBUG_RAW
      Serial.printf("  [cek] ditolak: BPM dari denyut (%d) dan autokorelasi (%d) berbeda\n", bb, abpm);
#endif
      return false;
    }
  } else if (q < AUTO_MIN_QUALITY_SOLO) {
#if DEBUG_RAW
    Serial.printf("  [cek] ditolak: denyut belum cukup terdeteksi, periodisitas harus minimal %.2f\n", AUTO_MIN_QUALITY_SOLO);
#endif
    return false;
  }

  double corr = redIrCorr(acRed, acIR, n, CORR_WIN);

#if DEBUG_RAW
  Serial.printf("  [cek] korelasi_merah_IR=%.2f (minimal %.2f)\n", corr, MIN_RED_IR_CORR);
#endif

  if (corr < MIN_RED_IR_CORR) return false;

  double R, perf;
  int used = 0;

  if (!aggregateR(beatR, beatPI, beatRok, nBeat, R, perf, used)) return false;

  int spo2;

  if (!spo2FromR(R, spo2)) {
#if DEBUG_RAW
    Serial.printf("  [spo2] ditolak: R=%.3f di luar rentang wajar\n", R);
#endif
    return false;
  }

#if DEBUG_RAW
  Serial.printf("  [kandidat] BPM=%d (%s) R=%.3f PI=%.2f%% dari %d denyut\n",
                bpm, viaBeat ? "denyut" : "autokorelasi", R, perf * 100.0, used);
  Serial.printf("  [rumus] kuadrat=%.1f  110-25R=%.1f  104-17R=%.1f  (dipakai: %d)\n",
                -45.060 * R * R + 30.354 * R + 94.845, 110.0 - 25.0 * R, 104.0 - 17.0 * R, SPO2_FORMULA);
#endif

  bpmOut = bpm;
  spo2Out = spo2;
  return true;
}

bool measure(int &bpmOut, int &spo2Out) {
  static uint32_t redRing[RING_SIZE];
  static uint32_t irRing[RING_SIZE];
  static float acIRRing[RING_SIZE];
  static float acRedRing[RING_SIZE];
  static float acBuf[AC_WIN];

  uint32_t beatIdx[MAX_BEATS];
  double beatR[MAX_BEATS];
  double beatPI[MAX_BEATS];
  bool beatRok[MAX_BEATS];
  int nBeat = 0;
  int lastIdx = 0;
  uint32_t n = 0;
  double lp = 0, base = 0, lpR = 0, baseR = 0, prev1 = 0, prev2 = 0, winMax = 0;
  int prevBpm = 0, prevSpo2 = 0;
  bool havePrev = false;

  memset(acBuf, 0, sizeof(acBuf));
  memset(acIRRing, 0, sizeof(acIRRing));
  memset(acRedRing, 0, sizeof(acRedRing));
  lastFail = FAIL_NONE;
  flushSensor();

  uint32_t t0 = millis();

  while (millis() - t0 < MEASURE_TIMEOUT_MS && n < MAX_SAMPLES) {
    uint32_t red, ir;

    if (!readOne(red, ir)) {
      lastFail = FAIL_SENSOR;
      return false;
    }

    if (ir < FINGER_STOP_THRESHOLD) {
      Serial.printf("  [gagal] IR turun ke %lu\n", (unsigned long)ir);
      lastFail = FAIL_NO_FINGER;
      return false;
    }

    redRing[n % RING_SIZE] = red;
    irRing[n % RING_SIZE] = ir;

    if (n == 0) {
      lp = ir;
      base = ir;
      lpR = red;
      baseR = red;
    }

    lp += BP_LP_ALPHA * ((double)ir - lp);
    base += BP_BASE_ALPHA * (lp - base);
    lpR += BP_LP_ALPHA * ((double)red - lpR);
    baseR += BP_BASE_ALPHA * (lpR - baseR);

    double a0 = lp - base;

    acBuf[n % AC_WIN] = (float)a0;
    acIRRing[n % RING_SIZE] = (float)a0;
    acRedRing[n % RING_SIZE] = (float)(lpR - baseR);
    n++;

    winMax = 0;

    for (int i = 0; i < AC_WIN; i++) {
      if (acBuf[i] > winMax) winMax = acBuf[i];
    }

    double thr = winMax * PEAK_RATIO;

    if (thr < MIN_SWING) thr = MIN_SWING;

    if (n == FAILFAST_SAMPLES && nBeat < FAILFAST_MIN_BEATS) {
      Serial.printf("  [gagal] denyut belum terdeteksi stabil (denyut=%d, ayunan=%.0f)\n", nBeat, winMax);
      lastFail = FAIL_LOW_QUALITY;
      return false;
    }

    bool peak = (n > SKIP_SAMPLES) && prev1 > prev2 && prev1 >= a0 && prev1 > thr;

    if (peak) {
      int idx = (int)n - 2;
      int gap = BEAT_MIN_MS / SAMPLE_MS;

      if (nBeat >= 3) {
        int iv[MAX_INTERVALS];
        int ni = nBeat - 1;

        for (int i = 0; i < ni; i++) iv[i] = (int)(beatIdx[i + 1] - beatIdx[i]) * SAMPLE_MS;

        int adaptive = (int)(medianOf(iv, ni) * REFRACTORY_RATIO / SAMPLE_MS);

        if (adaptive > gap) gap = adaptive;
      }

      if (nBeat == 0 || idx - lastIdx >= gap) {
        lastIdx = idx;

        if (nBeat == MAX_BEATS) {
          for (int i = 1; i < MAX_BEATS; i++) {
            beatIdx[i - 1] = beatIdx[i];
            beatR[i - 1] = beatR[i];
            beatPI[i - 1] = beatPI[i];
            beatRok[i - 1] = beatRok[i];
          }

          nBeat--;
        }

        beatIdx[nBeat] = (uint32_t)idx;
        beatRok[nBeat] = false;
        beatR[nBeat] = 0;
        beatPI[nBeat] = 0;

        if (nBeat > 0) {
          double Rb, Pb;

          if (beatRatio(redRing, irRing, n, beatIdx[nBeat - 1], (uint32_t)idx, Rb, Pb)) {
            beatR[nBeat] = Rb;
            beatPI[nBeat] = Pb;
            beatRok[nBeat] = true;
          }
        }

        nBeat++;

        if (nBeat > 1) {
          int d = (int)(beatIdx[nBeat - 1] - beatIdx[nBeat - 2]) * SAMPLE_MS;
          Serial.printf("  denyut %d: %d bpm\n", nBeat, 60000 / d);
        }
      }
    }

    prev2 = prev1;
    prev1 = a0;

    if (n >= EVAL_START_SAMPLES && n % EVAL_STEP == 0) {
      int cb = 0, cs = 0;

      if (evaluate(redRing, irRing, acIRRing, acRedRing, n, beatIdx, beatR, beatPI, beatRok, nBeat, cb, cs)) {
        if (havePrev && abs(cb - prevBpm) <= STABLE_BPM_TOL && abs(cs - prevSpo2) <= STABLE_SPO2_TOL) {
          bpmOut = (cb + prevBpm + 1) / 2;
          spo2Out = (cs + prevSpo2 + 1) / 2;
#if DEBUG_RAW
          Serial.println();
          Serial.println("=== HASIL ===");
          Serial.printf("BPM   : %d\n", bpmOut);
          Serial.printf("SpO2  : %d %%\n", spo2Out);
          Serial.printf("Sampel: %lu\n", (unsigned long)n);
          Serial.println("=============");
#endif
          return true;
        }

        if (havePrev) {
          Serial.printf("  [stabil] kandidat berbeda dari sebelumnya (%d vs %d bpm), menunggu\n", cb, prevBpm);
        } else {
          Serial.println("  [stabil] kandidat pertama, menunggu konfirmasi");
        }

        prevBpm = cb;
        prevSpo2 = cs;
        havePrev = true;
      } else {
        havePrev = false;
      }
    }

#if DEBUG_RAW
    if (n % 100 == 0) {
      Serial.printf("[status] sampel=%lu denyut=%d IR=%lu ayunan=%.0f%s\n",
                    (unsigned long)n, nBeat, (unsigned long)ir, winMax,
                    n <= SKIP_SAMPLES ? " (dilewati)" : "");
    }
#endif

    digitalWrite(LED_PIN, (millis() / 250) % 2);
  }

  Serial.printf("  [gagal] sampel=%lu denyut=%d (tidak ada sinyal denyut yang valid)\n",
                (unsigned long)n, nBeat);

  lastFail = FAIL_TIMEOUT;
  return false;
}

void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  delay(500);

  Serial.println("\n=== PantauJantung ESP32 v4.1 ===");

  Wire.begin(SDA_PIN, SCL_PIN);

  if (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 tidak ditemukan. Cek SDA/SCL dan 3V3.");

    while (true) {
      blinkLed(1, 150);
    }
  }

  sensor.setup(
    SENSOR_LED_BRIGHTNESS,
    4,
    2,
    400,
    411,
    SENSOR_ADC_RANGE
  );

#if !DRY_RUN
  connectWifi();
#else
  Serial.println("Mode DRY_RUN: data tidak dikirim.");
#endif

  reportStatus("siap");

  Serial.println("Siap. Tekan \"Mulai Pengukuran\" di dashboard, lalu taruh jari.");
}

void loop() {
  static uint32_t lastPrint = 0;
  static uint32_t lastBeat = 0;

  uint32_t irNow = sensor.getIR();

  if (irNow <= FINGER_IR_THRESHOLD) {
    if (millis() - lastPrint > 1000) {
      Serial.printf("Menunggu jari... IR=%lu\n", (unsigned long)irNow);
      lastPrint = millis();
    }

    if (millis() - lastBeat > HEARTBEAT_MS) {
      reportStatus(idleCode);
      lastBeat = millis();
    }

    delay(200);
    return;
  }

  Serial.println("Jari terdeteksi. Diam sebentar, jangan bergerak...");
  reportStatus("mengukur");

  int bpm = 0;
  int spo2 = 0;

  if (!measure(bpm, spo2)) {
    digitalWrite(LED_PIN, LOW);

    const char *failCode = "tidak_stabil";

    switch (lastFail) {
      case FAIL_NO_FINGER:
        Serial.println("Jari terangkat sebelum selesai. Ulangi pengukuran.");
        failCode = "jari_terangkat";
        break;

      case FAIL_SENSOR:
        Serial.println("Sensor tidak merespons. Cek kabel.");
        failCode = "sensor_error";
        break;

      case FAIL_LOW_QUALITY:
        Serial.println("Sinyal denyut terlalu lemah. Pastikan jari menutup sensor dan jangan bergerak.");
        failCode = "sinyal_lemah";
        break;

      case FAIL_TIMEOUT:
        Serial.println("Tidak ada denyut yang valid. Pastikan jari menempel dan tenang, lalu coba lagi.");
        failCode = "tidak_stabil";
        break;

      default:
        break;
    }

    blinkLed(5, 100);
    reportStatus(failCode);
    waitFingerRemoved();

    idleCode = "letakkan_kembali";
    Serial.println("Mohon letakkan kembali jari di sensor.");
    reportStatus(idleCode);
    lastBeat = millis();

    return;
  }

  Serial.printf("HASIL: detak jantung %d bpm, SpO2 %d %%\n", bpm, spo2);

  digitalWrite(LED_PIN, HIGH);

#if DRY_RUN

  Serial.println("DRY_RUN: tidak dikirim.");

#else

  int code = sendReading(bpm, spo2);
  bool retry = explainCode(code);

  for (int attempt = 0; retry && attempt < 2; attempt++) {
    delay(code == 429 ? 6000 : 2000);
    code = sendReading(bpm, spo2);
    retry = explainCode(code);
  }

  if (code == 200) {
    reportStatus("terkirim");
  } else if (code == 409) {
    reportStatus("tidak_ada_pengukuran_aktif");
  } else {
    reportStatus("gagal_kirim");
  }

  if (code != 200) {
    blinkLed(5, 100);
  }

#endif

  digitalWrite(LED_PIN, LOW);

  Serial.println("Angkat jari dari sensor.");

  waitFingerRemoved();

  delay(COOLDOWN_MS);

  idleCode = "siap";
  reportStatus(idleCode);
  lastBeat = millis();

  Serial.println("Siap untuk pengukuran berikutnya.");
}