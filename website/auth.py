from flask import Blueprint, render_template, request, flash, redirect, url_for
from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))
    
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = (request.form.get('password') or '').strip()


        user = User.query.filter_by(email=email).first()
        if user:
            if check_password_hash(user.password, password):
                flash('Logged in successfully.', category= 'success')
                login_user(user, remember = True)
                return redirect(url_for('views.home'))
            else:
                flash ('Incorrect password, try again.', category='error')
        else: 
            flash('Email does not exist.', category= 'error')
    return render_template("login.html", user = current_user)

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    # If the user is already logged in, redirect them to the home page
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))  # or wherever you want to send logged-in users

    if request.method == 'POST':
      
        email = (request.form.get('email') or '').strip().lower()
        first_name = (request.form.get('firstName') or '').strip()
        password1 = (request.form.get('password1') or '').strip()
        password2 = (request.form.get('password2') or '').strip()

        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists.', category='error')
        elif len(email) < 4:
            flash('Email must be greater than 3 characters.', category='error')
        # You can uncomment this to enforce a company email
        # elif not email.lower().endswith('@kr3infosys.com'):
        #     flash('Email must be a KR3 email.', category='error')
        elif len(first_name) < 2:
            flash('First name must be greater than 1 character.', category='error')
        elif password1 != password2:
            flash('Passwords don\'t match', category='error')
        elif len(password1) < 7:
            flash('Password must be greater than 6 characters.', category='error')
        else:
            
            new_user = User(
                email=email,
                first_name=first_name,
                password=generate_password_hash(password1, method='pbkdf2:sha256')
            )
            db.session.add(new_user)
            db.session.commit()

            
            login_user(new_user, remember=True)

            flash('Account created!', category='success')
            return redirect(url_for('views.home'))


    return render_template("sign_up.html", user=current_user)


