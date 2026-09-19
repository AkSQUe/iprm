"""Симетричне шифрування секретів у БД (Fernet, ключ з SECRET_KEY).

Одне місце на весь проєкт: доти ключ виводився двома однаковими копіями
(`site_settings._get_fernet`, `email_settings._get_fernet`), і третя копія
для анкети тренера дублювала б їх утретє. Зміна SECRET_KEY робить усі
збережені шифротексти нечитабельними -- decrypt_str тоді повертає '' і пише
warning, а не валить сторінку.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

logger = logging.getLogger(__name__)


def get_fernet():
    secret = current_app.config['SECRET_KEY']
    key = hashlib.sha256(secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_str(value):
    """Шифротекст рядка; порожнє значення -> ''."""
    if not value:
        return ''
    return get_fernet().encrypt(value.encode()).decode()


def decrypt_str(token, label='value'):
    """Відкритий текст; порожній або битий токен -> ''."""
    if not token:
        return ''
    try:
        return get_fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        logger.warning('Failed to decrypt %s', label)
        return ''


def encrypted_field(column_attr):
    """Властивість, що шифрує при записі в `column_attr` і розшифровує при читанні.

    Значення обрізається від пробілів; порожнє зберігається як '' (без
    шифротексту), щоб «не заповнено» відрізнялось без decrypt.
    """
    def fget(self):
        return decrypt_str(getattr(self, column_attr), column_attr)

    def fset(self, value):
        value = (value or '').strip()
        setattr(self, column_attr, encrypt_str(value))

    return property(fget, fset)
