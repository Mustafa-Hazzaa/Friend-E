#ifndef MOTOR_CONTROLLER_HPP
#define MOTOR_CONTROLLER_HPP

#include <Arduino.h>

// Simple MotorController for H-bridge (inA, inB, pwmPin)
class MotorController {
public:
    MotorController(uint8_t _inA, uint8_t _inB, uint8_t _pwm, bool _brakeEnabled = false, bool _activeBrake = false);

    // Set speed: range -255 .. 255. Positive = forward, negative = reverse, 0 = stop
    void setSpeed(int pwmValue);

    ~MotorController() = default;

private:
    uint8_t inA, inB, pwmPin;
    bool brakeEnabled;
    bool activeBrakeMode;
};

inline MotorController::MotorController(uint8_t _inA, uint8_t _inB, uint8_t _pwm, bool _brakeEnabled, bool _activeBrake)
    : inA(_inA), inB(_inB), pwmPin(_pwm), brakeEnabled(_brakeEnabled), activeBrakeMode(_activeBrake)
{
    pinMode(inA, OUTPUT);
    pinMode(inB, OUTPUT);
    pinMode(pwmPin, OUTPUT);

    digitalWrite(inA, LOW);
    digitalWrite(inB, LOW);
    analogWrite(pwmPin, 0);

    // Debug
    Serial.print("MotorController ctor: inA=");
    Serial.print(inA);
    Serial.print(" inB=");
    Serial.print(inB);
    Serial.print(" pwm=");
    Serial.println(pwmPin);
}

inline void MotorController::setSpeed(int pwmValue) {
    Serial.print("setSpeed called on pwmPin ");
    Serial.print(pwmPin);
    Serial.print(" value=");
    Serial.println(pwmValue);

    if (pwmValue > 255) pwmValue = 255;
    else if (pwmValue < -255) pwmValue = -255;

    if (pwmValue > 0) {
        // Forward
        digitalWrite(inA, HIGH);
        digitalWrite(inB, LOW);
        analogWrite(pwmPin, abs(pwmValue));
        Serial.println(" -> forward: inA=HIGH inB=LOW PWM set");
        return;
    }

    if (pwmValue < 0) {
        // Reverse
        digitalWrite(inA, LOW);
        digitalWrite(inB, HIGH);
        analogWrite(pwmPin, abs(pwmValue));
        Serial.println(" -> reverse: inA=LOW inB=HIGH PWM set");
        return;
    }

    // Stop (coast by default)
    if (brakeEnabled && activeBrakeMode) {
        digitalWrite(inA, HIGH);
        digitalWrite(inB, HIGH);
        analogWrite(pwmPin, 255);
        Serial.println(" -> active brake applied");
    } else {
        analogWrite(pwmPin, 0);
        digitalWrite(inA, LOW);
        digitalWrite(inB, LOW);
        Serial.println(" -> coast (PWM=0, inA=LOW, inB=LOW)");
    }
}

#endif // MOTOR_CONTROLLER_HPP
