"""Довідник назв локацій для перекладу розкладу.

CourseInstance.location -- вільний текст ("Харків", "Київ"), який показується
на публічних сторінках. Робити його перекладним ПОЛЕМ проведення було б
марнотратно: міста повторюються десятками проведень, а нові проведення
створюються постійно -- перекладач щоразу вписував би "Харків" наново.

Тому переклад живе в довіднику: назва перекладається один раз і
застосовується скрізь, де ця сама назва зустрічається (звірка -- за повним
нормалізованим рядком, див. app.services.city_glossary).
"""
from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin, TranslatableMixin


def normalize_city_name(text):
    """Форма для звірки: без крайніх пробілів, у нижньому регістрі,
    внутрішні пробіли стиснуті."""
    return ' '.join((text or '').split()).lower()


class City(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'cities'
    __translatable__ = ('name',)

    id = db.Column(BigIntPK, primary_key=True)

    # Канонічна українська назва -- рівно те, що вписують у location проведення.
    name = db.Column(db.String(255), unique=True, nullable=False)

    # Нормалізована форма для пошуку (lower + стиснуті пробіли). Зберігаємо
    # колонкою, а не рахуємо в SQL, щоб пошук ішов по індексу.
    name_normalized = db.Column(db.String(255), unique=True, nullable=False, index=True)

    @validates('name')
    def _sync_normalized(self, _key, value):
        """Тримати name_normalized узгодженим з name на рівні моделі --
        інакше воно розійдеться в котромусь із шляхів запису (адмінка,
        xlsx-імпорт, seed)."""
        self.name_normalized = normalize_city_name(value)
        return value

    def __repr__(self):
        return f'<City {self.name}>'
