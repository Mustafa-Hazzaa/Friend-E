import os
import json
from flask import Blueprint, jsonify
from web_interface.website_AI import AIPlanner
monitor_bp = Blueprint("monitor", __name__)

HISTORY_PATH = "uploads/History"
_ai = AIPlanner()


# 📜 GET ALL SESSIONS
@monitor_bp.route("/get-sessions", methods=["GET"])
def get_sessions():

    sessions = []

    if not os.path.exists(HISTORY_PATH):
        return jsonify([])

    for file in os.listdir(HISTORY_PATH):
        if file.endswith(".json"):

            path = os.path.join(HISTORY_PATH, file)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                sessions.append({
                    "file": file,
                    "session_timestamp": data.get("session_timestamp"),
                    "total_messages": len(data.get("messages", [])),
                    "messages": data.get("messages", [])
                })

            except Exception as e:
                print(f"[Monitor] Error reading {file}: {e}")

    # newest first
    sessions.sort(
        key=lambda x: x.get("session_timestamp", ""),
        reverse=True
    )

    return jsonify(sessions)


# 💬 GET SINGLE SESSION
@monitor_bp.route("/get-session/<filename>", methods=["GET"])
def get_session(filename):

    path = os.path.join(HISTORY_PATH, filename)

    if not os.path.exists(path):
        return jsonify({"error": "not found"}), 404

    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@monitor_bp.route("/analyze-child")
def analyze_child_route():
    import os, json

    sessions = []

    for file in os.listdir(HISTORY_PATH):
        path = os.path.join(HISTORY_PATH, file)

        with open(path, "r", encoding="utf-8") as f:
            sessions.append(json.load(f))

    result = _ai.analyze_child(sessions)

    return jsonify(result)