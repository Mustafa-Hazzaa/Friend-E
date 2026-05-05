import requests
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required

from web_interface.arduino import arduino   # shared ArduinoDevice instance
from web_interface.pi_bridge import speak

control = Blueprint('control', __name__)


@control.route('/motor', methods=['POST'])
@login_required
def motor():
    x = request.form.get('stickX')
    y = request.form.get('stickY')

    if x is None or y is None:
        return jsonify({'status': 'error', 'msg': 'Missing data'})

    payload = {
        "type": "commands",
        "data": {
            "stickX": float(x),
            "stickY": float(y)
        }
    }

    try:
        requests.post(
            current_app.config["PI_URL"].rstrip("/"),
            json=payload,
            timeout=0.2
        )

        return jsonify({'status': 'ok'})

    except requests.RequestException as e:
        return jsonify({
            'status': 'error',
            'msg': f'Pi unreachable: {str(e)}'
        })


@control.route('/servoControl', methods=['POST'])
@login_required
def servoControl():

    code = request.form.get('servo')
    value = request.form.get('value')

    if code is None or value is None:
        return jsonify({'status': 'Error', 'msg': 'Missing data'})

    payload = {
        "type": "servo",
        "data": {
            "servo": code,
            "value": value
        }
    }

    try:
        requests.post(
            current_app.config["PI_URL"].rstrip("/") + "/servoControl",
            json=payload,
            timeout=0.5
        )

        return jsonify({'status': 'OK'})

    except requests.RequestException as e:
        return jsonify({'status': 'Error', 'msg': str(e)})


@control.route('/tts', methods=['POST'])
@login_required
def tts():
    text = request.form.get('text', '').strip()

    if not text:
        return jsonify({'status': 'error', 'msg': 'No text'})

    ok = speak(text)

    if not ok:
        return jsonify({'status': 'error', 'msg': 'TTS failed'})

    return jsonify({'status': 'ok'})