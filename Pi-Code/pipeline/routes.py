from flask import request, jsonify, session, redirect, url_for

@app.route('/motor', methods=['POST'])
def motor():
    stickX = request.form.get('stickX')
    stickY = request.form.get('stickY')

    if stickX is None or stickY is None:
        return jsonify({'status': 'Error', 'msg': 'Missing data'})

    xVal = int(float(stickX) * 100)
    yVal = int(float(stickY) * 100)

    if arduino.is_connected():
        arduino.send_command("X" + str(xVal))
        arduino.send_command("Y" + str(yVal))
        return jsonify({'status': 'OK'})

    return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})

@app.route('/servoControl', methods=['POST'])
def servoControl():

    servo = request.form.get('servo')
    value = request.form.get('value')

    if servo is None or value is None:
        return jsonify({'status': 'Error', 'msg': 'Missing data'})

    if arduino.is_connected():
        arduino.send_command(servo + value)
        return jsonify({'status': 'OK'})

    return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})