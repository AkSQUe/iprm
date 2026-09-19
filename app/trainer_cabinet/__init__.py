from app.i18n import LocalizedBlueprint

trainer_cabinet_bp = LocalizedBlueprint('trainer_cabinet', __name__, url_prefix='/trainer')


@trainer_cabinet_bp.after_request
def add_noindex_header(response):
    # Кабінет тренера -- приватний, у пошуковий індекс не має потрапляти.
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


from app.trainer_cabinet import routes  # noqa: F401,E402
