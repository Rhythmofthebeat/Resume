from flask import Blueprint, render_template
from flask_login import login_required, current_user

views = Blueprint('views', __name__)

@views.route('/')
@login_required
def home():
    return render_template("home.html", user=current_user)

@views.route('/resume-summarizer')
@login_required
def resume_summarizer():
    return render_template('resumesum.html', user=current_user)

@views.route('/resume-jobmatch')
@login_required
def resume_jobmatch():
    return render_template('resumemat.html', user=current_user)
