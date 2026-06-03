"""lecturer_certificates table

Revision ID: a7c8e9f05b62
Revises: f6b7d8e94a51
Create Date: 2026-06-03 20:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a7c8e9f05b62'
down_revision = 'f6b7d8e94a51'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lecturer_certificates',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('instance_id', sa.BigInteger(), nullable=False),
        sa.Column('trainer_id', sa.BigInteger(), nullable=True),
        sa.Column('number', sa.String(length=40), nullable=False),
        sa.Column('recipient_name', sa.String(length=255), nullable=False),
        sa.Column('event_title', sa.String(length=500), nullable=False),
        sa.Column('event_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('specialties', sa.String(length=500), nullable=True),
        sa.Column('event_type_label', sa.String(length=100), nullable=True),
        sa.Column('event_place', sa.String(length=255), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_by_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['instance_id'], ['course_instances.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainer_id'], ['trainers.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['issued_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instance_id', name='uq_lecturer_certificates_instance'),
        sa.UniqueConstraint('number', name='uq_lecturer_certificates_number'),
    )
    op.create_index('ix_lecturer_certificates_instance_id', 'lecturer_certificates', ['instance_id'])
    op.create_index('ix_lecturer_certificates_trainer_id', 'lecturer_certificates', ['trainer_id'])
    op.create_index('ix_lecturer_certificates_number', 'lecturer_certificates', ['number'])


def downgrade():
    op.drop_index('ix_lecturer_certificates_number', table_name='lecturer_certificates')
    op.drop_index('ix_lecturer_certificates_trainer_id', table_name='lecturer_certificates')
    op.drop_index('ix_lecturer_certificates_instance_id', table_name='lecturer_certificates')
    op.drop_table('lecturer_certificates')
