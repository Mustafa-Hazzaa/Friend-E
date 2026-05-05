# from flask import request, jsonify
#
# @control.route('/motor', methods=['POST'])
# def motor():
#
#     payload = request.get_json()
#
#     if not payload:
#         return jsonify({'status': 'Error', 'msg': 'Missing JSON'})
#
#     data = payload.get("data", {})
#
#     x = data.get("stickX")
#     y = data.get("stickY")
#
#     if x is None or y is None:
#         return jsonify({'status': 'Error', 'msg': 'Missing data'})
#
#     if not arduino.is_connected():
#         return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})
#
#     # ===== ORIGINAL LOGIC PRESERVED =====
#     arduino.send("X" + str(int(float(x) * 100)))
#     arduino.send("Y" + str(int(float(y) * 100)))
#
#     return jsonify({'status': 'OK'})



# @app.route("/servoControl", methods=["POST"])
# def servoControl():
#
#     payload = request.get_json()
#
#     if not payload:
#         return jsonify({'status': 'Error', 'msg': 'Missing JSON'})
#
#     data = payload.get("data", {})
#
#     code = data.get("servo")
#     value = data.get("value")
#
#     if code is None or value is None:
#         return jsonify({'status': 'Error', 'msg': 'Missing data'})
#
#     if not arduino.is_open:
#         return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})
#
#     arduino.write((str(code) + str(value) + "\n").encode())
#
#     return jsonify({'status': 'OK'})