from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash
from db import get_db_connection

# Create a Blueprint for authentication routes
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db_connection()
        error = None
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user is None or not check_password_hash(user['password'], password):
            error = 'Incorrect username or password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role'].lower()   # 🔑 FIX: store role in session
            return redirect(url_for('main.stock'))

        flash(error, 'danger')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('auth.login'))