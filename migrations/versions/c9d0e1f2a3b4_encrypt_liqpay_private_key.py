"""Encrypt liqpay_private_key in-place (Fernet)

Усі інші секрети у SiteSettings -- recaptcha, apple .p8, google_oauth_secret,
partner_* -- зберігаються Fernet-encrypted. LiqPay private key історично
залишався plaintext (db.String(255)) -- це security-bug: у БД-бекапі/дампі
секрет з доступом до коштів видно у відкритому вигляді.

upgrade():
  1) Розширюємо колонку до String(500), щоб Fernet-ciphertext поміщався.
  2) Шифруємо існуюче значення через _get_fernet() (тим самим SECRET_KEY,
     що й інші секрети).
  3) Idempotency: якщо значення вже схоже на Fernet-ciphertext ('gAAAAA...'),
     не шифруємо повторно.

downgrade(): розшифровуємо назад + звужуємо до String(255).

Revision ID: c9d0e1f2a3b4
Revises: b6c7d8e9f0a1
Create Date: 2026-05-29 11:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d0e1f2a3b4'
down_revision = 'b6c7d8e9f0a1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'liqpay_private_key',
            existing_type=sa.String(length=255),
            type_=sa.String(length=500),
            existing_nullable=True,
        )

    from app.models.site_settings import _get_fernet
    fernet = _get_fernet()

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, liqpay_private_key FROM site_settings "
        "WHERE liqpay_private_key IS NOT NULL AND liqpay_private_key <> ''"
    )).fetchall()
    for row_id, value in rows:
        if value.startswith('gAAAA'):
            continue
        encrypted = fernet.encrypt(value.encode()).decode()
        conn.execute(
            sa.text("UPDATE site_settings SET liqpay_private_key = :val "
                    "WHERE id = :id"),
            {'val': encrypted, 'id': row_id},
        )


def downgrade():
    from app.models.site_settings import _get_fernet
    from cryptography.fernet import InvalidToken
    fernet = _get_fernet()

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, liqpay_private_key FROM site_settings "
        "WHERE liqpay_private_key IS NOT NULL AND liqpay_private_key <> ''"
    )).fetchall()
    for row_id, value in rows:
        if not value.startswith('gAAAA'):
            continue
        try:
            plaintext = fernet.decrypt(value.encode()).decode()
        except InvalidToken:
            continue
        conn.execute(
            sa.text("UPDATE site_settings SET liqpay_private_key = :val "
                    "WHERE id = :id"),
            {'val': plaintext, 'id': row_id},
        )

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.alter_column(
            'liqpay_private_key',
            existing_type=sa.String(length=500),
            type_=sa.String(length=255),
            existing_nullable=True,
        )
