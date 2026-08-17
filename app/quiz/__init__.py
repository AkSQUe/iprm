from app.i18n import LocalizedBlueprint

quiz_bp = LocalizedBlueprint('quiz', __name__, url_prefix='/quiz')


@quiz_bp.after_request
def add_noindex_header(response):
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.quiz import routes  # noqa: F401,E402
