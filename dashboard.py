# dashboard.py made from GPT
from flask import render_template

def register_dashboard_routes(app):
    @app.route("/")
    def index():
        return render_template("dashboard.html")
