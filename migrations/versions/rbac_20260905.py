"""RBAC: ролі, права, зв'язки, перенесення is_admin -> super_admin.

Revision ID: rbac_20260905
Revises: email_trigger_transfer_20260831

Створює чотири таблиці, заводить роль super_admin і видає її всім, у кого
стояв is_admin. Решту ролей і всі права створює ``flask rbac sync``
(міграція не імпортує реєстр застосунку). Колонка is_admin прибирається
цим самим файлом у Task 8 плану: до того код ще читає її.
"""
import sqlalchemy as sa
from alembic import op

revision = 'rbac_20260905'
down_revision = 'email_trigger_transfer_20260831'
branch_labels = None
depends_on = None

_BIGPK = sa.BigInteger().with_variant(sa.Integer, 'sqlite')


def upgrade():
    op.create_table(
        'roles',
        sa.Column('id', _BIGPK, primary_key=True),
        sa.Column('name', sa.String(50), nullable=False, unique=True),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('color', sa.String(20), nullable=False, server_default='gray'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
    )
    op.create_table(
        'permissions',
        sa.Column('id', _BIGPK, primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('module', sa.String(50), nullable=False),
    )
    op.create_index('ix_permissions_module', 'permissions', ['module'])
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.BigInteger(),
                  sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('permission_id', sa.BigInteger(),
                  sa.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True),
    )
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('role_id', sa.BigInteger(),
                  sa.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True)),
        sa.Column('assigned_by', sa.BigInteger(),
                  sa.ForeignKey('users.id', ondelete='SET NULL')),
    )

    conn = op.get_bind()
    roles = sa.table(
        'roles',
        sa.column('id', sa.BigInteger), sa.column('name', sa.String),
        sa.column('display_name', sa.String), sa.column('description', sa.Text),
        sa.column('color', sa.String), sa.column('is_system', sa.Boolean),
        sa.column('sort_order', sa.Integer),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    conn.execute(roles.insert().values(
        name='super_admin', display_name='Супер-адміністратор',
        description='Повний доступ і керування ролями. Перевірки прав не читає.',
        color='red', is_system=True, sort_order=0, created_at=sa.func.now(),
    ))
    role_id = conn.execute(
        sa.select(roles.c.id).where(roles.c.name == 'super_admin')
    ).scalar_one()
    conn.execute(sa.text(
        'INSERT INTO user_roles (user_id, role_id, assigned_at) '
        'SELECT id, :rid, CURRENT_TIMESTAMP FROM users WHERE is_admin IS TRUE'
    ), {'rid': role_id})

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_admin')


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_admin', sa.Boolean(), server_default=sa.false()))
    op.execute(sa.text(
        "UPDATE users SET is_admin = TRUE WHERE id IN ("
        "SELECT ur.user_id FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
        "WHERE r.name = 'super_admin')"
    ))

    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_index('ix_permissions_module', table_name='permissions')
    op.drop_table('permissions')
    op.drop_table('roles')
