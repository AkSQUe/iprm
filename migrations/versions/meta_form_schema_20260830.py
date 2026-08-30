"""Схеми інстант-форм Meta: підписи питань і варіантів відповіді.

`field_data` ліда їх не містить. Для питання з варіантами Graph API кладе
у відповідь ліда внутрішній КЛЮЧ варіанта (`ортопедія_/_травматологія`), а
не його текст -- тому на картці заявки менеджер бачив нижній регістр і
підкреслення замість пробілів. Людський підпис живе окремо, у полі
`questions` самої форми, і його треба десь тримати.

Таблиця, а не колонка на `meta_leads`: схема одна на форму й спільна для
сотень заявок, а приїхати може вже ПІСЛЯ них -- копія в кожному ліді
означала б, що старі картки не полагодяться ніколи.

`questions` -- JSON `{ключ: {label, type, options: {ключ: підпис}}}`.
Окрема таблиця питань дала б JOIN на кожну картку заради даних, які
завжди читаються цілком і разом.

Revision ID: meta_form_schema_20260830
Revises: meta_leads_wait_idx_20260826
"""
import sqlalchemy as sa
from alembic import op

revision = 'meta_form_schema_20260830'
down_revision = 'meta_leads_wait_idx_20260826'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'meta_lead_forms',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('form_id', sa.String(length=64), nullable=False),
        sa.Column('page_id', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=True),
        sa.Column('locale', sa.String(length=16), nullable=True),
        sa.Column('questions', sa.JSON(), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    # Унікальний, а не просто індекс: схема форми одна, і другий рядок під
    # тим самим `form_id` означав би два різні набори підписів на ту саму
    # картку -- залежно від того, який знайдеться першим.
    op.create_index('ix_meta_lead_forms_form_id', 'meta_lead_forms',
                    ['form_id'], unique=True)
    op.create_index('ix_meta_lead_forms_page_id', 'meta_lead_forms', ['page_id'])


def downgrade():
    op.drop_index('ix_meta_lead_forms_page_id', table_name='meta_lead_forms')
    op.drop_index('ix_meta_lead_forms_form_id', table_name='meta_lead_forms')
    op.drop_table('meta_lead_forms')
