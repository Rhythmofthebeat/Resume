# from dot is the same as from website since it imports from the current package
from . import db
from flask_login import UserMixin
from sqlalchemy.sql import func

class Resume(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    #data = db.Column(db.String(1000))
    #date = db.Column(db.Datetime(timezone=True), default = func.now())
    # Must pass a valid user id in order to go to next screen
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True) 
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(150))
    first_name = db.Column(db.String(150))
    #resume



    #You would add here what additional models you want to add like Reminders etc.