# from flask import Blueprint, request, jsonify, current_app
# import os
# import json
# from datetime import datetime
#
# history_bp = Blueprint("history", __name__)
#
# @history_bp.route("/upload_history", methods=["POST"])
# def upload_history():
#
#     data = request.get_json()
#
#     if not data:
#         return jsonify({"status": "error", "msg": "No JSON received"}), 400
#
#     folder = os.path.join("uploads", "history")
#     os.makedirs(folder, exist_ok=True)
#
#     filename = f"history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
#     filepath = os.path.join(folder, filename)
#
#     with open(filepath, "w", encoding="utf-8") as f:
#         json.dump(data, f, indent=4, ensure_ascii=False)
#
#     return jsonify({
#         "status": "success",
#         "saved_to": filepath
#     })