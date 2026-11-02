// XIAO SAMD21 + DFRobot analog PPG + 2N2222 haptic drivers
//
// Wiring
//   PPG VCC -> XIAO 3V3
//   PPG GND -> XIAO GND
//   PPG SIG -> XIAO D10 / A10
//   Haptic driver 1 base, through a base resistor -> XIAO D9
//   Haptic driver 2 base, through a base resistor -> XIAO D7
//   All grounds must be common.
//
// USB serial output format (one line at 100 Hz):
//   time_ms,raw_ppg,clipped
//
// USB serial commands accepted from the companion Python program:
//   HB       brief heartbeat pulse on D9
//   LEFT     test pulse on D9
//   RIGHT    test pulse on D7
//   BOTH     test pulse on D9 and D7
//   OFF      immediately stop both actuators
//   TEST     left, right, then both pulse sequence
//
// Important: This sketch never prints text status messages. It preserves a
// numeric-only CSV stream for the Python PPG parser.

const int PPG_PIN = A10;
const int HAPTIC_LEFT_PIN = D9;
const int HAPTIC_RIGHT_PIN = D7;

const uint32_t SAMPLE_RATE_HZ = 100;
const uint32_t SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;

const int ADC_MAX = 4095;
const int CLIP_MARGIN = 4;

const uint32_t HEARTBEAT_PULSE_MS = 35;
const uint32_t TEST_PULSE_MS = 120;

uint32_t nextSampleUs = 0;

bool leftActive = false;
bool rightActive = false;
uint32_t leftOffAtMs = 0;
uint32_t rightOffAtMs = 0;

char commandBuffer[24];
uint8_t commandLength = 0;

void startLeft(uint32_t durationMs) {
  digitalWrite(HAPTIC_LEFT_PIN, HIGH);
  leftActive = true;
  leftOffAtMs = millis() + durationMs;
}

void startRight(uint32_t durationMs) {
  digitalWrite(HAPTIC_RIGHT_PIN, HIGH);
  rightActive = true;
  rightOffAtMs = millis() + durationMs;
}

void stopAll() {
  digitalWrite(HAPTIC_LEFT_PIN, LOW);
  digitalWrite(HAPTIC_RIGHT_PIN, LOW);
  leftActive = false;
  rightActive = false;
}

void updateHaptics(uint32_t nowMs) {
  if (leftActive && (int32_t)(nowMs - leftOffAtMs) >= 0) {
    digitalWrite(HAPTIC_LEFT_PIN, LOW);
    leftActive = false;
  }

  if (rightActive && (int32_t)(nowMs - rightOffAtMs) >= 0) {
    digitalWrite(HAPTIC_RIGHT_PIN, LOW);
    rightActive = false;
  }
}

void runTestSequence() {
  // This gives a deterministic hardware sanity test. It is intentionally
  // non-blocking from the PPG sampler perspective except for brief scheduling.
  startLeft(TEST_PULSE_MS);
  delay(TEST_PULSE_MS + 80);
  startRight(TEST_PULSE_MS);
  delay(TEST_PULSE_MS + 80);
  startLeft(TEST_PULSE_MS);
  startRight(TEST_PULSE_MS);
}

void handleCommand(char *cmd) {
  if (strcmp(cmd, "HB") == 0) {
    startLeft(HEARTBEAT_PULSE_MS);
  } else if (strcmp(cmd, "LEFT") == 0) {
    startLeft(TEST_PULSE_MS);
  } else if (strcmp(cmd, "RIGHT") == 0) {
    startRight(TEST_PULSE_MS);
  } else if (strcmp(cmd, "BOTH") == 0) {
    startLeft(TEST_PULSE_MS);
    startRight(TEST_PULSE_MS);
  } else if (strcmp(cmd, "OFF") == 0) {
    stopAll();
  } else if (strcmp(cmd, "TEST") == 0) {
    runTestSequence();
  }
}

void pollSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      commandBuffer[commandLength] = '\0';
      if (commandLength > 0) {
        handleCommand(commandBuffer);
      }
      commandLength = 0;
      continue;
    }

    if (commandLength < sizeof(commandBuffer) - 1) {
      if (c >= 'a' && c <= 'z') {
        c = c - 'a' + 'A';
      }
      commandBuffer[commandLength++] = c;
    } else {
      commandLength = 0;
    }
  }
}

void setup() {
  Serial.begin(115200);

  analogReadResolution(12);
  pinMode(PPG_PIN, INPUT);

  pinMode(HAPTIC_LEFT_PIN, OUTPUT);
  pinMode(HAPTIC_RIGHT_PIN, OUTPUT);
  stopAll();

  nextSampleUs = micros();
}

void loop() {
  uint32_t nowMs = millis();
  updateHaptics(nowMs);
  pollSerialCommands();

  uint32_t nowUs = micros();
  if ((int32_t)(nowUs - nextSampleUs) < 0) {
    return;
  }

  nextSampleUs += SAMPLE_PERIOD_US;
  if ((int32_t)(nowUs - nextSampleUs) > (int32_t)SAMPLE_PERIOD_US) {
    nextSampleUs = nowUs + SAMPLE_PERIOD_US;
  }

  int raw = analogRead(PPG_PIN);
  int clipped = (raw <= CLIP_MARGIN || raw >= (ADC_MAX - CLIP_MARGIN)) ? 1 : 0;

  Serial.print(nowMs);
  Serial.print(",");
  Serial.print(raw);
  Serial.print(",");
  Serial.println(clipped);
}
