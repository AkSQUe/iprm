"""Кабінет тренера: прив'язка до акаунта, анкета, пропозиції курсу, договір і FAQ.

Revision ID: trainer_cabinet_20260919
Revises: posthog_secondary_20260913

Бекфілу немає: наявні тренери лишаються без акаунта (user_id NULL), поки
адмін не прив'яже їх у формі тренера. trainer_faq_html порожній означає
«текст за замовчуванням з коду».
"""
import sqlalchemy as sa
from alembic import op

revision = 'trainer_cabinet_20260919'
down_revision = 'posthog_secondary_20260913'
branch_labels = None
depends_on = None


def _secret(name):
    return sa.Column(name, sa.String(length=500), nullable=False, server_default='')


def upgrade():
    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.BigInteger(), nullable=True))
        batch_op.create_unique_constraint('uq_trainers_user_id', ['user_id'])
        batch_op.create_foreign_key(
            'fk_trainers_user_id_users', 'users', ['user_id'], ['id'],
            ondelete='SET NULL')

    op.create_table(
        'trainer_profiles',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('full_name', sa.String(length=200)),
        sa.Column('birth_date', sa.Date()),
        sa.Column('education', sa.Text()),
        sa.Column('position_titles', sa.Text()),
        sa.Column('workplace', sa.Text()),
        sa.Column('phone', sa.String(length=30)),
        sa.Column('email', sa.String(length=255)),
        sa.Column('social_links', sa.Text()),
        sa.Column('photo_media_id', sa.BigInteger(),
                  sa.ForeignKey('media_files.id', ondelete='SET NULL')),
        sa.Column('photo_url', sa.String(length=500)),
        sa.Column('fop_recipient', sa.String(length=300)),
        _secret('fop_iban'),
        _secret('fop_rnokpp'),
        sa.Column('fop_payment_purpose', sa.Text()),
        _secret('card_number'),
        _secret('tax_id'),
        sa.Column('registration_address', sa.Text()),
        sa.Column('edrpou', sa.String(length=20)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )

    op.create_table(
        'trainer_course_proposals',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('trainer_id', sa.BigInteger(),
                  sa.ForeignKey('trainers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(length=50), nullable=False),
        sa.Column('theses', sa.JSON(), nullable=False),
        sa.Column('language', sa.String(length=50)),
        sa.Column('relevance', sa.Text()),
        sa.Column('target_specialties', sa.Text()),
        sa.Column('resources', sa.Text()),
        sa.Column('future_topics', sa.Text()),
        sa.Column('quiz_url', sa.String(length=500)),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('curator_comment', sa.Text()),
        sa.Column('submitted_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('draft', 'submitted', 'accepted')",
                           name='ck_trainer_course_proposals_status'),
    )
    op.create_index('ix_trainer_course_proposals_trainer_id',
                    'trainer_course_proposals', ['trainer_id'])
    op.create_index('ix_trainer_course_proposals_status',
                    'trainer_course_proposals', ['status'])

    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_faq_html', sa.Text(),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_email', sa.String(length=255),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_pdf', sa.LargeBinary()))
        batch_op.add_column(sa.Column('trainer_contract_filename', sa.String(length=255),
                                      nullable=False, server_default=''))
        batch_op.add_column(sa.Column('trainer_contract_uploaded_at',
                                      sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table('site_settings', schema=None) as batch_op:
        batch_op.drop_column('trainer_contract_uploaded_at')
        batch_op.drop_column('trainer_contract_filename')
        batch_op.drop_column('trainer_contract_pdf')
        batch_op.drop_column('trainer_contract_email')
        batch_op.drop_column('trainer_faq_html')

    op.drop_index('ix_trainer_course_proposals_status',
                  table_name='trainer_course_proposals')
    op.drop_index('ix_trainer_course_proposals_trainer_id',
                  table_name='trainer_course_proposals')
    op.drop_table('trainer_course_proposals')
    op.drop_table('trainer_profiles')

    with op.batch_alter_table('trainers', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trainers_user_id_users', type_='foreignkey')
        batch_op.drop_constraint('uq_trainers_user_id', type_='unique')
        batch_op.drop_column('user_id')
