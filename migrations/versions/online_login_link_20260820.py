"""Персональне посилання на встановлення пароля в Sintegrum.

API партнера не вміє ані видати пароль новому учню, ані надіслати йому
запрошення -- такого ендпоінта немає в специфікації взагалі. Посилання
виду `https://sntgr.me/<код>` генерується руками в кабінеті Sintegrum під
конкретного учня. Отже єдиний ручний крок у ланцюжку -- перенести це
посилання до нас, а надіслати його покупцю система вже може сама.

Revision ID: online_login_20260820
Revises: material_kits_20260820
"""
import sqlalchemy as sa
from alembic import op

revision = 'online_login_20260820'
down_revision = 'material_kits_20260820'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.add_column(sa.Column('login_link', sa.String(500), nullable=True))
        batch.add_column(
            sa.Column('login_link_sent_at', sa.DateTime(timezone=True),
                      nullable=True))


def downgrade():
    with op.batch_alter_table('online_enrollments') as batch:
        batch.drop_column('login_link_sent_at')
        batch.drop_column('login_link')
