/**
 * WALL-E CONTROLLER CODE
 *
 * Main Wall-E Controller Sketch (updated pin mapping for Nano)
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "Queue.hpp"
#include "MotorController.hpp"

/// Define pin-mapping (Nano-safe)
#define PWM_SPEED_L_PIN 5     // PWM capable
#define IN1_L_PIN       6     // Direction pins
#define IN2_L_PIN       7
#define PWM_SPEED_R_PIN 10    // PWM capable
#define IN1_R_PIN       8
#define IN2_R_PIN       9
#define SERVO_ENABLE_PIN 3    // Servo shield output enable pin

/// Battery level detection (optional)
//#define BAT_L
#ifdef BAT_L
  #define BATTERY_LEVEL_PIN A2
  #define BATTERY_MAX_VOLTAGE 12.6
  #define BATTERY_MIN_VOLTAGE 10.2
  #define DIVIDER_SCALING_FACTOR 0.3197

  //#define OLED
  #ifdef OLED
    #include <U8g2lib.h>
    U8G2_SH1106_128X64_NONAME_1_HW_I2C u8g2(U8G2_R0, 10);
  #endif
#endif

/// Define other constants
#define NUMBER_OF_SERVOS 7
#define SERVO_UPDATE_TIME 10
#define SERVO_OFF_TIME 6000
#define STATUS_CHECK_TIME 10000
#define CONTROLLER_THRESHOLD 1
#define MAX_SERIAL_LENGTH 5

/// Instantiate Objects
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

// Motor controllers — inA, inB, pwmPin
MotorController* motorL;
MotorController* motorR;

// Queue for animations
struct animation_t {
  uint16_t timer;
  int8_t servos[NUMBER_OF_SERVOS];
};

#define QUEUE_LENGTH 40
animation_t buffer[QUEUE_LENGTH];
Queue<animation_t> queue(QUEUE_LENGTH, buffer);

/// Motor Control Variables
int pwmspeed = 255;
int moveValue = 0;
int turnValue = 0;
int turnOffset = 0;
int motorDeadzone = 0;

/// Runtime Variables
unsigned long lastTime = 0;
unsigned long animeTimer = 0;
unsigned long motorTimer = 0;
unsigned long statusTimer = 0;
unsigned long updateTimer = 0;
bool autoMode = false;

// Serial Parsing
char firstChar;
char serialBuffer[MAX_SERIAL_LENGTH];
uint8_t serialLength = 0;

// Servo calibration
  int preset[][2] =  {{410,120},  // head rotation
                    {532,178},  // neck top
                    {120,310},  // neck bottom
                    {465,271},  // eye right
                    {278,479},  // eye left
                    {340,135},  // arm left
                    {150,360}}; // arm right

// Servo control arrays
// Servo Pins:	     0,   1,   2,   3,   4,   5,   6,   -,   -
// Joint Name:	  head,necT,necB,eyeR,eyeL,armL,armR,motL,motR
float curpos[] = { 248, 560, 140, 475, 270, 250, 290, 180, 180};  // Current position (units)
float setpos[] = { 248, 560, 140, 475, 270, 250, 290,   0,   0};  // Required position (units)
float curvel[] = {   0,   0,   0,   0,   0,   0,   0,   0,   0};  // Current velocity (units/sec)
float maxvel[] = { 500, 400, 500,2400,2400, 600, 600, 255, 255};  // Max Servo velocity (units/sec)
float accell[] = { 350, 300, 480,1800,1800, 500, 500, 800, 800};  // Servo acceleration (units/sec^2)

// -------------------------------------------------------------------
// Setup
// -------------------------------------------------------------------
void setup() {
  // Servo enable (EO) pin
  pinMode(SERVO_ENABLE_PIN, OUTPUT);
  digitalWrite(SERVO_ENABLE_PIN, HIGH);

  // Servo shield
  pwm.begin();
  pwm.setPWMFreq(60);
  for (int i = 0; i < NUMBER_OF_SERVOS; i++) pwm.setPin(i, 0);

  // Serial
  Serial.begin(115200);
  Serial.println(F("--- Wall-E Control Sketch ---"));
  randomSeed(analogRead(0));

  if (queue.errors()) Serial.println(F("Error: Unable to allocate memory for servo animation queue"));

  Serial.println(F("Starting up the servo motors"));
  digitalWrite(SERVO_ENABLE_PIN, LOW);
  playAnimation(0);
  softStart(queue.pop(), 3500);

  #ifdef OLED
    Serial.println(F("Starting up the display"));
    u8g2.begin();
    displayLevel(100);
  #endif
	motorL = new MotorController(IN1_L_PIN, IN2_L_PIN, PWM_SPEED_L_PIN, false);
  motorR = new MotorController(IN1_R_PIN, IN2_R_PIN, PWM_SPEED_R_PIN, false);
  Serial.println(F("Startup complete; entering main loop"));
}

// -------------------------------------------------------------------
// Serial read/evaluate (unchanged logic)
// -------------------------------------------------------------------
void readSerial() {
  char inchar = Serial.read();
  if (inchar == '\n' || inchar == '\r') {
    if (serialLength > 0) evaluateSerial();
    serialBuffer[0] = 0;
    serialLength = 0;
  } else {
    if (serialLength == 0) firstChar = inchar;
    else {
      serialBuffer[serialLength-1] = inchar;
      serialBuffer[serialLength] = 0;
    }
    serialLength++;
    if (serialLength == MAX_SERIAL_LENGTH) {
      evaluateSerial();
      serialBuffer[0] = 0;
      serialLength = 0;
    }
  }
}

void evaluateSerial() {
  int number = atoi(serialBuffer);
  Serial.print(firstChar); Serial.println(number);

  if      (firstChar == 'X' && number >= -100 && number <= 100) turnValue = int(number * 2.55);
  else if (firstChar == 'Y' && number >= -100 && number <= 100) moveValue = int(number * 2.55);
  else if (firstChar == 'S' && number >= -100 && number <= 100) turnOffset = number;
  else if (firstChar == 'O' && number >=    0 && number <= 250) motorDeadzone = int(number);
  else if (firstChar == 'A') playAnimation(number);
  else if (firstChar == 'M' && number == 0) autoMode = false;
  else if (firstChar == 'M' && number == 1) autoMode = true;
  else if (firstChar == 'L' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[5] = int(number * 0.01 * (preset[5][1] - preset[5][0]) + preset[5][0]); }
  else if (firstChar == 'R' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[6] = int(number * 0.01 * (preset[6][1] - preset[6][0]) + preset[6][0]); }
  else if (firstChar == 'B' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[2] = int(number * 0.01 * (preset[2][1] - preset[2][0]) + preset[2][0]); }
  else if (firstChar == 'T' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[1] = int(number * 0.01 * (preset[1][1] - preset[1][0]) + preset[1][0]); }
  else if (firstChar == 'G' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[0] = int(number * 0.01 * (preset[0][1] - preset[0][0]) + preset[0][0]); }
  else if (firstChar == 'E' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[4] = int(number * 0.01 * (preset[4][1] - preset[4][0]) + preset[4][0]); }
  else if (firstChar == 'U' && number >= 0 && number <= 100) { autoMode = false; queue.clear(); setpos[3] = int(number * 0.01 * (preset[3][1] - preset[3][0]) + preset[3][0]); }

  else if (firstChar == 'w') { moveValue = pwmspeed; turnValue = 0; setpos[0] = (preset[0][1] + preset[0][0]) / 2; }
  else if (firstChar == 'q') { moveValue = 0; turnValue = 0; setpos[0] = (preset[0][1] + preset[0][0]) / 2; }
  else if (firstChar == 's') { moveValue = -pwmspeed; turnValue = 0; setpos[0] = (preset[0][1] + preset[0][0]) / 2; }
  else if (firstChar == 'a') { moveValue = 0; turnValue = -pwmspeed; setpos[0] = preset[0][0]; }
  else if (firstChar == 'd') { moveValue = 0; turnValue = pwmspeed; setpos[0] = preset[0][1]; }

  else if (firstChar == 'j') { setpos[4] = preset[4][0]; setpos[3] = preset[3][1]; }
  else if (firstChar == 'l') { setpos[4] = preset[4][1]; setpos[3] = preset[3][0]; }
  else if (firstChar == 'i') { setpos[4] = preset[4][0]; setpos[3] = preset[3][0]; }
  else if (firstChar == 'k') { setpos[4] = int(0.4 * (preset[4][1] - preset[4][0]) + preset[4][0]); setpos[3] = int(0.4 * (preset[3][1] - preset[3][0]) + preset[3][0]); }

  else if (firstChar == 'f') { setpos[1] = preset[1][0]; setpos[2] = (preset[2][1] + preset[2][0])/2; }
  else if (firstChar == 'g') { setpos[1] = preset[1][1]; setpos[2] = preset[2][0]; }
  else if (firstChar == 'h') { setpos[1] = preset[1][0]; setpos[2] = preset[2][0]; }

  else if (firstChar == 'b') { setpos[5] = preset[5][0]; setpos[6] = preset[6][1]; }
  else if (firstChar == 'n') { setpos[5] = (preset[5][0] + preset[5][1]) / 2; setpos[6] = (preset[6][0] + preset[6][1]) / 2; }
  else if (firstChar == 'm') { setpos[5] = preset[5][1]; setpos[6] = preset[6][0]; }
}

// -------------------------------------------------------------------
// Animations, servos and motors management (unchanged logic)
// -------------------------------------------------------------------
void manageAnimations() {
  if ((queue.size() > 0) && (animeTimer <= millis())) {
    animation_t newValues = queue.pop();
    animeTimer = millis() + newValues.timer;
    for (int i = 0; i < NUMBER_OF_SERVOS; i++) {
      setpos[i] = int(newValues.servos[i] * 0.01 * (preset[i][1] - preset[i][0]) + preset[i][0]);
    }
  } else if (autoMode && queue.empty() && (animeTimer <= millis())) {
    for (int i = 0; i < NUMBER_OF_SERVOS; i++) {
      if (random(2) == 1) {
        if (i == 0 || i == 1 || i == 5 || i == 6) {
          unsigned int min = preset[i][0];
          unsigned int max = preset[i][1];
          if (min > max) { min = max; max = preset[i][0]; }
          setpos[i] = random(min, max+1);
        } else if (i == 3) {
          int midPos1 = int((preset[i][1] - preset[i][0])*0.4 + preset[i][0]);
          int midPos2 = int((preset[i+1][1] - preset[i+1][0])*0.4 + preset[i+1][0]);
          if (random(2) == 1) {
            setpos[i] = random(midPos1, preset[i][0]);
            float multiplier = (setpos[i] - midPos1) / float(preset[i][0] - midPos1);
            setpos[i+1] = ((1 - multiplier) * (midPos2 - preset[i+1][0])) + preset[i+1][0];
          } else {
            setpos[i] = random(midPos1, preset[i][0]);
            float multiplier = (setpos[i] - preset[i][1]) / float(preset[i][0] - preset[i][1]);
            setpos[i+1] = (multiplier * (preset[i+1][1] - preset[i+1][0])) + preset[i+1][0];
          }
        }
      }
    }
    animeTimer = millis() + random(500, 3000);
  }
}

void manageServos(float dt) {

  bool moving = false;
  for (int i = 0; i < NUMBER_OF_SERVOS; i++) {
    float posError = setpos[i] - curpos[i];
    if (abs(posError) > CONTROLLER_THRESHOLD && (setpos[i] != -1)) {
      digitalWrite(SERVO_ENABLE_PIN, LOW);
      moving = true;
      bool dir = posError >= 0;
      float acceleration = accell[i];
      if ((curvel[i] * curvel[i] / (2 * accell[i])) > abs(posError)) acceleration = -accell[i];
      if (dir) curvel[i] += acceleration * dt / 1000.0;
      else curvel[i] -= acceleration * dt / 1000.0;
      if (curvel[i] > maxvel[i]) curvel[i] = maxvel[i];
      if (curvel[i] < -maxvel[i]) curvel[i] = -maxvel[i];
      float dP = curvel[i] * dt / 1000.0;
      if (abs(dP) < abs(posError)) curpos[i] += dP;
      else curpos[i] = setpos[i];
      pwm.setPWM(i, 0, curpos[i]);
    } else {
      curvel[i] = 0;
    }
  }
  if (moving) motorTimer = millis();
  else if (millis() - motorTimer >= SERVO_OFF_TIME) {
    for (int i = 0; i < NUMBER_OF_SERVOS; i++) pwm.setPin(i, 0);
  }

}

void softStart(animation_t targetPos, int timeMs) {
  for (int i = 0; i < NUMBER_OF_SERVOS; i++) {
    if (targetPos.servos[i] >= 0) {
      curpos[i] = int(targetPos.servos[i] * 0.01 * (preset[i][1] - preset[i][0]) + preset[i][0]);
      unsigned long endTime = millis() + timeMs / NUMBER_OF_SERVOS;
      while (millis() < endTime) {
        pwm.setPWM(i, 0, curpos[i]);
        delay(10);
        pwm.setPin(i, 0);
        delay(50);
      }
      pwm.setPWM(i, 0, curpos[i]);
      setpos[i] = curpos[i];
    }
  }
}

void manageMotors(float dt) {
  setpos[NUMBER_OF_SERVOS]     = moveValue - turnValue;
  setpos[NUMBER_OF_SERVOS + 1] = moveValue + turnValue;

  if (setpos[NUMBER_OF_SERVOS] != 0) setpos[NUMBER_OF_SERVOS] -= turnOffset;
  if (setpos[NUMBER_OF_SERVOS + 1] != 0) setpos[NUMBER_OF_SERVOS + 1] += turnOffset;

  for (int i = NUMBER_OF_SERVOS; i < NUMBER_OF_SERVOS + 2; i++) {
    float velError = setpos[i] - curvel[i];
    if (abs(velError) > CONTROLLER_THRESHOLD && (setpos[i] != -1)) {
      float acceleration = accell[i];
      if (setpos[i] < curvel[i] && curvel[i] >= 0) acceleration = -accell[i];
      else if (setpos[i] < curvel[i] && curvel[i] < 0) acceleration = -accell[i];
      else if (setpos[i] > curvel[i] && curvel[i] < 0) acceleration = accell[i];
      float dV = acceleration * dt / 1000.0;
      if (abs(dV) < abs(velError)) curvel[i] += dV;
      else curvel[i] = setpos[i];
    } else {
      curvel[i] = setpos[i];
    }

    if (curvel[i] > 0) curvel[i] += motorDeadzone;
    else if (curvel[i] < 0) curvel[i] -= motorDeadzone;

    if (curvel[i] > maxvel[i]) curvel[i] = maxvel[i];
    if (curvel[i] < -maxvel[i]) curvel[i] = -maxvel[i];
  }

 motorL->setSpeed(curvel[NUMBER_OF_SERVOS]);
 motorR->setSpeed(curvel[NUMBER_OF_SERVOS + 1]);
}

#ifdef BAT_L
void checkBatteryLevel() {
  float voltage = analogRead(BATTERY_LEVEL_PIN) * 5 / 1024.0;
  voltage = voltage / DIVIDER_SCALING_FACTOR;
  int percentage = int(100 * (voltage - BATTERY_MIN_VOLTAGE) / float(BATTERY_MAX_VOLTAGE - BATTERY_MIN_VOLTAGE));
  #ifdef OLED
    displayLevel(percentage);
  #endif
  Serial.print(F("Battery_")); Serial.println(percentage);
}
#endif

// -------------------------------------------------------------------
// Main loop
// -------------------------------------------------------------------
void loop() {
  if (Serial.available() > 0) readSerial();
  manageAnimations();

  if (millis() - updateTimer >= SERVO_UPDATE_TIME) {
    updateTimer = millis();
    unsigned long newTime = micros();
    float dt = (newTime - lastTime) / 1000.0;
    lastTime = newTime;
    manageServos(dt);
    manageMotors(dt);
  }

  if (millis() - statusTimer >= STATUS_CHECK_TIME) {
    statusTimer = millis();
    #ifdef BAT_L
      checkBatteryLevel();
    #endif
  }
}
