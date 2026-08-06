"""Відкладене надсилання листа "Реєстрацію підтверджено"

Revision ID: reg_email_delay_20260806
Revises: thankyou_promo_20260806
Create Date: 2026-08-06 23:10:00.000000

Хто платить одразу (підтверджує платіж у застосунку банку), встигав
отримати лист "до оплати" ще під час платежу. Пауза дає платежу дійти:
якщо за цей час прийшла оплата, лист не надсилається взагалі.

site_settings.registration_email_delay_minutes -- тривалість паузи
(0 = слати негайно, як раніше).

event_registrations.confirmation_email_due_at -- коли планувальник має
надіслати лист. Заповнюється лише публічним чекаутом, тож реєстрації від
адміна та xlsx-імпорту під розсилку не потрапляють.
"""
from alembic import op
import sqlalchemy as sa


revision = 'reg_email_delay_20260806'
down_revision = 'thankyou_promo_20260806'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'registration_email_delay_minutes', sa.Integer(), nullable=False,
            server_default='5',
        ))

    op.add_column(
        'event_registrations',
        sa.Column('confirmation_email_due_at', sa.DateTime(timezone=True),
                  nullable=True),
    )
    # Планувальник щохвилини питає "кому вже час" -- індекс саме під цей фільтр.
    op.create_index(
        'ix_event_registrations_confirmation_email_due_at',
        'event_registrations', ['confirmation_email_due_at'],
    )


def downgrade():
    op.drop_index('ix_event_registrations_confirmation_email_due_at',
                  table_name='event_registrations')
    op.drop_column('event_registrations', 'confirmation_email_due_at')

    with op.batch_alter_table('site_settings') as batch:
        batch.drop_column('registration_email_delay_minutes')
