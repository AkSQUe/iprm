"""Звести дві гілки міграцій: прив'язка форми до заходу й індекси подій.

Порожня ревізія-злиття, без власних дій. Дві роботи йшли паралельно і
зачепились за ту саму батьківську ревізію `meta_form_schema_20260830`:
одна додала `meta_lead_forms.course_instance_id`, друга -- індекси на
`meta_lead_events`. Кожна сама по собі коректна, але разом вони дають дві
голови, і `flask db upgrade` на цьому падає.

Alembic не вміє обрати між гілками сам, тому злиття -- обов'язковий крок,
а не косметика: без цієї ревізії прод просто не оновиться.

Revision ID: 9fad58660b0d
Revises: meta_form_offer_20260831, meta_lead_events_idx_20260830
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9fad58660b0d'
down_revision = ('meta_form_offer_20260831', 'meta_lead_events_idx_20260830')
branch_labels = None
depends_on = None


def upgrade():
    # Злиття гілок -- схему не змінює.
    pass


def downgrade():
    # Розділення назад на дві голови -- теж без дій над схемою.
    pass
