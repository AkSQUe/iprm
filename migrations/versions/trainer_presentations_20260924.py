"""Презентації тренерів до заходів: таблиця trainer_presentations + тригер листа.

Тренер завантажує презентацію до свого заходу з кабінету; співробітники
(super_admin, admin, content_editor) отримують лист із посиланням. Файл --
на диску (TRAINER_PRESENTATION_FOLDER), у таблиці лише метадані.

Тригер 'trainer_presentation' додається в CHECK ck_email_logs_trigger (той
самий перелік, що в EmailLog.__table_args__ і EmailLog.TRIGGERS).

Revision ID: trainer_presentations_20260924
Revises: trainer_specialty_20260924
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_presentations_20260924'
down_revision = 'trainer_specialty_20260924'
branch_labels = None
depends_on = None

_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'backup_report', 'materials', "
    "'referral', 'meta_lead', 'transfer', 'quiz', 'trainer_proposal', "
    "'trainer_requisites', 'material_request', 'trainer_presentation', 'test')"
)


def upgrade():
    op.create_table(
        'trainer_presentations',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('instance_id', sa.BigInteger(),
                  sa.ForeignKey('course_instances.id', ondelete='CASCADE'), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_name', sa.String(length=64), nullable=False),
        sa.Column('mimetype', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('uploaded_by_id', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('stored_name', name='uq_trainer_presentations_stored_name'),
    )
    op.create_index('ix_trainer_presentations_trainer_id', 'trainer_presentations',
                    ['trainer_id'])
    op.create_index('ix_trainer_presentations_instance_id', 'trainer_presentations',
                    ['instance_id'])

    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_NEW)


def downgrade():
    # Перед звуженням CHECK -- прибрати логи з новим тригером, інакше
    # constraint не створиться.
    op.execute("DELETE FROM email_logs WHERE trigger = 'trainer_presentation'")
    with op.batch_alter_table('email_logs', schema=None) as batch_op:
        batch_op.drop_constraint('ck_email_logs_trigger', type_='check')
        batch_op.create_check_constraint('ck_email_logs_trigger', _TRIGGERS_OLD)

    op.drop_index('ix_trainer_presentations_instance_id', table_name='trainer_presentations')
    op.drop_index('ix_trainer_presentations_trainer_id', table_name='trainer_presentations')
    op.drop_table('trainer_presentations')
