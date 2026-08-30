"""Meta-форма знає, про який захід вона.

Партнерська подія `lead.created` має нести менеджеру MM Medic не лише
відповіді людини, а й те, що саме їй пропонувати. Meta про наші курси не
знає нічого, тож зв'язок ставиться руками в адмінці.

SET NULL, а не CASCADE: видалення заходу не має забирати з собою схему
форми. На ній тримаються підписи питань усіх уже наявних заявок, і без неї
картка ліда знову показувала б внутрішні ключі Meta.

Revision ID: meta_form_offer_20260831
Revises: meta_form_schema_20260830
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_form_offer_20260831'
down_revision = 'meta_form_schema_20260830'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'meta_lead_forms',
        sa.Column('course_instance_id', sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        'fk_meta_lead_forms_course_instance', 'meta_lead_forms',
        'course_instances', ['course_instance_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_meta_lead_forms_course_instance_id', 'meta_lead_forms',
                    ['course_instance_id'])


def downgrade():
    op.drop_index('ix_meta_lead_forms_course_instance_id',
                  table_name='meta_lead_forms')
    op.drop_constraint('fk_meta_lead_forms_course_instance', 'meta_lead_forms',
                       type_='foreignkey')
    op.drop_column('meta_lead_forms', 'course_instance_id')
