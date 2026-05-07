import os

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask import Flask

from web_interface import control
import config

db = SQLAlchemy()
DB_NAME = "database.db"


def create_app():
    app = Flask(__name__)
    app.config.from_pyfile(os.path.join(os.path.dirname(__file__), '..', 'config.py'))
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + DB_NAME
    db.init_app(app)


    from web_interface.auth import auth
    from web_interface.view import view
    from web_interface.pdf import pdf
    from web_interface.control import control
    from web_interface.monitor import monitor_bp
    # from web_interface.history import history_bp
    # from web_interface.settings import settings

    app.register_blueprint(monitor_bp, url_prefix="/")
    # app.register_blueprint(history_bp,url_prefix="/")
    app.register_blueprint(auth, url_prefix='/auth')
    app.register_blueprint(view, url_prefix='/')
    app.register_blueprint(pdf, url_prefix='/pdf')
    app.register_blueprint(control, url_prefix='/control')
    # app.register_blueprint(settings, url_prefix='/settings')

    create_database(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)
    login_manager.login_message_category = "info"

    from web_interface.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    return app




def create_database(app):
    if not os.path.exists(f"web_interface/{DB_NAME}"):
        with app.app_context():
            db.create_all()
