"""Канонічний телефон у профілі + індекси під інкрементальну синхронізацію

Партнер (MM Medic) будує єдину базу клієнтів і зшиває картку саме за
телефоном: email тут ненадійний -- близько третини акаунтів мають технічні
адреси. Але `medical_profiles.phone` -- вільний рядок, і зіставляти за ним
неможливо.

Дані проду на 2026-08-11 (1264 профілі з телефоном):
  * 1253 вже канонічні `+380XXXXXXXXX`;
  * 11 явно покручені -- закороткі, задовгі або чужі коди
    (`+3809828628`, `+3806784014070730886`, `+809679019055`);
  * рівно один номер ділять два акаунти.

Тому:
  * `phone_e164` заповнюється ЛИШЕ для розпізнаних номерів. Вигадувати
    канонічну форму для покручених означало б зшити не тих людей;
  * індекс, а не UNIQUE. Один спільний номер на два акаунти -- це клініка з
    єдиним контактним телефоном, звичайна річ. Унікальність зламала б їм
    реєстрацію заради одного випадку на 1264, а неоднозначність усе одно
    розбирає партнер, у якого для цього є черга ручного зіставлення.

Друга частина -- індекси на `updated_at`. Колонка є скрізь через
TimestampMixin, але без індексу: інкрементальна вибірка «що змінилось після
X» йшла б повним скановм по кожній таблиці на кожен прогін синхронізації.

Revision ID: phone_e164_20260811
Revises: instance_city_20260810
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa


revision = 'phone_e164_20260811'
down_revision = 'instance_city_20260810'
branch_labels = None
depends_on = None


# Таблиці, які партнер тягне інкрементально за курсором `updated_since`.
SYNC_TABLES = (
    'users',
    'medical_profiles',
    'event_registrations',
    'b2b_requests',
    'course_requests',
)


def upgrade():
    op.add_column(
        'medical_profiles',
        sa.Column('phone_e164', sa.String(length=16), nullable=True),
    )
    op.create_index(
        'ix_medical_profiles_phone_e164', 'medical_profiles', ['phone_e164'],
    )

    # Бекфіл. Нормалізація повторює `app.utils.normalize_phone`, але SQL-ом:
    # тягнути 1279 рядків у Python заради трьох гілок regexp не варто.
    #   +380XXXXXXXXX -- як є
    #   380XXXXXXXXX  -- дописати '+'
    #   0XXXXXXXXX    -- дописати '+38'
    # Усе інше лишається NULL і потрапляє в звіт нижче.
    op.execute(
        """
        UPDATE medical_profiles SET phone_e164 = CASE
            WHEN phone ~ '^\\+380[0-9]{9}$' THEN phone
            WHEN phone ~ '^380[0-9]{9}$'    THEN '+' || phone
            WHEN phone ~ '^0[0-9]{9}$'      THEN '+38' || phone
        END
        WHERE phone IS NOT NULL AND phone <> ''
        """
    )

    for table in SYNC_TABLES:
        op.create_index(f'ix_{table}_updated_at', table, ['updated_at'])


def downgrade():
    for table in SYNC_TABLES:
        op.drop_index(f'ix_{table}_updated_at', table_name=table)

    op.drop_index('ix_medical_profiles_phone_e164', table_name='medical_profiles')
    op.drop_column('medical_profiles', 'phone_e164')
