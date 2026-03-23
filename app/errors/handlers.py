from flask import render_template

from app.errors import errors_bp


@errors_bp.app_errorhandler(401)
def unauthorized(error):
    return render_template('errors/401.html', active_nav=None), 401


@errors_bp.app_errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html', active_nav=None), 403


@errors_bp.app_errorhandler(404)
def page_not_found(error):
    return render_template('errors/404.html', active_nav=None), 404


@errors_bp.app_errorhandler(500)
def internal_server_error(error):
    return render_template('errors/500.html', active_nav=None), 500
