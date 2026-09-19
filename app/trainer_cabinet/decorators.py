from functools import wraps

from flask import abort, g
from flask_login import current_user, login_required


def trainer_required(view):
    """Анонім -> вхід; користувач без активної картки тренера або з
    непідтвердженим email -> 404.

    404, а не 403: сторонньому не треба знати, що кабінет існує. Картка
    кладеться в g.trainer. Непідтверджений email перевіряється тут, а не в
    User.active_trainer: прив'язка могла статися до того, як адмінка почала
    її відхиляти, і такий акаунт не має бачити анкету з реквізитами.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        trainer = current_user.active_trainer
        if trainer is None or not current_user.email_confirmed:
            abort(404)
        g.trainer = trainer
        return view(*args, **kwargs)
    return login_required(wrapped)
