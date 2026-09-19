import os
import json
from datetime import datetime
from flask import Blueprint, jsonify, request, session
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash

from web_interface.website_AI import AIPlanner

monitor_bp = Blueprint("monitor", __name__)

HISTORY_PATH = "uploads/History"
ANALYSIS_CACHE = "uploads/last_analysis.json"

_ai = AIPlanner()



@monitor_bp.route("/monitor-login", methods=["POST"])
@login_required
def monitor_login():
    password = request.form.get("password", "")

    if check_password_hash(current_user.password_hash, password):
        session["monitor_active"] = True
        return jsonify({"ok": True})

    return jsonify({"ok": False})



@monitor_bp.route("/sign-out-monitor", methods=["POST"])
def sign_out_monitor():
    session.pop("monitor_active", None)
    return jsonify({"ok": True})



def normalize_messages(data):

    msgs = data.get("messages")

    if isinstance(msgs, list):
        return msgs

    if isinstance(msgs, dict):
        out = []

        if msgs.get("question"):
            out.append({
                "role": "user",
                "content": msgs.get("question")
            })

        if msgs.get("answer"):
            out.append({
                "role": "assistant",
                "content": msgs.get("answer")
            })

        return out

    if data.get("session_type") == "summary":
        return [{
            "role": "assistant",
            "content": data.get("data", {}).get("summary", "")
        }]

    return []



@monitor_bp.route("/get-sessions", methods=["GET"])
def get_sessions():

    if not session.get("monitor_active"):
        return jsonify({"error": "Unauthorized"}), 401

    sessions = []

    if not os.path.exists(HISTORY_PATH):
        return jsonify([])

    for file in os.listdir(HISTORY_PATH):

        if not file.endswith(".json"):
            continue

        path = os.path.join(HISTORY_PATH, file)

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            msgs = normalize_messages(data)

            sessions.append({
                "file": file,
                "session_timestamp":
                    data.get("session_timestamp")
                    or data.get("timestamp"),

                "total_messages": len(msgs),
                "messages": msgs
            })

        except Exception as e:
            print(f"[Monitor] Error reading {file}: {e}")

    sessions.sort(
        key=lambda x: x.get("session_timestamp") or "",
        reverse=True
    )

    return jsonify(sessions)



@monitor_bp.route("/get-session/<filename>", methods=["GET"])
def get_session(filename):

    if not session.get("monitor_active"):
        return jsonify({"error": "Unauthorized"}), 401

    path = os.path.join(HISTORY_PATH, filename)

    if not os.path.exists(path):
        return jsonify({"error": "not found"}), 404

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        msgs = normalize_messages(data)

        return jsonify({
            "messages": msgs
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@monitor_bp.route("/analyze-child", methods=["GET"])
def analyze_child_cached():

    if not session.get("monitor_active"):
        return jsonify({"error": "Unauthorized"}), 401

    if not os.path.exists(ANALYSIS_CACHE):
        return jsonify({"no_cache": True})

    try:
        with open(ANALYSIS_CACHE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@monitor_bp.route("/analyze-child-fresh", methods=["POST"])
def analyze_child_fresh():

    if not session.get("monitor_active"):
        return jsonify({"error": "Unauthorized"}), 401

    sessions = []

    if os.path.exists(HISTORY_PATH):

        for file in os.listdir(HISTORY_PATH):

            if not file.endswith(".json"):
                continue

            path = os.path.join(HISTORY_PATH, file)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    sessions.append(json.load(f))

            except Exception as e:
                print(f"[Monitor] Error reading {file}: {e}")

    if not sessions:
        return jsonify({"error": "No session data found"}), 400

    try:
        result = _ai.analyze_child(sessions)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    result["generated_at"] = datetime.now().strftime("%d %b %Y, %H:%M")

    os.makedirs(os.path.dirname(ANALYSIS_CACHE), exist_ok=True)

    try:
        with open(ANALYSIS_CACHE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"[Monitor] Could not save analysis: {e}")

    return jsonify(result)