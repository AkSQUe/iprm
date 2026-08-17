"""Контент продажної сторінки курсу

Revision ID: course_landing_20260817
Revises: online_cover_20260817
Create Date: 2026-08-17 20:10:00.000000

Сторінки курсу (очного й онлайн) переверстуються за продажним лендингом
(docs/plan-course-landing-redesign.md). Референс приносить чотири нові
змістові блоки, яких у моделі не було: смуга цифр довіри, картки "що
зміниться у практиці", галерея з практики й акцентна плашка в програмі.
Плюс збагачуються три наявні: тариф отримує прапорець і явне виділення,
тренер -- короткі цифри, форма запиту -- поля продажної заявки.

Усі колонки nullable і без server_default: курс, якому контент ще не
заповнили, просто не показує відповідну секцію. Виняток -- is_featured у
тарифів: там потрібне саме false, а не NULL, бо це прапорець вибору, і
трьохзначна логіка в шаблоні була б зайвою.

Галерея власного поля не має: фото живуть у медіа-реєстрі з
usage_type='gallery' (значення вже є в MediaFile.USAGE_TYPES), а тут
з'являється лише caption -- видимий підпис, на відміну від alt_text.

Поліморфізм program_blocks -- окремою ревізією
(program_blocks_polymorphic_20260817): вона одна тут ризикована, і її має
бути видно в історії окремо, щоб відкочувати самостійно.
"""
from alembic import op
import sqlalchemy as sa


revision = 'course_landing_20260817'
down_revision = 'online_cover_20260817'
branch_labels = None
depends_on = None


# Спільний для courses й online_courses набір: сторінки зібрані з тих самих
# партіалів, тож і колонки називаються однаково.
LANDING_COLUMNS = (
    ('proof_stats', lambda: sa.Column('proof_stats', sa.JSON(), nullable=True)),
    ('benefits', lambda: sa.Column('benefits', sa.JSON(), nullable=True)),
    ('practice_note_title',
     lambda: sa.Column('practice_note_title', sa.String(200), nullable=True)),
    ('practice_note_text',
     lambda: sa.Column('practice_note_text', sa.Text(), nullable=True)),
    ('gallery_intro',
     lambda: sa.Column('gallery_intro', sa.String(500), nullable=True)),
)


def upgrade():
    with op.batch_alter_table('courses') as batch:
        for _name, make in LANDING_COLUMNS:
            batch.add_column(make())

    with op.batch_alter_table('online_courses') as batch:
        for _name, make in LANDING_COLUMNS:
            batch.add_column(make())
        # Онлайн-курс доганяє офлайновий за складом контенту: аудиторія,
        # FAQ, фінальний заклик і тренер у нього були відсутні як поля.
        batch.add_column(sa.Column('target_audience', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('faq', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('final_cta_text', sa.String(300), nullable=True))
        batch.add_column(sa.Column('trainer_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            'fk_online_courses_trainer_id', 'trainers',
            ['trainer_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index(
        'ix_online_courses_trainer_id', 'online_courses', ['trainer_id'],
    )

    with op.batch_alter_table('trainers') as batch:
        batch.add_column(sa.Column('highlights', sa.JSON(), nullable=True))

    with op.batch_alter_table('instance_tariffs') as batch:
        batch.add_column(sa.Column('badge', sa.String(60), nullable=True))
        batch.add_column(sa.Column(
            'is_featured', sa.Boolean(), nullable=False, server_default=sa.false(),
        ))

    with op.batch_alter_table('media_files') as batch:
        batch.add_column(sa.Column('caption', sa.String(255), nullable=True))

    with op.batch_alter_table('course_requests') as batch:
        batch.add_column(sa.Column('name', sa.String(120), nullable=True))
        batch.add_column(sa.Column('messenger', sa.String(20), nullable=True))
        batch.add_column(sa.Column(
            'consent_at', sa.DateTime(timezone=True), nullable=True,
        ))
        # NULL проходить свідомо: історичні заявки месенджера не мають, і
        # коротка форма "залишити запит" його не питає.
        batch.create_check_constraint(
            'ck_course_requests_messenger',
            "messenger IN ('telegram', 'viber', 'whatsapp', 'phone', 'email')"
            " OR messenger IS NULL",
        )

    # Відгук може не належати жодному курсу (загальні відгуки про Інститут),
    # тож CHECK "рівно один власник" тут навмисно відсутній -- на відміну від
    # program_blocks у наступній ревізії.
    with op.batch_alter_table('reviews') as batch:
        batch.add_column(sa.Column('online_course_id', sa.BigInteger(), nullable=True))
        batch.create_foreign_key(
            'fk_reviews_online_course_id', 'online_courses',
            ['online_course_id'], ['id'], ondelete='SET NULL',
        )


def downgrade():
    with op.batch_alter_table('reviews') as batch:
        batch.drop_constraint('fk_reviews_online_course_id', type_='foreignkey')
        batch.drop_column('online_course_id')

    with op.batch_alter_table('course_requests') as batch:
        batch.drop_constraint('ck_course_requests_messenger', type_='check')
        batch.drop_column('consent_at')
        batch.drop_column('messenger')
        batch.drop_column('name')

    with op.batch_alter_table('media_files') as batch:
        batch.drop_column('caption')

    with op.batch_alter_table('instance_tariffs') as batch:
        batch.drop_column('is_featured')
        batch.drop_column('badge')

    with op.batch_alter_table('trainers') as batch:
        batch.drop_column('highlights')

    op.drop_index('ix_online_courses_trainer_id', table_name='online_courses')
    with op.batch_alter_table('online_courses') as batch:
        batch.drop_constraint('fk_online_courses_trainer_id', type_='foreignkey')
        batch.drop_column('trainer_id')
        batch.drop_column('final_cta_text')
        batch.drop_column('faq')
        batch.drop_column('target_audience')
        for name, _make in reversed(LANDING_COLUMNS):
            batch.drop_column(name)

    with op.batch_alter_table('courses') as batch:
        for name, _make in reversed(LANDING_COLUMNS):
            batch.drop_column(name)
