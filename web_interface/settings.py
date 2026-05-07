# import subprocess
# from flask import Blueprint, request, jsonify, redirect, url_for
# from flask_login import login_required
# settings = Blueprint('settings', __name__)
# @settings.route('/mode', methods=['POST'])
# @login_required
# def mode():
#     """Switch between auto animation mode and manual servo mode."""
#     val = request.form.get('value')
#     if not arduino.is_connected():
#         return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})
#     arduino.send("M" + str(val))
#     return jsonify({'status': 'OK'})
#
#
# @settings.route('/mode', methods=['POST'])
# @login_required
# def motor_offset():
#     deadzone = request.form.get('motorOff')
#     steer    = request.form.get('steerOff')
#     if not arduino.is_connected():
#         return jsonify({'status': 'Error', 'msg': 'Arduino not connected'})
#     if deadzone:
#         arduino.send("O" + str(deadzone))
#     if steer:
#         arduino.send("S" + str(steer))
#     return jsonify({'status': 'OK'})
#
#
# @settings.route('/shutdown', methods=['POST'])
# @login_required
# def shutdown():
#     subprocess.run(['sudo', 'nohup', 'shutdown', '-h', 'now'], stdout=subprocess.PIPE)
#     return jsonify({'status': 'OK'})
#
#
# @settings.route('/restart', methods=['POST'])
# @login_required
# def restart():
#     subprocess.Popen("sleep 5 && sudo systemctl restart walle", shell=True)
#     return redirect(url_for('auth.login'))