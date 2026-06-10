"""Віддача медіа-файлів з MEDIA_FOLDER (поза app/static).

На проді цей шлях перехоплює nginx-alias (швидше); цей роут -- для dev та
як fallback. send_from_directory захищає від обходу каталогів. Публічно
(медіа блогу/тренерів/курсів). Кешування -- довге й immutable (імена з uuid).
"""
from flask import current_app, send_from_directory

from app.media import media_bp


@media_bp.route('/media/<path:filename>')
def serve(filename):
    resp = send_from_directory(current_app.config['MEDIA_FOLDER'], filename)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp
