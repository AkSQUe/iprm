"""Довідник спеціальностей для рядка «Спеціальності:» на сертифікаті.

Курс і проведення посилаються сюди списком КОДІВ (bpr_specialty_codes), а не
FK: код стабільний, читається в дампі й переживає перезаливку довідника.

Рядок, який десь уже вжито, не видаляють, а деактивують (is_active=False):
у виборі він зникає, а там, де вже проставлений, рендериться далі. Так
актуалізація номенклатури не лишає курси з осиротілим кодом.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin, TranslatableMixin

# Розділи I-IV Додатка 1. Підпис -- шапка групи у виборі спеціальностей.
SECTIONS = (
    ('medical', 'Лікарські'),
    ('pharmacy', 'Фармацевтичні'),
    ('professionals', 'Професіоналів'),
    ('specialists', 'Фахівців'),
)
SECTION_LABELS = dict(SECTIONS)


class Specialty(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'specialties'
    __translatable__ = ('name',)

    id = db.Column(BigIntPK, primary_key=True)

    # Латинський slug української назви, згенерований один раз і заморожений.
    code = db.Column(db.String(60), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    section = db.Column(db.String(20), nullable=False, index=True)

    # Службове узагальнення ("усі лікарські спеціальності") -- рядок довідника,
    # а не окремий стан поля: обирається й друкується як будь-який інший.
    is_group = db.Column(db.Boolean, nullable=False, default=False)

    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def section_label(self):
        return SECTION_LABELS.get(self.section, self.section)

    def __repr__(self):
        return f'<Specialty {self.code}>'
