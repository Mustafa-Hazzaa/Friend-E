from flask import Blueprint, request, flash, render_template, url_for, redirect
from web_interface import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import *

from web_interface.models import User

auth = Blueprint('auth', __name__)

@auth.route("/signUp" ,methods=["GET","POST"])
def signUp():
    error = None
    if request.method == "POST":
        data = request.form
        username = request.form["username"]
        email = data["email"]
        password = data["password"]
        confirm_password = data["confirm_password"]
        user = User.query.filter_by(email = email).first()
        if user:
            error = "user  already exists"
        elif password != confirm_password:
            error = "Passwords do not match"
        else:
            new_user = User(username = username, email = email, password_hash = generate_password_hash(password))
            db.session.add(new_user)
            db.session.commit()
            flash("account created!!",category="success")
            login_user(new_user, remember=True)
            return redirect(url_for("view.dashboard"))
    return render_template("signUp.html",error = error,user = current_user)

@auth.route("/login",methods=["GET","POST"])
def login():
    error = None
    if request.method == "POST":
        data = request.form
        email = data["email"]
        password = data["password"]
        user = User.query.filter_by(email = email).first()
        if user and check_password_hash(user.password_hash,password):
             flash("Login Successful!!",category="success")
             login_user(user,remember=True)
             next_page = request.args.get("next")
             return redirect(next_page) if next_page else redirect(url_for("view.dashboard"))
        else:
            error = "email or password is incorrect"

    return render_template("login.html", error=error , user = current_user)

@auth.route("/forgotPassword",methods=["GET","POST"])
def forgotPassword():
    email = request.form
    return render_template("forgotPassword.html")

@auth.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))

@auth.route("/account")
@login_required
def account():
    image_file = url_for('static', filename='profile_pics/default.jpg')
    return render_template("account.html", user=current_user)

@auth.route("/account/update", methods=["POST"])
@login_required
def update_account():
    user = current_user

    username = request.form.get("username")
    if username:
        user.username = username


    try:
        db.session.commit()
        flash("Profile updated!", "success")
    except:
        db.session.rollback()
        flash("Error updating profile", "error")

    return redirect(url_for("auth.account"))

import os
from werkzeug.utils import secure_filename      


@auth.route("/account/avatar", methods=["POST"])
@login_required
def upload_avatar():
    user = current_user

    if "avatar" not in request.files:
        return {"error": "No file"}, 400

    file = request.files["avatar"]
    if file.filename == "":
        return {"error": "Empty file"}, 400

    filename = secure_filename(file.filename)

    upload_path = os.path.join( "web_interface","static","profile_pics",f"{user.id}_{filename}")
    file.save(upload_path)

    user.avatar = f"profile_pics/{user.id}_{filename}"
    db.session.commit()

    return {"success": True}