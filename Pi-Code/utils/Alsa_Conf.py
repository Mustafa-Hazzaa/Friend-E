"""
command_executor.py

Parses AI response JSON and sends commands over serial to Arduino.
Reuses MotorController and Actions from your existing codebase.

Serial format sent per command: "F50\n"  (char + value 0-100 + newline)

Run with real Arduino:  python command_executor.py
Run without Arduino:    python command_executor.py --mock
"""

import json
import sys
import time
from typing import Optional

from motor_controller import MotorController
from Actions import Actions


# ─── Valid command characters ──────────────────────────────
VALID_CHARS  = {"F", "B", "L", "R"}
VALUE_MIN    = 0
VALUE_MAX    = 100


# ─── Validation ───────────────────────────────────────────

def validate_response(response: dict) -> tuple[bool, str]:
    """
    Validate the AI response dict.
    Returns (is_valid, error_message).
    """
    if not isinstance(response, dict):
        return False, "Response must be a JSON object"

    resp_type = response.get("response_type")
    if not resp_type:
        return False, "Missing 'response_type' field"

    if resp_type == "command":
        command_data = response.get("command_data")
        if command_data is None:
            return False, "response_type is 'command' but 'command_data' is missing"
        if not isinstance(command_data, list):
            return False, "'command_data' must be an array"
        if len(command_data) == 0:
            return False, "'command_data' array is empty"

        for i, item in enumerate(command_data):
            if not isinstance(item, dict):
                return False, f"command_data[{i}] must be an object"
            if "char" not in item:
                return False, f"command_data[{i}] missing 'char' field"
            if "value" not in item:
                return False, f"command_data[{i}] missing 'value' field"
            if item["char"] not in VALID_CHARS:
                return False, (f"command_data[{i}] invalid char '{item['char']}'. "
                               f"Valid: {sorted(VALID_CHARS)}")
            if not isinstance(item["value"], (int, float)):
                return False, f"command_data[{i}] value must be a number"
            if not (VALUE_MIN <= item["value"] <= VALUE_MAX):
                return False, (f"command_data[{i}] value {item['value']} "
                               f"out of range [{VALUE_MIN}, {VALUE_MAX}]")

    return True, ""


# ─── Serial sender ─────────────────────────────────────────

def send_command(mc: MotorController, char: str, value: int) -> bool:
    """
    Send one command to Arduino: "F50\n"
    Returns True if sent successfully.
    """
    serial_str = f"{char}{value}"
    print(f"[CMD] Sending '{serial_str}\\n' → Arduino")
    try:
        mc.send_action(serial_str)
        return True
    except Exception as e:
        print(f"[CMD] Serial error: {e}")
        return False


# ─── Main executor ─────────────────────────────────────────

def execute_response(mc: Optional[MotorController], response: dict) -> None:
    """
    Parse and execute one AI response.

    Args:
        mc:       MotorController instance (or None for dry-run logging)
        response: Parsed AI response dict
    """
    # Step 1: Validate
    valid, error = validate_response(response)
    if not valid:
        print(f"[CMD] Invalid response — {error}")
        return

    resp_type = response["response_type"]
    print(f"[CMD] response_type = '{resp_type}'")

    # Step 2: Route
    if resp_type != "command":
        text = response.get("response", "")
        print(f"[CMD] Answer (no serial): '{text}'")
        return

    # Step 3: Send each command
    command_data = response["command_data"]
    print(f"[CMD] Executing {len(command_data)} command(s)...")

    for i, item in enumerate(command_data):
        char  = item["char"]
        value = int(item["value"])
        print(f"[CMD] Step {i+1}/{len(command_data)}: {char}{value}")

        if mc is not None:
            success = send_command(mc, char, value)
            if not success:
                print(f"[CMD] Step {i+1} failed — stopping sequence.")
                break
        else:
            # Dry run — just print what would be sent
            print(f"[CMD] (dry-run) would send '{char}{value}\\n'")

        time.sleep(0.1)   # small gap between commands

    print("[CMD] Sequence complete.")


# ─── Test data ─────────────────────────────────────────────

TEST_RESPONSE_COMMAND = {
    "response_type": "command",
    "command_data": [
        {"char": "B", "value": 12} , 
        {"char": "F", "value": 72}
    ]
}

TEST_RESPONSE_ANSWER = {
    "response_type": "answer",
    "response": "Beep boop! I am WALL-E."
}


# ─── Entry point ───────────────────────────────────────────

if __name__ == "__main__":
    use_mock = "--mock" in sys.argv

    print("=" * 50)
    print("  Command Executor — Serial Test")
    print(f"  Mode: {'mock (no Arduino)' if use_mock else 'real serial'}")
    print("=" * 50)

    if use_mock:
        mc = None
        print("[Setup] Mock mode — serial output will be printed only.\n")
    else:
        mc = Actions.check_the_arduino()
        if mc is None:
            print("[Setup] No Arduino found. Run with --mock to test without hardware.")
            sys.exit(1)
        print()

    # ── Test 1: command response ───────────────────────────
    print("── Test 1: command response ──────────────────")
    print(f"Input:  {json.dumps(TEST_RESPONSE_COMMAND)}")
    execute_response(mc, TEST_RESPONSE_COMMAND)

    print()

    # ── Test 2: answer response (no serial) ───────────────
    print("── Test 2: answer response ───────────────────")
    print(f"Input:  {json.dumps(TEST_RESPONSE_ANSWER)}")
    execute_response(mc, TEST_RESPONSE_ANSWER)