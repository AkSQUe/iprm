from datetime import datetime, timezone

from app.extensions import db
from app.i18n import DEFAULT_LANGUAGE, PREFIXED_LANGUAGES, apply_json_overrides


def utcnow():
    return datetime.now(timezone.utc)


# BigInteger для PostgreSQL, Integer для SQLite (autoincrement)
BigIntPK = db.BigInteger().with_variant(db.Integer, 'sqlite')


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow)


def _current_language():
    try:
        from flask_babel import get_locale
        return str(get_locale() or DEFAULT_LANGUAGE)
    except Exception:
        # Поза app-контекстом (скрипти, частина фонових задач) -- дефолт.
        return DEFAULT_LANGUAGE


class TranslatableMixin:
    """Переклади контентних полів моделі (ru/en; українська -- канонічні
    колонки, тому окремого бакета "uk" немає).

    translations -- JSON {"ru": {<поле>: <значення>, ...}, "en": {...}}.
    Рядкові поля зберігають переклад рядком; JSON-поля (faq, регалії, блоки
    блогу) -- як ПЛОСКУ мапу overrides {шлях: текст}, що накладається на
    поточну українську структуру при читанні (app.i18n.apply_json_overrides).
    Перелік перекладних полів модель оголошує у __translatable__.

    Читання: obj.t('title') -- значення активної локалі з фолбеком на
    українську (відсутні/порожні переклади не показують діри в UI; для
    JSON-полів зміни оригіналу підхоплюються автоматично, застарілі
    переклади-шляхи ігноруються).
    Запис: set_translation(...) -- присвоює НОВИЙ dict, щоб SQLAlchemy
    зафіксував зміну JSON-колонки без MutableDict.
    """
    __translatable__ = ()

    translations = db.Column(db.JSON)

    def t(self, field, lang=None):
        if lang is None:
            lang = _current_language()
        uk_value = getattr(self, field)
        if lang == DEFAULT_LANGUAGE or field not in self.__translatable__:
            return uk_value
        stored = ((self.translations or {}).get(lang) or {}).get(field)
        if stored in (None, '', [], {}):
            return uk_value
        # JSON-структура -> overrides {шлях: текст}; рядок -> прямий переклад.
        if isinstance(uk_value, (list, dict)):
            return apply_json_overrides(uk_value, stored)
        return stored

    def set_translation(self, lang, field, value):
        if lang not in PREFIXED_LANGUAGES:
            raise ValueError(f'lang має бути одною з {PREFIXED_LANGUAGES}')
        if field not in self.__translatable__:
            raise ValueError(
                f'{field} не входить у __translatable__ {type(self).__name__}'
            )
        data = {k: dict(v or {}) for k, v in (self.translations or {}).items()}
        bucket = data.setdefault(lang, {})
        if value in (None, '', [], {}):
            bucket.pop(field, None)
        else:
            bucket[field] = value
        self.translations = data
