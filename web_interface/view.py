from flask import Blueprint, render_template, url_for, redirect, request, jsonify, current_app,session
from flask_login import login_required, current_user, login_manager
from werkzeug.security import check_password_hash
view = Blueprint('view', __name__)
   # or however you store it

@view.route("/dashboard")
@login_required
def dashboard():
    PI_IP = current_app.config["PI_IP"]
    return render_template("control.html", active_page="dashboard",user=current_user,pi_stream=f"http://{PI_IP}:8080/stream.mjpg")

@view.route("/health")
def good():
    return "good"

@view.route("/")
@view.route("/home")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("view.dashboard"))

    return render_template("home.html", user=current_user)

@view.route("/about")
def about():
    return render_template('about.html')

@view.route("/pdf")
@login_required
def pdf_page():
    return render_template("pdf.html", active_page="pdf",user=current_user)

@view.route("/Games")
def Games():
    return render_template("Games.html", active_page="Games",user=current_user)

@view.route("/settings")
@login_required
def settings():
    return render_template("settings.html", active_page="settings",user=current_user)
@view.route("/programming")
@login_required
def programming():
    return render_template("programming.html", active_page="programming",user=current_user)

@view.route("/account")
@login_required
def account():
    return render_template("account.html", active_page="account",user=current_user)

@view.route("/monitor")
def monitor():
    return render_template("monitor.html", active_page="monitor", user=current_user, parent_active=session.get('parent_active', False))

@view.route("/check-monitor-password", methods=["POST"])
@login_required
def check_monitor_password():
    data = request.get_json()
    password = data.get("password", "")

    if check_password_hash(current_user.password_hash, password):
        session['parent_active'] = True
        return jsonify(success=True)

    return jsonify(success=False)