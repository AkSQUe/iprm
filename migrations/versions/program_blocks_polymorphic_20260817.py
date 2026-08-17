"""Блоки програми -- спільні для очних і онлайн-курсів

Revision ID: program_blocks_poly_20260817
Revises: course_landing_20260817
Create Date: 2026-08-17 20:25:00.000000

Онлайн-курсу потрібна програма навчання -- рівно така сама, як в офлайнового.
Альтернативою була JSON-колонка на online_courses, але це дало б два джерела
правди для тієї самої сутності й два редактори в адмінці. Тому program_blocks
стає поліморфною: course_id АБО online_course_id, рівно один із двох.

Ризикована частина -- саме зняття NOT NULL з course_id, тому ревізія окрема
від course_landing_20260817: її можна відкотити, не чіпаючи решту контенту.

Про CHECK. Наявні рядки його не порушують за побудовою: у всіх course_id
заповнений, а online_course_id щойно доданий і скрізь NULL, отже
(FALSE) <> (TRUE) = TRUE. Ризик не в даних, а в коді: будь-яке місце, що
створює блок без власника, тепер впаде на вставці, а не збереже сироту.
Це і є мета -- блок без власника мовчки випадав би з обох сторінок і лишався
в базі назавжди.

Downgrade НЕ намагається зберегти блоки онлайн-курсів: у старій схемі їм
немає де жити, тож вони видаляються явно перед поверненням NOT NULL. Інакше
відкат падав би з незрозумілою помилкою обмеження.
"""
from alembic import op
import sqlalchemy as sa


revision = 'program_blocks_poly_20260817'
down_revision = 'course_landing_20260817'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('program_blocks') as batch:
        batch.add_column(sa.Column('online_course_id', sa.BigInteger(), nullable=True))
        batch.alter_column(
            'course_id', existing_type=sa.BigInteger(), nullable=True,
        )
        batch.create_foreign_key(
            'fk_program_blocks_online_course_id', 'online_courses',
            ['online_course_id'], ['id'], ondelete='CASCADE',
        )
        batch.create_check_constraint(
            'ck_program_blocks_single_owner',
            '(course_id IS NULL) <> (online_course_id IS NULL)',
        )
    op.create_index(
        'ix_program_blocks_online_course_id', 'program_blocks', ['online_course_id'],
    )


def downgrade():
    # Блоки онлайн-курсів у старій схемі не представлені -- прибираємо їх,
    # інакше повернення NOT NULL впаде.
    op.execute('DELETE FROM program_blocks WHERE course_id IS NULL')

    op.drop_index('ix_program_blocks_online_course_id', table_name='program_blocks')
    with op.batch_alter_table('program_blocks') as batch:
        batch.drop_constraint('ck_program_blocks_single_owner', type_='check')
        batch.drop_constraint('fk_program_blocks_online_course_id', type_='foreignkey')
        batch.alter_column(
            'course_id', existing_type=sa.BigInteger(), nullable=False,
        )
        batch.drop_column('online_course_id')
