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
            admin_supabase = create_client(
                "https://rfkgkjlfylhtzxevpphs.supabase.co",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJma2dramxmeWxodHp4ZXZwcGhzIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MzkzOTc2MSwiZXhwIjoyMDc5NTE1NzYxfQ.vimC-dSL2XQGBpv7qfYquADY9sU2d4nuZOh6m-sAYRQ"
            )
          
            authed_supabase = create_client(
                "https://rfkgkjlfylhtzxevpphs.supabase.co",
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJma2dramxmeWxodHp4ZXZwcGhzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjM5Mzk3NjEsImV4cCI6MjA3OTUxNTc2MX0.d5kmukDMp2YJZVf_A3T1eBbXDUv_HMu1nDMk4md9vpU"
            )
            authed_supabase.auth.set_session(
                access_token,
                refresh_token
            )
            
            
              # Get Supabase user
            user_response = authed_supabase.auth.get_user(access_token)
            supa_user = user_response.user
            email = supa_user.email

            # Get local user
            user = User.query.filter_by(email=email).first()

            if user:
                # Block reusing old password
                if check_password_hash(user.password, new_password):
                    flash("You cannot use your old password.", "error")
                    return redirect(request.url)

            admin_supabase.auth.admin.update_user_by_id(
                supa_user.id,
                {"password": new_password}
            )

        except Exception as e:
            print("Password update error:", e)
            flash("Error updating password.", "error")
            return redirect(request.url)

        session.pop("supabase_access_token", None)
        flash("Password updated successfully!", "success")
        return redirect(url_for("auth.login"))

    return render_template("reset_password_form.html")





    # Check if user exists locally
from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from . import db
from flask_login import login_user, login_required, logout_user, current_user
from supabase import create_client



# ------------------------------------------------ #
# ---------------- EMAIL LOGIN ------------------- #
# ------------------------------------------------ #

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            res = supabase.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
        except Exception as e:
            print("Supabase login error:", e)
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if not hasattr(res, 'user') or not res.user:
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        # Ensure local user exists for Flask-Login
        local_user = User.query.filter_by(email=email).first()
        if not local_user:
            local_user = User(
                email=email,
                first_name=res.user.user_metadata.get("full_name", ""),
                password=None
            )
            db.session.add(local_user)
            db.session.commit()

        login_user(local_user, remember=True)
        flash("Logged in successfully!", "success")
        return redirect(url_for('views.home'))

    return render_template("login.html")

@auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

# ---------------- SIGN-UP ----------------
@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if current_user.is_authenticated:
        return redirect(url_for('views.home'))

    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('firstName')
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')

        if not email:
            flash("Email is required.", "error")
        elif password1 != password2:
            flash("Passwords do not match.", "error")
        elif len(password1) < 7:
            flash("Password must be at least 7 characters.", "error")
        else:
            try:
                # Attempt signup
                res = supabase.auth.sign_up({
                    "email": email,
                    "password": password1,
                    "options": {"data": {"full_name": first_name}}
                })

                if res.user:
                    # Signup successful
                    flash("Account created successfully!", "success")
                    supa_user = res.user
                else:
                    # If no user returned, fallback to generic error
                    flash("Something went wrong. Try again.", "error")
                    return redirect(url_for("auth.sign_up"))

                # Ensure local Flask-Login user exists
                local_user = User.query.filter_by(email=email).first()
                if not local_user:
                    local_user = User(
                        email=email,
                        first_name=supa_user.user_metadata.get("full_name", first_name),
                        password=None
                    )
                    db.session.add(local_user)
                    db.session.commit()

                # Log in the user
                login_user(local_user, remember=True)
                return redirect(url_for('views.home'))

            except Exception as e:
                # Detect "already registered" from Supabase
                if "already registered" in str(e):
                    flash("Email already exists. Try logging in instead.", "error")
                    return redirect(url_for("auth.login"))

                # Other unexpected errors
                print("Signup/login unexpected error:", e)
                flash("Something went wrong. Try again.", "error")
                return redirect(url_for("auth.sign_up"))

    return render_template("sign_up.html")

# ------------------------------------------------ #
# ---------------- GOOGLE OAUTH ------------------ #
# ------------------------------------------------ #


@auth.route('/login/google')
def login_google():
    # Redirect user to Supabase Google OAuth
    res = supabase.auth.sign_in_with_oauth({
        "provider": "google",
        "options": {
            # This must match your route that serves the JS
            "redirect_to": request.host_url.rstrip("/") + "/login/google/finish"
        }
    })
    return redirect(res.url)


@auth.route("/login/google/finish")
def login_google_finish():
    code = request.args.get("code")

    if not code:
        flash("Google login failed.", "error")
        return redirect(url_for("auth.login"))

    try:
        # Exchange code for session
        res = supabase.auth.exchange_code_for_session({"auth_code": code})

        supa_user = res.user

        if not supa_user:
            flash("Google login failed.", "error")
            return redirect(url_for("auth.login"))

        email = supa_user.email
        name = supa_user.user_metadata.get("full_name", "Google User")

        local_user = User.query.filter_by(email=email).first()

        if not local_user:
            local_user = User(
                email=email,
                first_name=name,
                password=None
            )
            db.session.add(local_user)
            db.session.commit()

        login_user(local_user, remember=True)

        return redirect(url_for("views.home"))

    except Exception as e:
        print("Google OAuth error:", e)
        flash("Google login failed.", "error")
        return redirect(url_for("auth.login"))
