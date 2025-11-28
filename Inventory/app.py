from flask import Flask
from datetime import datetime, timedelta  # <-- Add timedelta import

# Import the blueprints
from routes import main_bp
from api import api_bp
from auth import auth_bp
import os

# --- 1. DEFINE THE FORMATTING FUNCTION ---
def format_date_alphanumeric(date_string):
    """Custom Jinja2 filter to format date from YYYY-MM-DD to 'DD Month, YYYY'."""
    if not date_string:
        return ""  # Return an empty string if the date is None
    try:
        # Parse the date string from the database ('2025-09-09')
        date_obj = datetime.strptime(date_string, '%Y-%m-%d')
        # Format it into the desired display format ('09 September, 2025')
        return date_obj.strftime('%d %B, %Y')
    except (ValueError, TypeError):
        # In case of an error, just return the original string
        return date_string

def todatetime(date_string, fmt='%Y-%m-%d'):
    """Convert a date string to a datetime object."""
    if not date_string:
        return None
    try:
        return datetime.strptime(date_string, fmt)
    except (ValueError, TypeError):
        return None

def add_days(date_obj, days):
    """Add days to a datetime object."""
    if not date_obj:
        return ""
    try:
        return date_obj + timedelta(days=days)
    except Exception:
        return date_obj

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'a_very_secret_and_random_string_for_production'

    # Register custom filters
    app.jinja_env.filters['dateformat'] = format_date_alphanumeric
    app.jinja_env.filters['todatetime'] = todatetime
    app.jinja_env.filters['add_days'] = add_days  # <-- Register the new filter

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Register blueprints
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)

