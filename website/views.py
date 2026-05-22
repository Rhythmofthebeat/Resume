from flask import Blueprint, render_template
from flask_login import login_required, current_user


views = Blueprint('views', __name__)

# Moved from '/' to '/home' to avoid conflicting with the app-level index() route at '/'.
# auth.py redirects to url_for('views.home') after login — this now resolves to /home.
@views.route('/home')
@login_required
def home():
    return render_template("home.html", user=current_user)
