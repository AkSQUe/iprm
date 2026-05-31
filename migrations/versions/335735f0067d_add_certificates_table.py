"""add certificates table

Revision ID: 335735f0067d
Revises: d5e6f7a8b9c0
Create Date: 2026-05-31 19:02:19.295788

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '335735f0067d'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'certificates',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
        sa.Column('registration_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('number', sa.String(length=40), nullable=False),
        sa.Column('recipient_name', sa.String(length=255), nullable=False),
        sa.Column('event_title', sa.String(length=500), nullable=False),
        sa.Column('event_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cpd_points', sa.Integer(), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_by_id', sa.BigInteger(), nullable=True),
        sa.Column('pdf_path', sa.String(length=255), nullable=False),
        sa.Column('revoked', sa.Boolean(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['issued_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['registration_id'], ['event_registrations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_certificates_number'), ['number'], unique=True)
        batch_op.create_index(batch_op.f('ix_certificates_registration_id'), ['registration_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_certificates_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('certificates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_certificates_user_id'))
        batch_op.drop_index(batch_op.f('ix_certificates_registration_id'))
        batch_op.drop_index(batch_op.f('ix_certificates_number'))
    op.drop_table('certificates')
