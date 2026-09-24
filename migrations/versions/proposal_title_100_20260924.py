"""trainer_course_proposals.title: varchar(50) -> varchar(100).

Назви доповідей у 50 символів не вміщались ("Багата тромбоцитами плазма
PRP та інші аутологічні ..."), куратор попросила щонайменше 100. Межа
форми, підказка й maxlength беруться з TrainerCourseProposal.TITLE_MAX,
тож тут змінюється лише колонка.

Розширення varchar у PostgreSQL -- лише зміна метаданих, без перезапису
таблиці. Відкат звужує назад і обрізає довші назви до 50: інакше ALTER
впав би на першому ж рядку, довшому за стару межу.

Revision ID: proposal_title_100_20260924
Revises: lect_cert_downloaded_20260923
"""
import sqlalchemy as sa
from alembic import op

revision = 'proposal_title_100_20260924'
down_revision = 'lect_cert_downloaded_20260923'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trainer_course_proposals', schema=None) as batch_op:
        batch_op.alter_column('title', existing_type=sa.String(50),
                              type_=sa.String(100), existing_nullable=False)


def downgrade():
    op.execute('UPDATE trainer_course_proposals SET title = LEFT(title, 50) '
               'WHERE LENGTH(title) > 50')
    with op.batch_alter_table('trainer_course_proposals', schema=None) as batch_op:
        batch_op.alter_column('title', existing_type=sa.String(100),
                              type_=sa.String(50), existing_nullable=False)
