from flask import render_template

from app.main import main_bp


@main_bp.route('/')
def index():
    return render_template('main/index.html', active_nav='labs')


@main_bp.route('/design-system')
def design_system():
    return render_template('design_system/index.html')
