from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from os import path
from flask_login import LoginManager

db = SQLAlchemy()
DB_NAME = "database.db"   

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'ebsjkfbsdjkfbjkdfb'
    #sqlite is stored at this location 
    app.config['SQLALCHEMY_DATABASE_URI'] =f'sqlite:///{DB_NAME}'
    db.init_app(app) # we are going to use this app

    import os
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    audio_path = os.path.join(BASE_DIR, "..", "audio")
    upload_path = os.path.join(BASE_DIR, "..", "uploads")

    app.config["AUDIO_FOLDER"] = os.path.join(os.path.dirname(__file__), "audio")
    app.config["AUDIO_FOLDER"] = audio_path

    app.config["AUDIO_FOLDER"] = os.path.join(os.path.dirname(__file__), "uploads")
    app.config["UPLOAD_FOLDER"] = upload_path

    
    os.makedirs(upload_path, exist_ok=True)

    from .models import User, Resume

    with app.app_context():       #Sets up the app context
            db.create_all()    

    from .views import views
    from .auth import auth
    
    app.register_blueprint(views, url_prefix = '/')
    app.register_blueprint(auth, url_prefix = '/')


    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    return app

#function checks if the database exists
def create_database(app):
    if not path.exists('website/' + DB_NAME):      
        print('Created Database!')

