"""Колонка professional_certificates у trainer_profiles.

Професійні сертифікати для резюме до реєстру БПР. Текст, один рядок = один
сертифікат. Необовʼязкове: в REQUIRED_FOR_COMPLETE не входить, тож наявні
анкети не стають неповними.

Revision ID: trainer_prof_certs_20260922
Revises: mat_request_20260922

down_revision зафіксовано на фактичну голову (`flask db heads`) на момент
застосування, а не на голову з брифу (lect_cert_emailed_20260922): у тому ж
дереві паралельна сесія вже накотила mat_request_20260922 поверх неї до
того, як застосовувалась ця міграція. Лінійний ланцюг замість двох голів.
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_prof_certs_20260922'
down_revision = 'mat_request_20260922'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('professional_certificates', sa.Text()))


def downgrade():
    with op.batch_alter_table('trainer_profiles', schema=None) as batch_op:
        batch_op.drop_column('professional_certificates')
