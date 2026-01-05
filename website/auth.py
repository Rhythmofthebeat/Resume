from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user
from supabase import create_client

# ---------------- Supabase Client ---------------- #

supabase = create_client(
    "https://rfkgkjlfylhtzxevpphs.supabase.co",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJma2dramxmeWxodHp4ZXZwcGhzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5Mzk3NjEsImV4cCI6MjA3OTUxNTc2MX0.d5kmukDMp2YJZVf_A3T1eBbXDUv_HMu1nDMk4md9vpU"
)

auth = Blueprint('auth', __name__)

# ------------------------------------------------ #
# ---------------- PASSWORD RESET ---------------- #
# ------------------------------------------------ #

@auth.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")

        supabase.auth.reset_password_for_email(
            email,
            {"redirect_to": request.host_url.rstrip("/") + "/reset-password"}
        )

        flash("Password reset email sent!", "success")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")



@auth.route("/reset-password", methods=["GET"])
def reset_password():
    # Supabase redirects here from email
    return """
<script>
const hash = window.location.hash.substring(1);
const params = new URLSearchParams(hash);

const access_token = params.get("access_token");
const refresh_token = params.get("refresh_token");

if (!access_token || !refresh_token) {
  alert("Invalid or expired reset link.");
  window.location = "/login";
} else {
  fetch("/reset-password/store", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({ access_token, refresh_token })
  }).then(() => {
    window.location = "/reset-password/form";
  });
}
</script>

"""


@auth.route("/reset-password/store", methods=["POST"])
def store_reset_token():
    data = request.get_json()
    session["supabase_access_token"] = data.get("access_token")
    session["supabase_refresh_token"] = data.get("refresh_token")
    return {"status": "ok"}


from supabase import create_client

@auth.route("/reset-password/form", methods=["GET", "POST"])
def reset_password_form():
    if request.method == "POST":
        new_password = request.form.get("password")
        access_token = session.get("supabase_access_token")
        refresh_token = session.get("supabase_refresh_token")

        if not access_token:
            flash("Reset session expired. Try again.", "error")
            return redirect(url_for("auth.login"))

        if len(new_password) < 7:
            flash("Password must be at least 7 characters.", "error")
            return redirect(request.url)

        try:
          
            authed_supabase = create_client(
                "https://rfkgkjlfylhtzxevpphs.supabase.co",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJma2dramxmeWxodHp4ZXZwcGhzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5Mzk3NjEsImV4cCI6MjA3OTUxNTc2MX0.d5kmukDMp2YJZVf_A3T1eBbXDUv_HMu1nDMk4md9vpU"
            )
            authed_supabase.auth.set_session(
                access_token,
                refresh_token
            )
            

            authed_supabase.auth.update_user({
                "password": new_password
            })

        except Exception as e:
            print("Password update error:", e)
            flash("Error updating password.", "error")
            return redirect(request.url)

        session.pop("supabase_access_token", None)
        flash("Password updated successfully!", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password_form.html")


# ------------------------------------------------ #
# ---------------- EMAIL LOGIN ------------------- #
# ------------------------------------------------ #

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user, remember=True)
            flash('Logged in successfully', 'success')
            return redirect(url_for('views.home'))

        flash('Invalid email or password.', 'error')

    return render_template("login.html")


@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))

    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('firstName')
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')

        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
        elif password1 != password2:
            flash('Passwords do not match.', 'error')
        elif len(password1) < 7:
            flash('Password must be at least 7 characters.', 'error')
        else:
            new_user = User(
                email=email,
                first_name=first_name,
                password=generate_password_hash(password1)
            )
            db.session.add(new_user)
            db.session.commit()

            login_user(new_user, remember=True)
            flash('Account created!', 'success')
            return redirect(url_for('views.home'))

    return render_template("sign_up.html")

# ------------------------------------------------ #
# ---------------- GOOGLE OAUTH ------------------ #
# ------------------------------------------------ #

@auth.route('/login/google')
def login_google():
    redirect_url = request.host_url.rstrip("/") + "/auth/callback"

    response = supabase.auth.sign_in_with_oauth(
        provider="google",
        options={"redirect_to": redirect_url}
    )

    return redirect(response.url)


@auth.route("/auth/callback")
def auth_callback():
    return """
<script>
const params = new URLSearchParams(window.location.hash.substring(1));
fetch("/auth/store-session", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    access_token: params.get("access_token"),
    refresh_token: params.get("refresh_token")
  })
}).then(() => window.location = "/login/google/finish");
</script>
"""


@auth.route("/auth/store-session", methods=["POST"])
def store_session():
    data = request.get_json()
    session["access_token"] = data["access_token"]
    session["refresh_token"] = data["refresh_token"]
    return {"status": "ok"}


@auth.route("/login/google/finish")
def login_google_finish():
    access_token = session.get("access_token")

    if not access_token:
        flash("Google login failed.", "error")
        return redirect(url_for("auth.login"))

    supabase.auth.set_session(access_token, session.get("refresh_token"))
    result = supabase.auth.get_user()

    email = result.user.email
    name = result.user.user_metadata.get("full_name", "Google User")

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email,
            first_name=name,
            password=generate_password_hash("google-login")
        )
        db.session.add(user)
        db.session.commit()

    login_user(user, remember=True)
    flash("Logged in with Google!", "success")
    return redirect(url_for('views.home'))

@auth.route('/resume-summarizer')
def resume():
    return render_template('resumesum.html')


@auth.route('/resume-jobmatch')
def resumejob():
    return render_template('resumemat.html')
