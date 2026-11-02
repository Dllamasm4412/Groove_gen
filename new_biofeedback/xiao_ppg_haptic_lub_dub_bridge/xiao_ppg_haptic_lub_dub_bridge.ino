// XIAO SAMD21 + DFRobot analog PPG + two 2N2222 haptic drivers
//
// This sketch streams raw PPG to the companion Python estimator and receives
// haptic commands over the SAME USB serial connection.
//
// Wiring
//   PPG VCC -> XIAO 3V3
//   PPG GND -> XIAO GND
//   PPG SIG -> XIAO D10 / A10
//   Haptic driver 1 base, through a base resistor -> XIAO D9
//   Haptic driver 2 base, through a base resistor -> XIAO D7
//   XIAO GND, PPG GND, and actuator-driver supply GND -> common ground
//
// Numeric USB serial output at 100 Hz (do not add debug prints):
//   time_ms,raw_ppg,clipped
//
// Commands accepted from Python, each terminated with newline:
//   HB       heartbeat-inspired paired pattern: D9 then D7
//   LEFT     test pulse on D9
//   RIGHT    test pulse on D7
//   BOTH     test pulse on D9 and D7 together
//   OFF      stop motors and cancel pending pattern events
//   TEST     D9, then D7, then both (hardware wiring test)
//
// The built-in LED is lit whenever D9 or D7 is HIGH, so a received command is
// visible on the board even if no motor moves.
//
// The HB pattern is perceptual: D9 gives the primary "bum", then D7 provides
// a shorter secondary "bum" after a brief delay. It is not a measurement of
// cardiac S1/S2 heart sounds.

#include <string.h>

const int PPG_PIN = A10;
const int HAPTIC_LEFT_PIN = D9;
const int HAPTIC_RIGHT_PIN = D7;

const uint32_t SAMPLE_RATE_HZ = 100;
const uint32_t SAMPLE_PERIOD_US = 1000000UL / SAMPLE_RATE_HZ;

const int ADC_MAX = 4095;
const int CLIP_MARGIN = 4;

// ---- Heartbeat-inspired D9 -> D7 haptic pattern ----
// Adjust these three values to tune the subjective "bum-bum" feel.
// 2026-09-28: 40/25 ms were barely felt (ERM motors need ~50-100 ms to spin
// up); raised to 80/60 ms, then 70/50 ms after the developer asked for a
// little less intensity. The pattern ends by 200 ms, inside the 600 ms beat
// period at the 100 bpm pacing ceiling.
const uint32_t HEARTBEAT_PRIMARY_MS = 70;     // D9 duration; first/stronger bump
const uint32_t HEARTBEAT_GAP_MS = 150;        // D9-start to D7-start delay
const uint32_t HEARTBEAT_SECONDARY_MS = 50;   // D7 duration; second/lighter bump

// Hardware-test pulse duration used by LEFT, RIGHT, and BOTH commands.
const uint32_t TEST_PULSE_MS = 120;

uint32_t nextSampleUs = 0;

bool leftActive = false;
bool rightActive = false;
bool heartbeatSecondPending = false;

uint32_t leftOffAtMs = 0;
uint32_t rightOffAtMs = 0;
uint32_t heartbeatSecondAtMs = 0;

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
  heartbeatSecondPending = false;
}

void startHeartbeatPattern() {
  // Cancel an unfinished old pattern before starting a new heartbeat.
  heartbeatSecondPending = false;

  // Primary tactile beat: D9 immediately.
  startLeft(HEARTBEAT_PRIMARY_MS);

  // Secondary tactile beat: D7 scheduled without delay(), so PPG acquisition
  // and serial processing continue uninterrupted.
  heartbeatSecondPending = true;
  heartbeatSecondAtMs = millis() + HEARTBEAT_GAP_MS;
}

void updateHaptics(uint32_t nowMs) {
  // Start the secondary D7 event when its scheduled time arrives.
  if (heartbeatSecondPending && (int32_t)(nowMs - heartbeatSecondAtMs) >= 0) {
    startRight(HEARTBEAT_SECONDARY_MS);
    heartbeatSecondPending = false;
  }

  // Stop D9 after its assigned duration.
  if (leftActive && (int32_t)(nowMs - leftOffAtMs) >= 0) {
    digitalWrite(HAPTIC_LEFT_PIN, LOW);
    leftActive = false;
  }

  // Stop D7 after its assigned duration.
  if (rightActive && (int32_t)(nowMs - rightOffAtMs) >= 0) {
    digitalWrite(HAPTIC_RIGHT_PIN, LOW);
    rightActive = false;
  }

  // Mirror the motor pins on the built-in LED (active LOW on XIAO SAMD21).
  digitalWrite(LED_BUILTIN, (leftActive || rightActive) ? LOW : HIGH);
}

void runTestSequence() {
  // This blocks only when manually invoked for a wiring test. It is never used
  // during normal heartbeat feedback. PPG CSV output resumes afterward.
  stopAll();

  startLeft(TEST_PULSE_MS);
  delay(TEST_PULSE_MS + 80);

  startRight(TEST_PULSE_MS);
  delay(TEST_PULSE_MS + 80);

  startLeft(TEST_PULSE_MS);
  startRight(TEST_PULSE_MS);
}

void handleCommand(char *cmd) {
  if (strcmp(cmd, "HB") == 0) {
    startHeartbeatPattern();
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
      // Accept lowercase commands too.
      if (c >= 'a' && c <= 'z') {
        c = c - 'a' + 'A';
      }
      commandBuffer[commandLength++] = c;
    } else {
      // Discard an overlong malformed command.
      commandLength = 0;
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Read 12-bit PPG samples from 0 to 4095.
  analogReadResolution(12);
  pinMode(PPG_PIN, INPUT);

  pinMode(HAPTIC_LEFT_PIN, OUTPUT);
  pinMode(HAPTIC_RIGHT_PIN, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  stopAll();

  nextSampleUs = micros();
}

void loop() {
  uint32_t nowMs = millis();

  // These run on every pass, independently of the 100 Hz sample scheduler.
  updateHaptics(nowMs);
  pollSerialCommands();

  uint32_t nowUs = micros();
  if ((int32_t)(nowUs - nextSampleUs) < 0) {
    return;
  }

  // Maintain a 100 Hz sample cadence. If USB serial printing ever makes us
  // much later than one period, resynchronize rather than burst sampling.
  nextSampleUs += SAMPLE_PERIOD_US;
  if ((int32_t)(nowUs - nextSampleUs) > (int32_t)SAMPLE_PERIOD_US) {
    nextSampleUs = nowUs + SAMPLE_PERIOD_US;
  }

  int raw = analogRead(PPG_PIN);
  int clipped = (raw <= CLIP_MARGIN || raw >= (ADC_MAX - CLIP_MARGIN)) ? 1 : 0;

  // Keep the serial stream strictly numeric for the Python parser.
  Serial.print(nowMs);
  Serial.print(",");
  Serial.print(raw);
  Serial.print(",");
  Serial.println(clipped);
}
