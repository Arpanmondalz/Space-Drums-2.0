#include <SPI.h>
#include <Wire.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_now.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include <freertos/queue.h>

// ==========================================
// CONFIGURATION
// ==========================================
//  XIAO ESP32S3 Hub MAC ADDRESS
uint8_t hubAddress[] = {0xE8, 0x06, 0x90, 0x9D, 0xA0, 0x68};

const uint8_t STICK_ID = 0; // 0 = Left Stick, 1 = Right Stick

// --- PIN CONFIGURATION ---
const int PIN_SPI_MOSI    = 35;
const int PIN_SPI_MISO    = 37;
const int PIN_SPI_SCK     = 36;
const int PIN_I2C_SDA     = 7;
const int PIN_I2C_SCL     = 8;
const int IMU1_CS         = 5;
const int IMU2_CS         = 9;
const int PIN_STATUS_LED  = 41;
const int PMIC_KILL       = 11;
const int PMIC_INT        = 12;
const int PIN_VBAT_SENSE  = 4;   // ADC1_CH3 - ADC1 stays usable while Wi-Fi is on

const uint8_t MMC5983_ADDR  = 0x30;
const uint8_t DRV2605_ADDR  = 0x5A;

// ==========================================
// FREERTOS OBJECTS
// ==========================================
SemaphoreHandle_t i2cMutex;
QueueHandle_t hitQueue;
QueueHandle_t hapticQueue;

// Must match struct_message in spacedrums_2_hub.ino byte for byte.
enum : uint8_t { MSG_HIT = 0, MSG_BATTERY = 1 };
struct __attribute__((packed)) StickPacket {
  uint8_t  type;
  uint8_t  stick_id;
  uint8_t  drum_id;      // MSG_HIT
  uint8_t  velocity;     // MSG_HIT
  uint8_t  battery_pct;  // MSG_BATTERY
  uint16_t battery_mv;   // MSG_BATTERY
};

// ==========================================
// TUNABLES
// ==========================================
// --- Orientation calibration (point at snare, hold still) ---
const uint32_t CAL_STABLE_WINDOW_MS = 1200;   // uninterrupted still time required
const uint32_t CAL_TIMEOUT_MS       = 8000;   // after this, accept best effort
const uint32_t BOOT_SETTLE_MS       = 1500;   // time to get into position after power-on
const int16_t  CAL_GYRO_STILL_LSB   = 200;    // ~12 deg/s per axis
const float    CAL_ACC_TOL_G        = 0.15f;

// --- AHRS ---
const float GYRO_LSB_TO_RADS = 0.001065264f;  // +/-2000 dps full scale
const float ACCEL_LSB_PER_G  = 2048.0f;       // +/-16 g full scale
const float ACC_KP           = 0.5f;          // gravity correction gain (~2 s time constant)
const float ACC_KI           = 0.02f;         // integral term: learns gyro offset while playing
const float ACC_GATE_G       = 0.20f;         // only trust accel within 1 g +/- this
const int16_t ACC_GATE_GYRO_LSB = 8000;       // ~490 deg/s, above this the swing dominates
const float ACC_KI_LIMIT_RADS = 0.09f;        // ~5 deg/s, beyond any plausible ICM-42688 offset

// --- Zero-rate update: in-run gyro bias tracking ---
// A stick in the hand is never truly still, so the old 3 deg/s gate almost never opened during
// a song. Looser gate plus a longer hold trades per-sample purity for actually firing.
const int16_t  ZUPT_GYRO_LSB  = 150;          // ~9 deg/s
const float    ZUPT_ACC_TOL_G = 0.10f;
const uint32_t ZUPT_HOLD_MS   = 400;
const float    ZUPT_ALPHA     = 0.0015f;

// --- Gyro bias vs die temperature ---
// The stick warms 10-15 C in the first minutes of play; that shift is the bulk of the yaw drift.
const uint32_t TCAL_SAMPLE_MS   = 20;
const float    TCAL_MIN_SPAN_C  = 4.0f;       // need this much temperature range to trust a slope
const uint32_t TCAL_MIN_SAMPLES = 400;
const uint32_t TCAL_SOLVE_EVERY = 200;
const float    TCAL_MAX_SLOPE   = 60.0f;      // LSB per C, ~3.7 deg/s per C

// --- IMU1 -> IMU2 gyro alignment, learned from ordinary playing ---
const float    ALIGN_MIN_RATE_LSB = 3000.0f;  // the fit is only observable while really rotating
const uint32_t ALIGN_DECIMATE     = 4;
const uint32_t ALIGN_MIN_SAMPLES  = 4000;
const uint32_t ALIGN_SOLVE_EVERY  = 1000;
const float    ALIGN_MAX_RAD      = 0.15f;    // >8.6 deg means a mounting rotation, not tolerance
const uint32_t ALIGN_IMPACT_BLANK_MS = 30;    // stick flex at contact is not a mounting error

// --- Stick geometry, measured from the tip (PCB sits at the base) ---
const float IMU1_TIP_M     = 0.190f;
const float IMU2_TIP_M     = 0.240f;
const float IMU_BASELINE_M = IMU2_TIP_M - IMU1_TIP_M;

// --- Velocity ---
// Loudness follows tip speed logarithmically, so the levels are spaced by equal speed ratios.
// These two bounds are the whole feel of the dynamics; nudge them if hits read hot or cold.
const float VEL_TIP_MIN_MPS    = 1.3f;
const float VEL_TIP_MAX_MPS    = 9.0f;
const float PIVOT_DEFAULT_M    = 0.08f;       // pivot-to-IMU2 for a wrist stroke, used until measured
const float PIVOT_MIN_M        = 0.00f;
const float PIVOT_MAX_M        = 0.55f;
const float PIVOT_ALPHA        = 0.25f;
const float PIVOT_MIN_RATE     = 8.0f;        // rad/s, below this w^2 is too small to divide by
const float PIVOT_SPREAD_TOL_M = 0.030f;      // measured IMU spacing must agree with IMU_BASELINE_M
const int16_t PIVOT_ACC_CLIP   = 30000;       // near +/-16 g the estimate is unusable

// Above ~1375 deg/s the gyro is heading for its +/-2000 dps rail, so fade over to the
// accelerometer pair, which measures the same rate by a route that cannot saturate.
const float   OMEGA_BLEND_LO = 24.0f;         // rad/s
const float   OMEGA_BLEND_HI = 33.0f;         // rad/s
const int16_t GYRO_CLIP_LSB  = 32000;

// --- Magnetometer yaw anchor (only active after a passing fig-8) ---
const float   MAG_YAW_GAIN      = 0.004f;     // per mag sample, ~5 s time constant
const float   MAG_FIELD_TOL     = 0.20f;      // reject sample if |B| off by >20%
const int16_t MAG_GATE_GYRO_LSB = 3000;       // ~180 deg/s

// --- Drum zones, in degrees of yaw/pitch relative to the snare aim ---
// Top and bottom rows have independent boundaries; the top row is spread wider
// because crash and ride sit further out than the toms.
const float TOP_ROW_PITCH  =  35.0f;   // Angle to trigger upper row. At or above this pitch, the upper row is selected
const float TOP_YAW_OUTER  = 110.0f;   // beyond this, no hit registers at all
const float TOP_YAW_CRASH  = -45.0f;   // left of this -> crash
const float TOP_YAW_CENTER =   0.0f;   // splits tom1 / tom2
const float TOP_YAW_RIDE   =  45.0f;   // right of this -> ride
const float BOT_YAW_OUTER  =  90.0f;
const float BOT_YAW_HIHAT  = -30.0f;   // left of this -> hihat
const float BOT_YAW_FLOOR  =  30.0f;   // right of this -> floor tom

// --- Battery monitoring ---
const float    VBAT_DIVIDER   = 2.0f;    // R9 = R10 = 100k, so Vbat = 2 x Vpin
const float    VBAT_CAL_SCALE = 1.0f;    // trim if it disagrees with a multimeter. Factor = (measured voltage)/(displayed voltage on hub)
const uint32_t VBAT_FIRST_MS  = 3000;
const uint32_t VBAT_SEND_MS   = 10000;
const uint32_t VBAT_QUIET_MS  = 1500;     // let the rail recover after a haptic pulse
const int      VBAT_SAMPLES   = 16;
const float    VBAT_EMA_ALPHA = 0.05f;

// --- Auto power-off ---
const uint32_t IDLE_POWEROFF_MS = 7200000UL;   // 2 h with the stick never leaving the ZUPT rest gate

// --- Fig-8 magnetometer calibration ---
const int      MAX_MAG_SAMPLES      = 300;
const uint32_t MAG_CAL_PERIOD_MS    = 60;
const uint32_t MAG_CAL_DURATION_MS  = 18000;
const int      MAG_CAL_MIN_SAMPLES  = 150;
const float    MAG_CAL_MAX_RESIDUAL = 0.08f;  // RMS sphere-fit error, fraction of radius
const float    MAG_CAL_MIN_COVERAGE = 0.50f;  // weakest axis chord vs mean chord

// ==========================================
// GLOBALS & STATE MACHINES
// ==========================================
Preferences prefs;
enum SystemState { STATE_BOOT_SETTLE, STATE_CALIBRATING, STATE_NORMAL, STATE_MAG_FIG8 };
volatile SystemState sysState = STATE_BOOT_SETTLE;
volatile bool buttonPressed = false;

unsigned long stateTimer = 0;
unsigned long lastLedToggle = 0;
bool ledState = false;

enum : uint8_t { IMU_TEMP = 0, IMU_AX, IMU_AY, IMU_AZ, IMU_GX, IMU_GY, IMU_GZ, IMU_FIELDS };

struct GyroTempCal {
  float slope[3];       // LSB per degC
  float refTemp;        // die temperature at which gyroBias* was captured
  bool  valid;
  double n, sT, sTT, sB[3], sTB[3];
  float tMin, tMax;
  uint32_t sinceSolve;
};
GyroTempCal tcal1 = {}, tcal2 = {};
volatile float dieTemp1 = 0, dieTemp2 = 0;
bool dieTempInit = false;

float accKiBias[3] = {0, 0, 0};               // rad/s, learned by the gravity correction

float alignDelta[3] = {0, 0, 0};              // small-angle rotation from IMU1 frame into IMU2 frame
volatile bool alignValid = false;
double alignAtA[3][3] = {{0}}, alignAtR[3] = {0};
uint32_t alignCount = 0, alignSinceSolve = 0, alignDecimate = 0;
volatile float gyroDisagree = 0;

float pivotToImu2 = PIVOT_DEFAULT_M;
volatile bool geomValid = false;              // set once the measured IMU spacing confirms the model
volatile uint32_t gyroClipCount = 0;
volatile float dbgTipSpeed = 0;
volatile bool driftCalDirty = false;
volatile uint32_t lastMotionMs = 0;

enum DrumState { STATE_IDLE, STATE_SWINGING, STATE_REFRACTORY };
DrumState stickState = STATE_IDLE;
const int16_t SWING_START_THRESHOLD = 4000;
const int16_t HIT_DECEL_THRESHOLD   = 3000;
int16_t peak_swing_velocity = 0; 
unsigned long hitTimer = 0;

float targetYawOffset = 0.0, targetPitchOffset = 0.0;

float gyroBiasX1 = 0, gyroBiasY1 = 0, gyroBiasZ1 = 0;
float gyroBiasX2 = 0, gyroBiasY2 = 0, gyroBiasZ2 = 0;
float magBiasX = 0, magBiasY = 0, magBiasZ = 0;
float magScaleX = 1.0, magScaleY = 1.0, magScaleZ = 1.0;
float magFieldRef = 0.0;                      // expected |B| after calibration
volatile bool magCalValid = false;
volatile bool magYawEnabled = true;

struct MagSample { float x, y, z; };
MagSample magBuffer[MAX_MAG_SAMPLES];
int magSampleCount = 0;
unsigned long lastMagSampleTime = 0;

// Calibrated magnetometer handoff: core 0 produces, core 1 consumes.
portMUX_TYPE magMux = portMUX_INITIALIZER_UNLOCKED;
float magBodyX = 0, magBodyY = 0, magBodyZ = 0;
volatile uint32_t magSeq = 0;

// Calibration result handshake: core 1 produces, core 0 reports.
volatile bool calCompleteFlag = false;
volatile bool calWasStable = false;

volatile float dbgPitch = 0, dbgYaw = 0;
uint8_t whoAmI1 = 0, whoAmI2 = 0;

float q0 = 1.0f, q1 = 0.0f, q2 = 0.0f, q3 = 0.0f;

SPISettings imuSpiSettings(16000000, MSBFIRST, SPI_MODE0);

// ==========================================
// INTERRUPTS & HARDWARE HELPERS
// ==========================================
void IRAM_ATTR isrCalibrate() { buttonPressed = true; }

void writeRegisterIMU(int csPin, uint8_t reg, uint8_t val) {
  SPI.beginTransaction(imuSpiSettings);
  digitalWrite(csPin, LOW); SPI.transfer(reg & 0x7F); SPI.transfer(val); digitalWrite(csPin, HIGH);
  SPI.endTransaction();
}

uint8_t readRegisterIMU(int csPin, uint8_t reg) {
  SPI.beginTransaction(imuSpiSettings);
  digitalWrite(csPin, LOW); SPI.transfer(reg | 0x80); uint8_t v = SPI.transfer(0x00); digitalWrite(csPin, HIGH);
  SPI.endTransaction();
  return v;
}

void selectBankIMU(int csPin, uint8_t bank) { writeRegisterIMU(csPin, 0x76, bank); }

// TEMP_DATA through GYRO_DATA_Z0 in one 14-byte burst; the die temperature drives bias compensation.
void readIMUBurst(int csPin, int16_t *out) {
  uint8_t buf[15] = {0};
  buf[0] = 0x1D | 0x80;
  SPI.beginTransaction(imuSpiSettings);
  digitalWrite(csPin, LOW);
  SPI.transferBytes(buf, buf, sizeof(buf));
  digitalWrite(csPin, HIGH);
  SPI.endTransaction();
  for (int i = 0; i < IMU_FIELDS; i++) out[i] = (int16_t)((buf[1 + 2 * i] << 8) | buf[2 + 2 * i]);
}

static inline float imuTempC(int16_t raw) { return (float)raw / 132.48f + 25.0f; }

void writeRegisterHaptic(uint8_t reg, uint8_t val) {
  if (xSemaphoreTake(i2cMutex, portMAX_DELAY)) {
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(reg); Wire.write(val); Wire.endTransmission();
    xSemaphoreGive(i2cMutex);
  }
}

void hapticEffect(uint8_t e1, uint8_t e2) {
  writeRegisterHaptic(0x04, e1); writeRegisterHaptic(0x05, e2); writeRegisterHaptic(0x06, 0); writeRegisterHaptic(0x0C, 1);
}
void hapticCalStart()   { hapticEffect(1, 0); }    // single strong click
void hapticCalSuccess() { hapticEffect(10, 0); }   // double click
void hapticCalWarn()    { hapticEffect(14, 14); }  // long double buzz

void triggerHapticHit(int velocityBucket) {
  uint8_t effect = 1;
  switch(velocityBucket) {
    case 8: effect = 1; break; case 7: effect = 2; break; case 6: effect = 3; break; case 5: effect = 4; break;
    case 4: effect = 5; break; case 3: effect = 6; break; case 2: effect = 7; break; case 1: effect = 8; break;
  }
  writeRegisterHaptic(0x04, effect); writeRegisterHaptic(0x05, 0x00); writeRegisterHaptic(0x0C, 1);      
}

// Auto set/reset (CTRL0 bit5) cancels the sensor's own offset drift on every
// measurement; it must be re-asserted on each trigger write or it is cleared.
const uint8_t MMC_CTRL0_TM_AUTOSR = 0x21;

void initMagnetometer() {
  Wire.beginTransmission(MMC5983_ADDR); Wire.write(0x0A); Wire.write(0x02); Wire.endTransmission(); // 400 Hz BW, ~2 ms
  Wire.beginTransmission(MMC5983_ADDR); Wire.write(0x09); Wire.write(0x08); Wire.endTransmission(); // one-off SET
  delay(10);
}

void magStartMeasurement() {
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(5))) {
    Wire.beginTransmission(MMC5983_ADDR); Wire.write(0x09); Wire.write(MMC_CTRL0_TM_AUTOSR); Wire.endTransmission();
    xSemaphoreGive(i2cMutex);
  }
}

bool magFetchIfReady(float &mx, float &my, float &mz) {
  bool ok = false;
  if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(5))) {
    Wire.beginTransmission(MMC5983_ADDR); Wire.write(0x08); Wire.endTransmission();
    Wire.requestFrom(MMC5983_ADDR, (uint8_t)1);
    if (Wire.available() && (Wire.read() & 0x01)) {
      Wire.beginTransmission(MMC5983_ADDR); Wire.write(0x00); Wire.endTransmission();
      Wire.requestFrom(MMC5983_ADDR, (uint8_t)6);
      if (Wire.available() >= 6) {
        uint32_t rawX = (Wire.read() << 10) | (Wire.read() << 2);
        uint32_t rawY = (Wire.read() << 10) | (Wire.read() << 2);
        uint32_t rawZ = (Wire.read() << 10) | (Wire.read() << 2);
        mx = (float)((long)rawX - 131072); my = (float)((long)rawY - 131072); mz = (float)((long)rawZ - 131072);
        ok = true;
      }
    }
    xSemaphoreGive(i2cMutex);
  }
  return ok;
}

// Blocking variant, only used during the fig-8 sweep where no hits are being timed.
bool readMagnetometer(float &mx, float &my, float &mz) {
  magStartMeasurement();
  for (int i = 0; i < 20; i++) {
    delayMicroseconds(500);
    if (magFetchIfReady(mx, my, mz)) return true;
  }
  return false;
}

// ==========================================
// BATTERY
// ==========================================
uint16_t readBatteryMillivolts() {
  uint32_t sum = 0;
  for (int i = 0; i < VBAT_SAMPLES; i++) sum += analogReadMilliVolts(PIN_VBAT_SENSE);
  float pinMv = (float)sum / VBAT_SAMPLES;
  return (uint16_t)(pinMv * VBAT_DIVIDER * VBAT_CAL_SCALE);
}

// 1S LiPo discharge curve; a linear voltage-to-percent map is badly wrong in the flat middle.
uint8_t batteryPercent(uint16_t mv) {
  static const uint16_t curveMv[]  = {3270,3610,3690,3710,3730,3750,3770,3790,3800,3820,3840,
                                      3850,3870,3910,3950,3980,4020,4080,4110,4150,4200};
  static const uint8_t  curvePct[] = {   0,   5,  10,  15,  20,  25,  30,  35,  40,  45,  50,
                                        55,  60,  65,  70,  75,  80,  85,  90,  95, 100};
  const int n = sizeof(curvePct) / sizeof(curvePct[0]);
  if (mv <= curveMv[0]) return 0;
  if (mv >= curveMv[n - 1]) return 100;
  for (int i = 1; i < n; i++) {
    if (mv < curveMv[i]) {
      float f = (float)(mv - curveMv[i - 1]) / (float)(curveMv[i] - curveMv[i - 1]);
      return (uint8_t)(curvePct[i - 1] + f * (curvePct[i] - curvePct[i - 1]) + 0.5f);
    }
  }
  return 100;
}

void loadMagCalibration() {
  prefs.begin("drum_cal", true);
  magBiasX = prefs.getFloat("magBiasX", 0.0); magBiasY = prefs.getFloat("magBiasY", 0.0); magBiasZ = prefs.getFloat("magBiasZ", 0.0);
  magScaleX = prefs.getFloat("magScaleX", 1.0); magScaleY = prefs.getFloat("magScaleY", 1.0); magScaleZ = prefs.getFloat("magScaleZ", 1.0);
  magFieldRef = prefs.getFloat("magField", 0.0);
  magCalValid = prefs.getBool("magValid", false);
  magYawEnabled = prefs.getBool("magYaw", true);
  prefs.end();
}

// Learned, part-specific and stable across sessions: gyro bias-vs-temperature slopes and the
// small mounting misalignment between the two IMUs.
void loadDriftCalibration() {
  prefs.begin("drum_cal", true);
  tcal1.slope[0] = prefs.getFloat("t1sx", 0.0f); tcal1.slope[1] = prefs.getFloat("t1sy", 0.0f); tcal1.slope[2] = prefs.getFloat("t1sz", 0.0f);
  tcal2.slope[0] = prefs.getFloat("t2sx", 0.0f); tcal2.slope[1] = prefs.getFloat("t2sy", 0.0f); tcal2.slope[2] = prefs.getFloat("t2sz", 0.0f);
  tcal1.valid = prefs.getBool("t1v", false);
  tcal2.valid = prefs.getBool("t2v", false);
  alignDelta[0] = prefs.getFloat("algx", 0.0f); alignDelta[1] = prefs.getFloat("algy", 0.0f); alignDelta[2] = prefs.getFloat("algz", 0.0f);
  alignValid = prefs.getBool("algv", false);
  prefs.end();
}

void saveDriftCalibration() {
  prefs.begin("drum_cal", false);
  prefs.putFloat("t1sx", tcal1.slope[0]); prefs.putFloat("t1sy", tcal1.slope[1]); prefs.putFloat("t1sz", tcal1.slope[2]);
  prefs.putFloat("t2sx", tcal2.slope[0]); prefs.putFloat("t2sy", tcal2.slope[1]); prefs.putFloat("t2sz", tcal2.slope[2]);
  prefs.putBool("t1v", tcal1.valid); prefs.putBool("t2v", tcal2.valid);
  prefs.putFloat("algx", alignDelta[0]); prefs.putFloat("algy", alignDelta[1]); prefs.putFloat("algz", alignDelta[2]);
  prefs.putBool("algv", alignValid);
  prefs.end();
}

// Least-squares sphere fit: solves A*p = b for p = [2cx, 2cy, 2cz, r^2-|c|^2].
static bool solveSphere(double A[4][5], double out[4]) {
  for (int i = 0; i < 4; i++) {
    int piv = i;
    for (int r = i + 1; r < 4; r++) if (fabs(A[r][i]) > fabs(A[piv][i])) piv = r;
    if (fabs(A[piv][i]) < 1e-12) return false;
    if (piv != i) for (int c = 0; c < 5; c++) { double t = A[i][c]; A[i][c] = A[piv][c]; A[piv][c] = t; }
    for (int r = 0; r < 4; r++) {
      if (r == i) continue;
      double f = A[r][i] / A[i][i];
      for (int c = i; c < 5; c++) A[r][c] -= f * A[i][c];
    }
  }
  for (int i = 0; i < 4; i++) out[i] = A[i][4] / A[i][i];
  return true;
}

static bool solve3x3(double A[3][4], double out[3]) {
  for (int i = 0; i < 3; i++) {
    int piv = i;
    for (int r = i + 1; r < 3; r++) if (fabs(A[r][i]) > fabs(A[piv][i])) piv = r;
    if (fabs(A[piv][i]) < 1e-9) return false;
    if (piv != i) for (int c = 0; c < 4; c++) { double t = A[i][c]; A[i][c] = A[piv][c]; A[piv][c] = t; }
    for (int r = 0; r < 3; r++) {
      if (r == i) continue;
      double f = A[r][i] / A[i][i];
      for (int c = i; c < 4; c++) A[r][c] -= f * A[i][c];
    }
  }
  for (int i = 0; i < 3; i++) out[i] = A[i][3] / A[i][i];
  return true;
}

bool processMagnetometerCalibration() {
  Serial.println();
  Serial.println(F("--- FIG-8 MAGNETOMETER CALIBRATION RESULT ---"));
  Serial.printf("Samples collected : %d (need >= %d)\n", magSampleCount, MAG_CAL_MIN_SAMPLES);

  if (magSampleCount < MAG_CAL_MIN_SAMPLES) {
    Serial.println(F("RESULT: FAIL - not enough samples. Keep the stick moving for the whole 18 s."));
    return false;
  }

  // Work in kilo-counts so the normal equations stay well conditioned.
  double A[4][5] = {{0}};
  for (int i = 0; i < magSampleCount; i++) {
    double x = magBuffer[i].x / 1000.0, y = magBuffer[i].y / 1000.0, z = magBuffer[i].z / 1000.0;
    double row[4] = { x, y, z, 1.0 };
    double bi = x * x + y * y + z * z;
    for (int r = 0; r < 4; r++) {
      for (int c = 0; c < 4; c++) A[r][c] += row[r] * row[c];
      A[r][4] += row[r] * bi;
    }
  }

  double p[4];
  if (!solveSphere(A, p)) {
    Serial.println(F("RESULT: FAIL - fit is singular. Rotate through all three axes, not just one plane."));
    return false;
  }

  float bX = (float)(p[0] * 0.5 * 1000.0);
  float bY = (float)(p[1] * 0.5 * 1000.0);
  float bZ = (float)(p[2] * 0.5 * 1000.0);

  float minX = 1e30f, maxX = -1e30f, minY = 1e30f, maxY = -1e30f, minZ = 1e30f, maxZ = -1e30f;
  double sumR = 0;
  for (int i = 0; i < magSampleCount; i++) {
    float x = magBuffer[i].x - bX, y = magBuffer[i].y - bY, z = magBuffer[i].z - bZ;
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
    if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
    sumR += sqrt((double)x * x + (double)y * y + (double)z * z);
  }
  float meanR = (float)(sumR / magSampleCount);
  if (meanR < 1.0f) {
    Serial.println(F("RESULT: FAIL - field magnitude is essentially zero. Check the magnetometer."));
    return false;
  }

  float chordX = (maxX - minX) * 0.5f, chordY = (maxY - minY) * 0.5f, chordZ = (maxZ - minZ) * 0.5f;
  float avgChord = (chordX + chordY + chordZ) / 3.0f;
  float minChord = fmin(chordX, fmin(chordY, chordZ));
  float coverage = (avgChord > 0) ? (minChord / avgChord) : 0.0f;

  float sX = (chordX > 0) ? (avgChord / chordX) : 1.0f;
  float sY = (chordY > 0) ? (avgChord / chordY) : 1.0f;
  float sZ = (chordZ > 0) ? (avgChord / chordZ) : 1.0f;

  double sumSq = 0; double sumRc = 0;
  for (int i = 0; i < magSampleCount; i++) {
    float x = (magBuffer[i].x - bX) * sX, y = (magBuffer[i].y - bY) * sY, z = (magBuffer[i].z - bZ) * sZ;
    sumRc += sqrt((double)x * x + (double)y * y + (double)z * z);
  }
  float meanRc = (float)(sumRc / magSampleCount);
  for (int i = 0; i < magSampleCount; i++) {
    float x = (magBuffer[i].x - bX) * sX, y = (magBuffer[i].y - bY) * sY, z = (magBuffer[i].z - bZ) * sZ;
    float r = sqrt(x * x + y * y + z * z) - meanRc;
    sumSq += (double)r * r;
  }
  float residual = sqrt(sumSq / magSampleCount) / meanRc;

  Serial.printf("Hard-iron bias    : %.0f, %.0f, %.0f\n", bX, bY, bZ);
  Serial.printf("Soft-iron scale   : %.3f, %.3f, %.3f\n", sX, sY, sZ);
  Serial.printf("Field magnitude   : %.0f counts\n", meanRc);
  Serial.printf("Axis coverage     : %.2f (need >= %.2f)\n", coverage, MAG_CAL_MIN_COVERAGE);
  Serial.printf("Fit residual      : %.2f%% (need <= %.0f%%)\n", residual * 100.0f, MAG_CAL_MAX_RESIDUAL * 100.0f);

  bool pass = true;
  if (coverage < MAG_CAL_MIN_COVERAGE) {
    Serial.println(F("  ! Poor coverage: rotate the stick through all orientations, not one plane."));
    pass = false;
  }
  if (residual > MAG_CAL_MAX_RESIDUAL) {
    Serial.println(F("  ! High residual: nearby iron or speakers distorted the field. Move away and retry."));
    pass = false;
  }

  if (!pass) {
    Serial.println(F("RESULT: FAIL - calibration discarded, previous values kept."));
    return false;
  }

  magBiasX = bX; magBiasY = bY; magBiasZ = bZ;
  magScaleX = sX; magScaleY = sY; magScaleZ = sZ;
  magFieldRef = meanRc;
  magCalValid = true;

  prefs.begin("drum_cal", false);
  prefs.putFloat("magBiasX", magBiasX); prefs.putFloat("magBiasY", magBiasY); prefs.putFloat("magBiasZ", magBiasZ);
  prefs.putFloat("magScaleX", magScaleX); prefs.putFloat("magScaleY", magScaleY); prefs.putFloat("magScaleZ", magScaleZ);
  prefs.putFloat("magField", magFieldRef);
  prefs.putBool("magValid", true);
  prefs.end();

  Serial.println(F("RESULT: PASS - saved to flash. This is stick-specific; you do not need to redo it per room."));
  return true;
}

void autoCalibrateHaptic() {
  if (xSemaphoreTake(i2cMutex, portMAX_DELAY)) {
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x01); Wire.write(0x07); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x1A); Wire.write(0xB6); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x16); Wire.write(0x53); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x17); Wire.write(0xA4); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x1B); Wire.write(0x93); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x1C); Wire.write(0x25); Wire.endTransmission();
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x0C); Wire.write(0x01); Wire.endTransmission();
    xSemaphoreGive(i2cMutex);
  }
  delay(1000); 
  if (xSemaphoreTake(i2cMutex, portMAX_DELAY)) {
    Wire.beginTransmission(DRV2605_ADDR); Wire.write(0x01); Wire.write(0x00); Wire.endTransmission();
    xSemaphoreGive(i2cMutex);
  }
}

// ==========================================
// DRIFT & VELOCITY ESTIMATORS
// ==========================================
static inline float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Straight-line fit of gyro offset against die temperature, fed only from genuinely still samples.
void tcalAccumulate(uint8_t imu, float T, int16_t gx, int16_t gy, int16_t gz) {
  GyroTempCal &c = (imu == 1) ? tcal1 : tcal2;
  const int16_t g[3] = { gx, gy, gz };

  if (c.n == 0) { c.tMin = c.tMax = T; }
  if (T < c.tMin) c.tMin = T;
  if (T > c.tMax) c.tMax = T;
  c.n += 1; c.sT += T; c.sTT += (double)T * T;
  for (int i = 0; i < 3; i++) { c.sB[i] += g[i]; c.sTB[i] += (double)T * g[i]; }

  if (++c.sinceSolve < TCAL_SOLVE_EVERY) return;
  c.sinceSolve = 0;
  if (c.n < TCAL_MIN_SAMPLES || (c.tMax - c.tMin) < TCAL_MIN_SPAN_C) return;

  double den = c.n * c.sTT - c.sT * c.sT;
  if (fabs(den) < 1e-6) return;
  double s[3];
  for (int i = 0; i < 3; i++) {
    s[i] = (c.n * c.sTB[i] - c.sT * c.sB[i]) / den;
    if (fabs(s[i]) > TCAL_MAX_SLOPE) return;
  }
  for (int i = 0; i < 3; i++) c.slope[i] = (float)s[i];
  c.valid = true;
  driftCalDirty = true;
}

// One rigid stick means both gyros must read the same rate, so any difference is misalignment:
// g1 - g2 = delta x g2, which is linear in delta and solvable from ordinary playing motion.
void alignAccumulate(float g1x, float g1y, float g1z, float g2x, float g2y, float g2z) {
  double gx = g2x * 1e-3, gy = g2y * 1e-3, gz = g2z * 1e-3;
  double rx = (g1x - g2x) * 1e-3, ry = (g1y - g2y) * 1e-3, rz = (g1z - g2z) * 1e-3;
  double gg = gx * gx + gy * gy + gz * gz;

  alignAtA[0][0] += gg - gx * gx; alignAtA[0][1] -= gx * gy;      alignAtA[0][2] -= gx * gz;
  alignAtA[1][0] -= gy * gx;      alignAtA[1][1] += gg - gy * gy; alignAtA[1][2] -= gy * gz;
  alignAtA[2][0] -= gz * gx;      alignAtA[2][1] -= gz * gy;      alignAtA[2][2] += gg - gz * gz;
  alignAtR[0] += gy * rz - gz * ry;
  alignAtR[1] += gz * rx - gx * rz;
  alignAtR[2] += gx * ry - gy * rx;
  alignCount++;

  if (++alignSinceSolve < ALIGN_SOLVE_EVERY || alignCount < ALIGN_MIN_SAMPLES) return;
  alignSinceSolve = 0;

  double M[3][4] = {
    { alignAtA[0][0], alignAtA[0][1], alignAtA[0][2], alignAtR[0] },
    { alignAtA[1][0], alignAtA[1][1], alignAtA[1][2], alignAtR[1] },
    { alignAtA[2][0], alignAtA[2][1], alignAtA[2][2], alignAtR[2] },
  };
  // Rotation about a single axis leaves that axis unobservable; the ridge keeps it from blowing up.
  double ridge = 1e-4 * (alignAtA[0][0] + alignAtA[1][1] + alignAtA[2][2]) / 3.0;
  M[0][0] += ridge; M[1][1] += ridge; M[2][2] += ridge;

  double d[3];
  if (!solve3x3(M, d)) return;
  for (int i = 0; i < 3; i++) if (fabs(d[i]) > ALIGN_MAX_RAD) return;
  for (int i = 0; i < 3; i++) alignDelta[i] = (float)d[i];
  alignValid = true;
  driftCalDirty = true;
}

// At the peak of a swing the tangential term is zero, so along-stick linear acceleration is
// exactly -w^2 * (distance to pivot). Comparing the two IMUs also reveals which way body +X
// points and validates the 50 mm spacing, so no sign convention has to be assumed.
float updateTipRadius(int16_t ax1, int16_t ax2, float gravBodyX, float omegaPerp) {
  float fallback = pivotToImu2 + IMU2_TIP_M;
  if (omegaPerp < PIVOT_MIN_RATE) return fallback;
  if (abs(ax1) > PIVOT_ACC_CLIP || abs(ax2) > PIVOT_ACC_CLIP) return fallback;

  const float G0 = 9.80665f;
  float lin1 = ((float)ax1 / ACCEL_LSB_PER_G - gravBodyX) * G0;
  float lin2 = ((float)ax2 / ACCEL_LSB_PER_G - gravBodyX) * G0;
  float w2 = omegaPerp * omegaPerp;

  float spread = fabsf(lin1 - lin2) / w2;
  if (fabsf(spread - IMU_BASELINE_M) > PIVOT_SPREAD_TOL_M) return fallback;
  geomValid = true;

  float axisSign = (lin1 < lin2) ? 1.0f : -1.0f;
  float d2 = 0.5f * ((axisSign * (-lin2 / w2)) + (axisSign * (-lin1 / w2) - IMU_BASELINE_M));
  if (d2 > PIVOT_MIN_M && d2 < PIVOT_MAX_M) pivotToImu2 += PIVOT_ALPHA * (d2 - pivotToImu2);
  return pivotToImu2 + IMU2_TIP_M;
}

// Across the 50 mm baseline the along-stick difference is exactly -L * (wy^2 + wz^2): gravity and
// whole-arm motion cancel, so this reads swing rate straight through gyro saturation.
// Returns a negative value when the accelerometers are themselves railed.
float omegaFromAccelPair(int16_t ax1, int16_t ax2) {
  if (abs(ax1) > PIVOT_ACC_CLIP || abs(ax2) > PIVOT_ACC_CLIP) return -1.0f;
  float dfx = ((float)((int32_t)ax1 - (int32_t)ax2) / ACCEL_LSB_PER_G) * 9.80665f;
  return sqrtf(fabsf(dfx) / IMU_BASELINE_M);
}

// Gyro below the blend window, accelerometer pair above it, crossfade in between.
float swingRate(float gyroRate, int16_t ax1, int16_t ax2) {
  if (!geomValid || gyroRate <= OMEGA_BLEND_LO) return gyroRate;
  float accRate = omegaFromAccelPair(ax1, ax2);
  if (accRate <= 0.0f) return gyroRate;
  float b = clampf((gyroRate - OMEGA_BLEND_LO) / (OMEGA_BLEND_HI - OMEGA_BLEND_LO), 0.0f, 1.0f);
  return (1.0f - b) * gyroRate + b * accRate;
}

// Equal steps in perceived loudness are equal ratios of tip speed, not equal increments.
uint8_t tipSpeedToLevel(float v, uint8_t levels) {
  if (v <= VEL_TIP_MIN_MPS) return 1;
  if (v >= VEL_TIP_MAX_MPS) return levels;
  float f = logf(v / VEL_TIP_MIN_MPS) / logf(VEL_TIP_MAX_MPS / VEL_TIP_MIN_MPS);
  int lvl = 1 + (int)(f * (float)(levels - 1) + 0.5f);
  return (uint8_t)constrain(lvl, 1, (int)levels);
}

// ==========================================
// ATTITUDE HELPERS
// ==========================================
// Absolute attitude from measured gravity, with yaw defined as exactly zero.
void setAttitudeFromGravity(float ax, float ay, float az) {
  float n = sqrtf(ax * ax + ay * ay + az * az);
  if (n < 1e-6f) return;
  ax /= n; ay /= n; az /= n;
  float roll  = atan2f(ay, az);
  float pitch = atan2f(-ax, sqrtf(ay * ay + az * az));
  float cr = cosf(roll * 0.5f),  sr = sinf(roll * 0.5f);
  float cp = cosf(pitch * 0.5f), sp = sinf(pitch * 0.5f);
  q0 = cr * cp; q1 = sr * cp; q2 = cr * sp; q3 = -sr * sp;
}

static inline float wrap180(float a) {
  while (a > 180.0f) a -= 360.0f;
  while (a < -180.0f) a += 360.0f;
  return a;
}

// ==========================================
// CORE 1: FAST PHYSICS TASK
// (swing / hit detection thresholds below are unchanged; only the velocity number differs)
// ==========================================
void PhysicsTask(void *pvParameters) {
  TickType_t xLastWakeTime = xTaskGetTickCount();
  bool impactLatched = false;
  uint32_t impactLatchMs = 0;
  float latchedPitch = 0.0;
  float latchedYaw = 0.0;

  SystemState prevState = STATE_BOOT_SETTLE;
  uint32_t lastMicros = micros();

  double calSumAx = 0, calSumAy = 0, calSumAz = 0;
  double calSumGx1 = 0, calSumGy1 = 0, calSumGz1 = 0;
  double calSumGx2 = 0, calSumGy2 = 0, calSumGz2 = 0;
  double calSumT1 = 0, calSumT2 = 0;
  uint32_t calCount = 0, calWindowStart = 0, calAttemptStart = 0;

  uint32_t restStart = 0;
  uint32_t lastTcalSample = 0;
  bool magRefValid = false;
  float magYawRef = 0.0f;
  uint32_t lastMagSeqSeen = 0;

  int16_t s1[IMU_FIELDS], s2[IMU_FIELDS];
  float peakOmegaPerp = 0.0f, peakTipRadius = PIVOT_DEFAULT_M + IMU2_TIP_M;

  for(;;) {
    vTaskDelayUntil(&xLastWakeTime, pdMS_TO_TICKS(1));
    readIMUBurst(IMU1_CS, s1);
    readIMUBurst(IMU2_CS, s2);

    int16_t gx1 = s1[IMU_GX], gy1 = s1[IMU_GY], gz1 = s1[IMU_GZ];
    int16_t gx2 = s2[IMU_GX], gy2 = s2[IMU_GY], gz2 = s2[IMU_GZ];
    int16_t ax2 = s2[IMU_AX], ay2 = s2[IMU_AY], az2 = s2[IMU_AZ];

    float rawT1 = imuTempC(s1[IMU_TEMP]), rawT2 = imuTempC(s2[IMU_TEMP]);
    if (!dieTempInit) { dieTemp1 = rawT1; dieTemp2 = rawT2; dieTempInit = true; }
    dieTemp1 += 0.01f * (rawT1 - dieTemp1);
    dieTemp2 += 0.01f * (rawT2 - dieTemp2);
    float dT1 = dieTemp1 - tcal1.refTemp, dT2 = dieTemp2 - tcal2.refTemp;

    float c1x = gx1 - (gyroBiasX1 + tcal1.slope[0] * dT1);
    float c1y = gy1 - (gyroBiasY1 + tcal1.slope[1] * dT1);
    float c1z = gz1 - (gyroBiasZ1 + tcal1.slope[2] * dT1);
    float c2x = gx2 - (gyroBiasX2 + tcal2.slope[0] * dT2);
    float c2y = gy2 - (gyroBiasY2 + tcal2.slope[1] * dT2);
    float c2z = gz2 - (gyroBiasZ2 + tcal2.slope[2] * dT2);

    // Both parts sit on one rigid stick and must read the same rate, so averaging the aligned
    // pair drops angular random walk by ~sqrt(2).
    float fgx = c2x, fgy = c2y, fgz = c2z;
    if (alignValid) {
      float a1x = c1x - (alignDelta[1] * c1z - alignDelta[2] * c1y);
      float a1y = c1y - (alignDelta[2] * c1x - alignDelta[0] * c1z);
      float a1z = c1z - (alignDelta[0] * c1y - alignDelta[1] * c1x);
      fgx = 0.5f * (c2x + a1x); fgy = 0.5f * (c2y + a1y); fgz = 0.5f * (c2z + a1z);
    }

    uint32_t nowUs = micros();
    float dt = (nowUs - lastMicros) * 1e-6f;
    lastMicros = nowUs;
    if (dt <= 0.0f || dt > 0.02f) dt = 0.001f;

    uint32_t nowMs = millis();
    SystemState st = sysState;
    float accMagG = sqrtf((float)ax2 * ax2 + (float)ay2 * ay2 + (float)az2 * az2) / ACCEL_LSB_PER_G;

    // ---------- POINT-AT-SNARE CALIBRATION ----------
    if (st == STATE_CALIBRATING) {
      if (prevState != STATE_CALIBRATING) {
        calSumAx = calSumAy = calSumAz = 0;
        calSumGx1 = calSumGy1 = calSumGz1 = 0;
        calSumGx2 = calSumGy2 = calSumGz2 = 0;
        calSumT1 = calSumT2 = 0;
        calCount = 0; calWindowStart = nowMs; calAttemptStart = nowMs;
      }
      prevState = st;

      bool timedOut = (nowMs - calAttemptStart) >= CAL_TIMEOUT_MS;
      bool still = (abs(gx2) <= CAL_GYRO_STILL_LSB) && (abs(gy2) <= CAL_GYRO_STILL_LSB) && (abs(gz2) <= CAL_GYRO_STILL_LSB)
                   && (fabsf(accMagG - 1.0f) <= CAL_ACC_TOL_G);

      if (!still && !timedOut) {
        // Restart the window: only a genuinely motionless stick gives a usable bias and gravity vector.
        calSumAx = calSumAy = calSumAz = 0;
        calSumGx1 = calSumGy1 = calSumGz1 = 0;
        calSumGx2 = calSumGy2 = calSumGz2 = 0;
        calSumT1 = calSumT2 = 0;
        calCount = 0; calWindowStart = nowMs;
        continue;
      }

      calSumAx += ax2; calSumAy += ay2; calSumAz += az2;
      calSumGx1 += gx1; calSumGy1 += gy1; calSumGz1 += gz1;
      calSumGx2 += gx2; calSumGy2 += gy2; calSumGz2 += gz2;
      calSumT1 += dieTemp1; calSumT2 += dieTemp2;
      calCount++;

      bool windowDone = (nowMs - calWindowStart) >= CAL_STABLE_WINDOW_MS;
      if (windowDone || timedOut) {
        if (calCount > 100) {
          float inv = 1.0f / (float)calCount;
          gyroBiasX1 = calSumGx1 * inv; gyroBiasY1 = calSumGy1 * inv; gyroBiasZ1 = calSumGz1 * inv;
          gyroBiasX2 = calSumGx2 * inv; gyroBiasY2 = calSumGy2 * inv; gyroBiasZ2 = calSumGz2 * inv;
          tcal1.refTemp = calSumT1 * inv; tcal2.refTemp = calSumT2 * inv;
          setAttitudeFromGravity(calSumAx * inv, calSumAy * inv, calSumAz * inv);
        } else {
          tcal1.refTemp = dieTemp1; tcal2.refTemp = dieTemp2;
          setAttitudeFromGravity(ax2, ay2, az2);
        }
        accKiBias[0] = accKiBias[1] = accKiBias[2] = 0.0f;

        // Zero the aim at the current attitude, using the same extraction the loop uses.
        targetPitchOffset = -asin(2.0f * (q0*q2 - q3*q1)) * 57.2957f;
        targetYawOffset   = -atan2(2.0f * (q0*q3 + q1*q2), 1.0f - 2.0f * (q2*q2 + q3*q3)) * 57.2957f;

        stickState = STATE_IDLE; peak_swing_velocity = 0; impactLatched = false;
        magRefValid = false;
        restStart = 0;
        calWasStable = windowDone && !timedOut;
        calCompleteFlag = true;
        sysState = STATE_NORMAL;
      }
      continue;
    }

    if (st != STATE_NORMAL) { prevState = st; continue; }
    prevState = st;

    float gx_rad = fgx * GYRO_LSB_TO_RADS + accKiBias[0];
    float gy_rad = fgy * GYRO_LSB_TO_RADS + accKiBias[1];
    float gz_rad = fgz * GYRO_LSB_TO_RADS + accKiBias[2];

    // Gravity direction in the body frame, i.e. what the accelerometer should read at rest.
    float vx = 2.0f * (q1*q3 - q0*q2);
    float vy = 2.0f * (q0*q1 + q2*q3);
    float vz = q0*q0 - q1*q1 - q2*q2 + q3*q3;

    // ---------- GRAVITY CORRECTION (kills roll/pitch drift) ----------
    bool accTrusted = (fabsf(accMagG - 1.0f) <= ACC_GATE_G)
                      && (abs(gx2) < ACC_GATE_GYRO_LSB) && (abs(gy2) < ACC_GATE_GYRO_LSB) && (abs(gz2) < ACC_GATE_GYRO_LSB);
    if (accTrusted) {
      float an = 1.0f / (accMagG * ACCEL_LSB_PER_G);
      float axn = ax2 * an, ayn = ay2 * an, azn = az2 * an;
      float ex = ayn * vz - azn * vy;
      float ey = azn * vx - axn * vz;
      float ez = axn * vy - ayn * vx;
      gx_rad += ACC_KP * ex; gy_rad += ACC_KP * ey; gz_rad += ACC_KP * ez;
      // Integral term: bleeds out the standing gyro offset even when the stick is never still enough for ZUPT.
      accKiBias[0] = clampf(accKiBias[0] + ACC_KI * ex * dt, -ACC_KI_LIMIT_RADS, ACC_KI_LIMIT_RADS);
      accKiBias[1] = clampf(accKiBias[1] + ACC_KI * ey * dt, -ACC_KI_LIMIT_RADS, ACC_KI_LIMIT_RADS);
      accKiBias[2] = clampf(accKiBias[2] + ACC_KI * ez * dt, -ACC_KI_LIMIT_RADS, ACC_KI_LIMIT_RADS);
    }

    // ---------- ZERO-RATE UPDATE (kills thermal gyro bias drift) ----------
    bool atRest = (abs(gx2) <= ZUPT_GYRO_LSB) && (abs(gy2) <= ZUPT_GYRO_LSB) && (abs(gz2) <= ZUPT_GYRO_LSB)
                  && (fabsf(accMagG - 1.0f) <= ZUPT_ACC_TOL_G);
    if (atRest) {
      if (restStart == 0) restStart = nowMs;
      else if (nowMs - restStart >= ZUPT_HOLD_MS) {
        // Track the offset at the reference temperature; the learned slope covers the rest.
        gyroBiasX2 += ZUPT_ALPHA * ((gx2 - tcal2.slope[0] * dT2) - gyroBiasX2);
        gyroBiasY2 += ZUPT_ALPHA * ((gy2 - tcal2.slope[1] * dT2) - gyroBiasY2);
        gyroBiasZ2 += ZUPT_ALPHA * ((gz2 - tcal2.slope[2] * dT2) - gyroBiasZ2);
        gyroBiasX1 += ZUPT_ALPHA * ((gx1 - tcal1.slope[0] * dT1) - gyroBiasX1);
        gyroBiasY1 += ZUPT_ALPHA * ((gy1 - tcal1.slope[1] * dT1) - gyroBiasY1);
        gyroBiasZ1 += ZUPT_ALPHA * ((gz1 - tcal1.slope[2] * dT1) - gyroBiasZ1);

        if (nowMs - lastTcalSample >= TCAL_SAMPLE_MS) {
          lastTcalSample = nowMs;
          tcalAccumulate(1, dieTemp1, gx1, gy1, gz1);
          tcalAccumulate(2, dieTemp2, gx2, gy2, gz2);
        }
      }
    } else { restStart = 0; lastMotionMs = nowMs; }

    // ---------- IMU1 -> IMU2 ALIGNMENT ----------
    // Contact bends the stick between the two IMUs, breaking the rigid-body assumption the fit needs.
    bool nearImpact = (stickState == STATE_REFRACTORY)
                      || (impactLatched && (nowMs - impactLatchMs) < ALIGN_IMPACT_BLANK_MS);
    float rateSum = fabsf(c2x) + fabsf(c2y) + fabsf(c2z);
    if (rateSum > ALIGN_MIN_RATE_LSB) {
      if (++alignDecimate >= ALIGN_DECIMATE) {
        alignDecimate = 0;
        if (!nearImpact) alignAccumulate(c1x, c1y, c1z, c2x, c2y, c2z);
      }
    } else if (rateSum < 1500.0f) {
      float d = fabsf(c1x - c2x) + fabsf(c1y - c2y) + fabsf(c1z - c2z);
      gyroDisagree += 0.002f * (d - gyroDisagree);
    }

    float dq0 = 0.5f * (-q1 * gx_rad - q2 * gy_rad - q3 * gz_rad) * dt;
    float dq1 = 0.5f * ( q0 * gx_rad + q2 * gz_rad - q3 * gy_rad) * dt;
    float dq2 = 0.5f * ( q0 * gy_rad - q1 * gz_rad + q3 * gx_rad) * dt;
    float dq3 = 0.5f * ( q0 * gz_rad + q1 * gy_rad - q2 * gx_rad) * dt;
    q0 += dq0; q1 += dq1; q2 += dq2; q3 += dq3;

    float norm = sqrt(q0*q0 + q1*q1 + q2*q2 + q3*q3);
    q0 /= norm; q1 /= norm; q2 /= norm; q3 /= norm;

    // ---------- MAGNETOMETER YAW ANCHOR (bounds long-term yaw drift) ----------
    if (magSeq != lastMagSeqSeen) {
      float mbx, mby, mbz;
      portENTER_CRITICAL(&magMux);
      mbx = magBodyX; mby = magBodyY; mbz = magBodyZ; lastMagSeqSeen = magSeq;
      portEXIT_CRITICAL(&magMux);

      float mMag = sqrtf(mbx*mbx + mby*mby + mbz*mbz);
      bool magTrusted = magCalValid && magYawEnabled && magFieldRef > 1.0f
                        && fabsf(mMag - magFieldRef) <= MAG_FIELD_TOL * magFieldRef
                        && abs(gx2) < MAG_GATE_GYRO_LSB && abs(gy2) < MAG_GATE_GYRO_LSB && abs(gz2) < MAG_GATE_GYRO_LSB;

      if (magTrusted) {
        // Rotate the field into world frame; with a correct attitude this is constant.
        float wx = (1 - 2*(q2*q2 + q3*q3))*mbx + 2*(q1*q2 - q0*q3)*mby + 2*(q1*q3 + q0*q2)*mbz;
        float wy = 2*(q1*q2 + q0*q3)*mbx + (1 - 2*(q1*q1 + q3*q3))*mby + 2*(q2*q3 - q0*q1)*mbz;
        float heading = atan2f(wy, wx);
        if (!magRefValid) { magYawRef = heading; magRefValid = true; }
        else {
          float delta = heading - magYawRef;
          while (delta > (float)M_PI) delta -= 2.0f * (float)M_PI;
          while (delta < -(float)M_PI) delta += 2.0f * (float)M_PI;
          float theta = -MAG_YAW_GAIN * delta;
          float c = cosf(theta * 0.5f), s = sinf(theta * 0.5f);
          float n0 = c*q0 - s*q3, n1 = c*q1 - s*q2, n2 = c*q2 + s*q1, n3 = c*q3 + s*q0;
          q0 = n0; q1 = n1; q2 = n2; q3 = n3;
        }
      }
    }

    float curPitch = -asin(2.0f * (q0*q2 - q3*q1)) * 57.2957f;
    float curYaw   = -atan2(2.0f * (q0*q3 + q1*q2), 1.0f - 2.0f * (q2*q2 + q3*q3)) * 57.2957f;

    float finalPitch = curPitch - targetPitchOffset;
    float finalYaw   = wrap180(curYaw - targetYawOffset);
    dbgPitch = finalPitch; dbgYaw = finalYaw;

    int16_t current_gyro_y = gy2;
    if (stickState == STATE_IDLE) {
      if (current_gyro_y > SWING_START_THRESHOLD) { 
        stickState = STATE_SWINGING;
        peak_swing_velocity = current_gyro_y; 
        peakOmegaPerp = sqrtf(fgy * fgy + fgz * fgz) * GYRO_LSB_TO_RADS;
        peakTipRadius = pivotToImu2 + IMU2_TIP_M;
        impactLatched = false;
      }
    } 
    else if (stickState == STATE_SWINGING) {
      if (current_gyro_y > peak_swing_velocity) {
        peak_swing_velocity = current_gyro_y;
        if (abs(gy2) > GYRO_CLIP_LSB || abs(gz2) > GYRO_CLIP_LSB) gyroClipCount++;
        // Radius first, from the gyro alone, so its spacing check stays independent of the blend.
        float wGyro = sqrtf(fgy * fgy + fgz * fgz) * GYRO_LSB_TO_RADS;
        peakTipRadius = updateTipRadius(s1[IMU_AX], s2[IMU_AX], vx, wGyro);
        peakOmegaPerp = swingRate(wGyro, s1[IMU_AX], s2[IMU_AX]);
      }

      if (!impactLatched && current_gyro_y < (peak_swing_velocity - 800)) {
        latchedPitch = finalPitch; latchedYaw = finalYaw; impactLatched = true; impactLatchMs = nowMs;
      }

      if (current_gyro_y < (peak_swing_velocity - HIT_DECEL_THRESHOLD)) {
        uint8_t drumId = 0;
        if (latchedPitch >= TOP_ROW_PITCH) {
          if (latchedYaw >= -TOP_YAW_OUTER && latchedYaw <= TOP_YAW_OUTER) {
            if (latchedYaw < TOP_YAW_CRASH)       { drumId = 1; }  // crash
            else if (latchedYaw < TOP_YAW_CENTER) { drumId = 3; }  // tom1
            else if (latchedYaw <= TOP_YAW_RIDE)  { drumId = 4; }  // tom2
            else                                  { drumId = 5; }  // ride
          }
        } else {
          if (latchedYaw >= -BOT_YAW_OUTER && latchedYaw <= BOT_YAW_OUTER) {
            if (latchedYaw < BOT_YAW_HIHAT)       { drumId = 6; }  // hihat
            else if (latchedYaw <= BOT_YAW_FLOOR) { drumId = 2; }  // snare
            else                                  { drumId = 7; }  // floor tom
          }
        }
        
        if (drumId != 0) {
          // Loudness is set by how fast the tip moves, not how fast the stick rotates: a wrist
          // flick and a full-arm stroke at the same rate are very different volumes.
          float tipSpeed = peakOmegaPerp * peakTipRadius;
          dbgTipSpeed = tipSpeed;

          StickPacket payload = {};
          payload.type = MSG_HIT; payload.stick_id = STICK_ID;
          payload.drum_id = drumId; payload.velocity = tipSpeedToLevel(tipSpeed, 6);

          // Send to Network Task via Queue instantly
          xQueueSend(hitQueue, &payload, 0);

          // Haptics are I2C and would stall this 1 kHz loop mid-swing, so hand them off too.
          uint8_t hapticLevel = tipSpeedToLevel(tipSpeed, 8);
          xQueueSend(hapticQueue, &hapticLevel, 0);
        }
        stickState = STATE_REFRACTORY; hitTimer = millis();
      }
    } 
    else if (stickState == STATE_REFRACTORY) {
      if (millis() - hitTimer >= 80) { 
        if (current_gyro_y < 2000) { stickState = STATE_IDLE; peak_swing_velocity = 0; }
      }
    }
  }
}

// ==========================================
// CORE 0: NETWORK, UI & SERIAL TASK
// ==========================================
void startOrientationCalibration() {
  hapticCalStart();
  calCompleteFlag = false;
  sysState = STATE_CALIBRATING;
  Serial.println(F("[CAL] Point at the snare and hold still..."));
}

void printHelp() {
  Serial.println();
  Serial.println(F("Commands:"));
  Serial.println(F("  help            - this list"));
  Serial.println(F("  cal             - re-zero orientation (same as a short button press)"));
  Serial.println(F("  magcal          - run the 18 s figure-8 magnetometer calibration"));
  Serial.println(F("  magclear        - erase the stored magnetometer calibration"));
  Serial.println(F("  magyaw on|off   - enable/disable the magnetometer yaw anchor"));
  Serial.println(F("  status          - show live orientation and calibration state"));
}

void printBanner() {
  Serial.printf("\nSpace Drums 2.0 - stick %d\n", STICK_ID);
  Serial.printf("IMU1 WHO_AM_I=0x%02X  IMU2 WHO_AM_I=0x%02X (expect 0x47)\n", whoAmI1, whoAmI2);
  Serial.printf("Mag calibration: %s\n", magCalValid ? "loaded from flash" : "NOT SET - run 'magcal' once");
  printHelp();
}

void printStatus() {
  Serial.println();
  Serial.printf("Stick ID       : %d\n", STICK_ID);
  Serial.printf("State          : %d\n", (int)sysState);
  Serial.printf("Pitch / Yaw    : %.1f  /  %.1f  (deg from snare aim)\n", dbgPitch, dbgYaw);
  Serial.printf("Gyro bias IMU2 : %.1f, %.1f, %.1f LSB\n", gyroBiasX2, gyroBiasY2, gyroBiasZ2);
  Serial.printf("Die temp 1/2   : %.1f / %.1f C (ref %.1f / %.1f)\n", dieTemp1, dieTemp2, tcal1.refTemp, tcal2.refTemp);
  Serial.printf("Gyro T-slope   : %s  IMU1 %.1f,%.1f,%.1f  IMU2 %.1f,%.1f,%.1f LSB/C\n",
                (tcal1.valid && tcal2.valid) ? "learned" : "learning",
                tcal1.slope[0], tcal1.slope[1], tcal1.slope[2],
                tcal2.slope[0], tcal2.slope[1], tcal2.slope[2]);
  Serial.printf("Accel-KI bias  : %.3f, %.3f, %.3f rad/s\n", accKiBias[0], accKiBias[1], accKiBias[2]);
  Serial.printf("IMU alignment  : %s  %.2f, %.2f, %.2f deg  (%lu samples)\n",
                alignValid ? "valid" : "learning",
                alignDelta[0] * 57.2957f, alignDelta[1] * 57.2957f, alignDelta[2] * 57.2957f,
                (unsigned long)alignCount);
  Serial.printf("Gyro mismatch  : %.1f LSB at rest\n", gyroDisagree);
  Serial.printf("Pivot -> IMU2  : %.3f m  (tip radius %.3f m)\n", pivotToImu2, pivotToImu2 + IMU2_TIP_M);
  Serial.printf("Geometry check : %s\n", geomValid ? "confirmed by IMU pair" : "not yet confirmed");
  Serial.printf("Gyro clip hits : %lu\n", (unsigned long)gyroClipCount);
  Serial.printf("Last tip speed : %.2f m/s\n", dbgTipSpeed);
  uint16_t bmv = readBatteryMillivolts();
  Serial.printf("Battery        : %u%% (%u mV)\n", batteryPercent(bmv), bmv);
  Serial.printf("Mag cal valid  : %s\n", magCalValid ? "yes" : "no  (run magcal)");
  Serial.printf("Mag yaw anchor : %s\n", magYawEnabled ? "on" : "off");
  if (magCalValid) {
    Serial.printf("Mag bias       : %.0f, %.0f, %.0f\n", magBiasX, magBiasY, magBiasZ);
    Serial.printf("Mag scale      : %.3f, %.3f, %.3f\n", magScaleX, magScaleY, magScaleZ);
    Serial.printf("Mag |B| ref    : %.0f\n", magFieldRef);
  }
}

void handleSerialCommand(const char *cmd) {
  if (!strcmp(cmd, "help")) { printHelp(); }
  else if (!strcmp(cmd, "status")) { printStatus(); }
  else if (!strcmp(cmd, "cal")) {
    if (sysState == STATE_NORMAL) startOrientationCalibration();
    else Serial.println(F("[CAL] Busy, try again in a moment."));
  }
  else if (!strcmp(cmd, "magcal")) {
    if (sysState != STATE_NORMAL) { Serial.println(F("[MAGCAL] Busy, try again in a moment.")); return; }
    Serial.println();
    Serial.println(F("[MAGCAL] Move away from speakers, PCs and steel furniture."));
    Serial.println(F("[MAGCAL] Slowly draw figure-8s AND roll the stick so every orientation is covered."));
    Serial.println(F("[MAGCAL] Recording for 18 seconds, starting now..."));
    hapticCalStart();
    sysState = STATE_MAG_FIG8;  // timers are armed on state entry in NetworkTask
  }
  else if (!strcmp(cmd, "magclear")) {
    prefs.begin("drum_cal", false);
    prefs.putBool("magValid", false);
    prefs.end();
    magCalValid = false;
    Serial.println(F("[MAGCAL] Stored calibration cleared. Yaw anchor disabled until you run magcal."));
  }
  else if (!strcmp(cmd, "magyaw on") || !strcmp(cmd, "magyaw off")) {
    magYawEnabled = (cmd[7] == 'o' && cmd[8] == 'n');
    prefs.begin("drum_cal", false); prefs.putBool("magYaw", magYawEnabled); prefs.end();
    Serial.printf("[MAGYAW] %s\n", magYawEnabled ? "enabled" : "disabled");
  }
  else if (cmd[0]) { Serial.printf("Unknown command '%s'. Type help.\n", cmd); }
}

void pollSerial() {
  static char buf[32];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') { buf[len] = 0; handleSerialCommand(buf); len = 0; }
    else if (len < sizeof(buf) - 1) buf[len++] = c;
  }
}

void NetworkTask(void *pvParameters) {
  // --- Initialize ESP-NOW ---
  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) { Serial.println("ESP-NOW Init Failed!"); }
  
  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, hubAddress, 6);
  peerInfo.channel = 0;  
  peerInfo.encrypt = false;
  if (esp_now_add_peer(&peerInfo) != ESP_OK) { Serial.println("Failed to add Hub peer"); }

  autoCalibrateHaptic(); 
  stateTimer = millis();
  sysState = STATE_BOOT_SETTLE;

  unsigned long lastMagRead = millis();
  unsigned long lastButtonHandled = 0;
  unsigned long magTrigTime = 0;
  bool magPending = false;
  unsigned long lastHitMs = 0;
  unsigned long nextBattSend = millis() + VBAT_FIRST_MS;
  unsigned long driftSaveAt = 0;
  bool driftSavePending = false;
  float battMvFiltered = 0;
  bool serialWasUp = false;
  SystemState prevNetState = STATE_BOOT_SETTLE;

  for(;;) {
    unsigned long currentMillis = millis();

    // USB CDC enumerates well after boot, so greet the monitor when it actually attaches.
    bool serialUp = (bool)Serial;
    if (serialUp && !serialWasUp) printBanner();
    serialWasUp = serialUp;

    StickPacket outgoingHit;
    // OPTIMIZATION: Block for up to 1ms waiting for a hit.
    // This replaces vTaskDelay(1) and eliminates up to 1ms of delay!
    if (xQueueReceive(hitQueue, &outgoingHit, pdMS_TO_TICKS(1)) == pdPASS) {
      esp_now_send(hubAddress, (uint8_t *) &outgoingHit, sizeof(StickPacket));
      lastHitMs = currentMillis;
    }

    uint8_t hapticLevel;
    while (xQueueReceive(hapticQueue, &hapticLevel, 0) == pdPASS) triggerHapticHit(hapticLevel);

    if (sysState == STATE_NORMAL && (long)(currentMillis - nextBattSend) >= 0
        && currentMillis - lastHitMs >= VBAT_QUIET_MS) {
      nextBattSend = currentMillis + VBAT_SEND_MS;
      uint16_t mv = readBatteryMillivolts();
      battMvFiltered = (battMvFiltered < 1.0f) ? mv : battMvFiltered + VBAT_EMA_ALPHA * (mv - battMvFiltered);
      StickPacket batt = {};
      batt.type = MSG_BATTERY; batt.stick_id = STICK_ID;
      batt.battery_mv = (uint16_t)battMvFiltered;
      batt.battery_pct = batteryPercent(batt.battery_mv);
      esp_now_send(hubAddress, (uint8_t *) &batt, sizeof(StickPacket));
    }

    if (currentMillis >= lastMotionMs && (currentMillis - lastMotionMs >= IDLE_POWEROFF_MS)) {
      Serial.println(F("[PWR] Idle for 2 h, powering off."));
      if (driftCalDirty) saveDriftCalibration();
      digitalWrite(PMIC_KILL, LOW);   // LTC2954 releases EN ~30 us later, cutting the rail
      vTaskDelay(portMAX_DELAY);      // on USB the rail cannot drop, so just stop here
    }

    pollSerial();

    // Arm timers here, not in the command handler: currentMillis predates the command.
    SystemState st = sysState;
    if (st != prevNetState) {
      if (st == STATE_MAG_FIG8) {
        magSampleCount = 0;
        stateTimer = currentMillis;
        lastMagSampleTime = currentMillis;
      }
      // A flash write stalls both cores, so it may only happen while calibrating, never mid-song.
      if (st == STATE_CALIBRATING && driftCalDirty) {
        driftSavePending = true;
        driftSaveAt = currentMillis + 10;  // let the physics task observe the state change first
      }
      prevNetState = st;
    }

    if (driftSavePending && (long)(currentMillis - driftSaveAt) >= 0) {
      driftSavePending = false;
      if (sysState == STATE_CALIBRATING) { driftCalDirty = false; saveDriftCalibration(); }
    }

    if (buttonPressed) {
      buttonPressed = false;
      if (sysState == STATE_NORMAL && currentMillis - lastButtonHandled > 500) {
        lastButtonHandled = currentMillis;
        startOrientationCalibration();
      }
    }

    // --- Calibration finished (signalled by the physics task) ---
    if (calCompleteFlag) {
      calCompleteFlag = false;
      if (calWasStable) {
        hapticCalSuccess();
        Serial.println(F("[CAL] Done - pitch and yaw zeroed at your snare aim."));
      } else {
        hapticCalWarn();
        Serial.println(F("[CAL] Done, but the stick was moving - hold it steadier for a cleaner zero."));
      }
      lastLedToggle = currentMillis;
    }

    // --- LED ---
    if (sysState == STATE_BOOT_SETTLE) {
      digitalWrite(PIN_STATUS_LED, HIGH);
    } else if (sysState == STATE_CALIBRATING || sysState == STATE_MAG_FIG8) {
      if (currentMillis - lastLedToggle >= 100) {  // 5 Hz
        lastLedToggle = currentMillis; ledState = !ledState; digitalWrite(PIN_STATUS_LED, ledState);
      }
    } else if (currentMillis - lastLedToggle >= 1000) {
      lastLedToggle = currentMillis; ledState = !ledState; digitalWrite(PIN_STATUS_LED, ledState);
    }

    // --- State machine ---
    if (sysState == STATE_BOOT_SETTLE) {
      if (currentMillis - stateTimer >= BOOT_SETTLE_MS) {
        buttonPressed = false;
        startOrientationCalibration();
      }
    }
    else if (sysState == STATE_MAG_FIG8) {
      if (currentMillis - lastMagSampleTime >= MAG_CAL_PERIOD_MS && magSampleCount < MAX_MAG_SAMPLES) {
        lastMagSampleTime = currentMillis;
        float mx, my, mz;
        if (readMagnetometer(mx, my, mz)) magBuffer[magSampleCount++] = {mx, my, mz};
      }
      if (currentMillis - stateTimer >= MAG_CAL_DURATION_MS) {
        bool pass = processMagnetometerCalibration();
        if (pass) hapticCalSuccess(); else hapticCalWarn();
        // 18 s of waving leaves the gyro-integrated attitude meaningless either way.
        Serial.println(F("[MAGCAL] Now re-zeroing orientation."));
        startOrientationCalibration();
      }
    }
    else if (sysState == STATE_NORMAL) {
      // Split trigger/fetch so an in-flight magnetometer conversion never delays a hit packet.
      if (!magPending) {
        if (currentMillis - lastMagRead >= 20) { magStartMeasurement(); magTrigTime = currentMillis; magPending = true; }
      } else if (currentMillis - magTrigTime >= 4) {
        float mX, mY, mZ;
        if (magFetchIfReady(mX, mY, mZ)) {
          float cX = (mX - magBiasX) * magScaleX;
          float cY = (mY - magBiasY) * magScaleY;
          float cZ = (mZ - magBiasZ) * magScaleZ;
          portENTER_CRITICAL(&magMux);
          magBodyX = cX; magBodyY = cY; magBodyZ = cZ; magSeq++;
          portEXIT_CRITICAL(&magMux);
          magPending = false; lastMagRead = currentMillis;
        } else if (currentMillis - magTrigTime > 25) {
          magPending = false; lastMagRead = currentMillis;
        }
      }
    }
  }
}

// ==========================================
// ARDUINO SETUP
// ==========================================
void setup() {
  // LTC2954 releases EN unless KILL is driven high within 512 ms of power-on, so this stays first.
  pinMode(PMIC_KILL, OUTPUT); digitalWrite(PMIC_KILL, HIGH);
  pinMode(PIN_STATUS_LED, OUTPUT); digitalWrite(PIN_STATUS_LED, HIGH);
  pinMode(IMU1_CS, OUTPUT); digitalWrite(IMU1_CS, HIGH);
  pinMode(IMU2_CS, OUTPUT); digitalWrite(IMU2_CS, HIGH);

  Serial.begin(115200);
  SPI.begin(PIN_SPI_SCK, PIN_SPI_MISO, PIN_SPI_MOSI, -1);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);

  pinMode(PMIC_INT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PMIC_INT), isrCalibrate, FALLING);

  i2cMutex = xSemaphoreCreateMutex();
  hitQueue = xQueueCreate(10, sizeof(StickPacket));
  hapticQueue = xQueueCreate(8, sizeof(uint8_t));

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_VBAT_SENSE, ADC_11db);  // full-scale ~3.1 V, battery divides to max 2.1 V

  writeRegisterHaptic(0x01, 0x00); writeRegisterHaptic(0x03, 0x06); 
  writeRegisterHaptic(0x16, 0x56); writeRegisterHaptic(0x17, 0xFF);
  writeRegisterHaptic(0x1A, 0xB6); writeRegisterHaptic(0x1B, 0x93);
  writeRegisterHaptic(0x1C, 0x75); writeRegisterHaptic(0x1D, 0x80);
  
  initMagnetometer();

  // Run both IMUs off the board TCXO: crystal-accurate ODR that does not wander with temperature,
  // and the two parts sample on the same edge. Note this scales the ODR by 32.768/32.
  selectBankIMU(IMU1_CS, 0x01); selectBankIMU(IMU2_CS, 0x01);
  writeRegisterIMU(IMU1_CS, 0x7B, 0x04); writeRegisterIMU(IMU2_CS, 0x7B, 0x04);  // INTF_CONFIG5: pin 9 = CLKIN
  selectBankIMU(IMU1_CS, 0x00); selectBankIMU(IMU2_CS, 0x00);
  writeRegisterIMU(IMU1_CS, 0x4D, 0x95); writeRegisterIMU(IMU2_CS, 0x4D, 0x95);  // INTF_CONFIG1: RTC_MODE

  writeRegisterIMU(IMU1_CS, 0x4F, 0x06); writeRegisterIMU(IMU2_CS, 0x4F, 0x06); // gyro  +/-2000 dps, 1 kHz nominal -> 1024 Hz on CLKIN
  writeRegisterIMU(IMU1_CS, 0x50, 0x06); writeRegisterIMU(IMU2_CS, 0x50, 0x06); // accel +/-16 g,    1 kHz nominal -> 1024 Hz on CLKIN
  writeRegisterIMU(IMU1_CS, 0x4E, 0x0F); writeRegisterIMU(IMU2_CS, 0x4E, 0x0F);
  delay(100);

  uint8_t who1 = readRegisterIMU(IMU1_CS, 0x75), who2 = readRegisterIMU(IMU2_CS, 0x75);
  whoAmI1 = who1; whoAmI2 = who2;

  loadMagCalibration();
  loadDriftCalibration();

  xTaskCreatePinnedToCore(NetworkTask, "NetTask", 8192, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(PhysicsTask, "PhysTask", 8192, NULL, 2, NULL, 1); 
}

void loop() { vTaskDelete(NULL); }