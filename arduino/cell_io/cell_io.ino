/* =============================================================================
 *  QUALITY INSPECTION CELL - Arduino I/O firmware  (conveyor motor + IR sensor)
 * =============================================================================
 *  The Arduino is a DUMB I/O BOX: it switches the conveyor motor and reads the
 *  IR sensor. All decisions are taken by the ROS 2 supervisor. The PC side is
 *  quality_cell/nodes/arduino_io_node.py, which exposes the SAME topics as the
 *  simulation (/conveyor/command, /conveyor/status, /ir_sensor/status).
 *
 *  Serial: 115200 baud, text lines ending in '\n'.
 *
 *  PC -> Arduino
 *     RUN        start the conveyor motor
 *     STOP       stop the conveyor motor
 *     PING       heartbeat (the bridge sends it every 200 ms)
 *
 *  Arduino -> PC
 *     BOOT quality_cell_io 1        after reset
 *     STAT <ir> <motor>             every 50 ms AND immediately on any change
 *                                   ir: 1 = OCCUPIED, 0 = FREE
 *                                   motor: 1 = RUNNING, 0 = STOPPED
 *     ACK RUN | ACK STOP            command accepted
 *     ERR INTERLOCK                 RUN refused because the IR beam is blocked
 *     ERR WATCHDOG                  motor stopped: no message from the PC
 *     ERR UNKNOWN <text>            unknown command
 *
 *  SAFETY (independent of ROS):
 *   * HW_INTERLOCK: the motor is switched OFF as soon as the IR beam is blocked
 *     and RUN is refused while it is blocked. This duplicates rule R2 of the
 *     supervisor in hardware, so the belt stops even if the PC is slow.
 *   * WATCHDOG: if nothing arrives from the PC for WATCHDOG_MS, the motor stops.
 *
 *  Wiring: see docs/13_hardware_arduino_xarm5.md
 * ========================================================================== */

// ---------------- pins (change to match your wiring)
const uint8_t PIN_IR        = 2;   // IR sensor digital output
const uint8_t PIN_MOTOR     = 7;   // relay / MOSFET / motor-driver enable
const uint8_t PIN_LED       = 13;  // on-board LED mirrors the IR state

// ---------------- behaviour
const bool     IR_ACTIVE_LOW  = true;   // most IR modules / break-beam receivers pull LOW when blocked
const bool     MOTOR_ACTIVE_HIGH = true;// relay module: some are active LOW -> set false
const bool     HW_INTERLOCK   = true;   // stop motor in firmware when IR is blocked
const uint16_t DEBOUNCE_MS    = 15;     // IR must be stable this long to change state
const uint16_t STATUS_MS      = 50;     // periodic STAT (20 Hz)
const uint16_t WATCHDOG_MS    = 1500;   // stop motor if the PC is silent

bool irOccupied = false, motorOn = false;
bool irRaw = false;
unsigned long irRawSince = 0, lastStatus = 0, lastRx = 0;
String rx;

bool readIrRaw() {
  bool level = digitalRead(PIN_IR);
  return IR_ACTIVE_LOW ? (level == LOW) : (level == HIGH);
}

void setMotor(bool on) {
  motorOn = on;
  digitalWrite(PIN_MOTOR, (on == MOTOR_ACTIVE_HIGH) ? HIGH : LOW);
}

void sendStatus() {
  Serial.print(F("STAT "));
  Serial.print(irOccupied ? 1 : 0);
  Serial.print(' ');
  Serial.println(motorOn ? 1 : 0);
  lastStatus = millis();
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;
  lastRx = millis();
  if (line == "RUN") {
    if (HW_INTERLOCK && irOccupied) { Serial.println(F("ERR INTERLOCK")); }
    else { setMotor(true); Serial.println(F("ACK RUN")); }
    sendStatus();
  } else if (line == "STOP") {
    setMotor(false); Serial.println(F("ACK STOP")); sendStatus();
  } else if (line == "PING") {
    // heartbeat only
  } else {
    Serial.print(F("ERR UNKNOWN ")); Serial.println(line);
  }
}

void setup() {
  pinMode(PIN_IR, INPUT_PULLUP);
  pinMode(PIN_MOTOR, OUTPUT);
  pinMode(PIN_LED, OUTPUT);
  setMotor(false);
  Serial.begin(115200);
  irRaw = irOccupied = readIrRaw();
  irRawSince = lastRx = millis();
  Serial.println(F("BOOT quality_cell_io 1"));
  sendStatus();
}

void loop() {
  unsigned long now = millis();

  // ---- read serial lines
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') { handleLine(rx); rx = ""; }
    else if (c != '\r' && rx.length() < 40) rx += c;
  }

  // ---- IR with debounce, report edges immediately
  bool r = readIrRaw();
  if (r != irRaw) { irRaw = r; irRawSince = now; }
  if (irRaw != irOccupied && now - irRawSince >= DEBOUNCE_MS) {
    irOccupied = irRaw;
    digitalWrite(PIN_LED, irOccupied ? HIGH : LOW);
    if (HW_INTERLOCK && irOccupied && motorOn) setMotor(false);   // hardware R2
    sendStatus();
  }

  // ---- watchdog
  if (motorOn && now - lastRx > WATCHDOG_MS) {
    setMotor(false);
    Serial.println(F("ERR WATCHDOG"));
    sendStatus();
  }

  // ---- periodic status (heartbeat for the IR sensor)
  if (now - lastStatus >= STATUS_MS) sendStatus();
}
