
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

from config import Config  # uses env vars, no load_dotenv here

db = SQLAlchemy()
DB_NAME = "database.db"


def create_app():
    app = Flask(__name__)

    # Secrets (centralized)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "ebsjkfbsdjkfbjkdfb")

    # SQLite DB (store in project root by default)
    # Using absolute path prevents "where did my DB go?" issues
    base_dir = os.path.abspath(os.path.dirname(__file__))
    db_path = os.path.join(base_dir, DB_NAME)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
  
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Folders (single source of truth)
    audio_path = os.path.join(base_dir, "audio")
    upload_path = os.path.join(base_dir, "uploads")
    app.config["AUDIO_FOLDER"] = audio_path
    app.config["UPLOAD_FOLDER"] = upload_path
    os.makedirs(audio_path, exist_ok=True)
    os.makedirs(upload_path, exist_ok=True)

    # Init extensions
    db.init_app(app)

    # Models
    from .models import User, Resume  # noqa: F401

    with app.app_context():
        db.create_all()

    # Blueprints
    from .views import views
    from .auth import auth
    app.register_blueprint(views, url_prefix="/")
    app.register_blueprint(auth, url_prefix="/")

    # Login manager
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    return app
