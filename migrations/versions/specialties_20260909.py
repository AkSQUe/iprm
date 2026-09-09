"""Довідник спеціальностей і перехід курсу/проведення на коди

Revision ID: specialties_20260909
Revises: transfer_after_days_20260908
Create Date: 2026-09-09 00:00:00.000000

Поле "Спеціальності (для сертифіката)" було вільним рядком
(courses.bpr_specialties): назви набирали руками, і в сертифікат ішло те, що
набрали. Тепер номенклатура (Додаток 1 до Порядку проведення атестації
працівників сфери охорони здоров'я) лежить таблицею specialties, а курс і
проведення посилаються на неї списком кодів.

Наявні значення не губляться: текст звіряється з назвами довідника за
нормалізованою формою, а те, чого в довіднику немає, заводиться в нього
деактивованим рядком.

Знімки сертифікатів (certificates.specialties, lecturer_certificates.specialties)
лишаються рядками -- виданий документ не залежить від довідника -- але
переїжджають зі String(500) у Text: ліміту на кількість обраних позицій немає.
"""
from alembic import op
import sqlalchemy as sa


revision = 'specialties_20260909'
down_revision = 'transfer_after_days_20260908'
branch_labels = None
depends_on = None


# Узагальнення: службові рядки, які обираються як звичайні позиції.
_GROUPS = (
    ('all-medical', 'усі лікарські спеціальності', 'medical'),
    ('all-pharmacy', 'усі фармацевтичні спеціальності', 'pharmacy'),
    ('all-professionals',
     'усі спеціальності професіоналів у сфері охорони здоров’я',
     'professionals'),
    ('all-specialists',
     'усі спеціальності фахівців у сфері охорони здоров’я',
     'specialists'),
)


def upgrade():
    op.create_table(
        'specialties',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=60), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('section', sa.String(length=20), nullable=False),
        sa.Column('is_group', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('translations', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index('ix_specialties_code', 'specialties', ['code'])
    op.create_index('ix_specialties_section', 'specialties', ['section'])

    bind = op.get_bind()
    _seed(bind)

    with op.batch_alter_table('courses') as batch:
        batch.add_column(sa.Column('bpr_specialty_codes', sa.JSON(), nullable=True))
    with op.batch_alter_table('course_instances') as batch:
        batch.add_column(sa.Column('bpr_specialty_codes', sa.JSON(), nullable=True))

    _backfill(bind)

    with op.batch_alter_table('courses') as batch:
        batch.drop_column('bpr_specialties')

    _drop_translation_key(bind)

    with op.batch_alter_table('certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.String(length=500),
                           type_=sa.Text(), existing_nullable=True)
    with op.batch_alter_table('lecturer_certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.String(length=500),
                           type_=sa.Text(), existing_nullable=True)


def _seed(bind):
    """Позиції номенклатури плюс чотири узагальнення."""
    from app.data.specialties import SPECIALTIES

    rows = [{'code': code, 'name': name, 'section': section,
             'is_group': False, 'sort_order': sort_order, 'is_active': True}
            for code, name, section, sort_order in SPECIALTIES]
    rows.extend({'code': code, 'name': name, 'section': section,
                 'is_group': True, 'sort_order': 0, 'is_active': True}
                for code, name, section in _GROUPS)
    bind.execute(
        sa.text('INSERT INTO specialties (code, name, section, is_group, '
                'sort_order, is_active) VALUES (:code, :name, :section, '
                ':is_group, :sort_order, :is_active)'),
        rows,
    )


def _backfill(bind):
    """Старий вільний текст курсу -> список кодів.

    JSON-значення передається типізованим bind-параметром (sa.bindparam з
    type_=sa.JSON), а не рядком '["code"]': Postgres не приймає text у
    json-колонку без явного касту (в SQLite помилка не виникає, тож локально
    вона не виявилась би, а на проді впала б).
    """
    from app.services.specialties import legacy_code_for, normalize_name

    name_to_code = {
        normalize_name(name): code
        for code, name in bind.execute(sa.text('SELECT code, name FROM specialties'))
    }
    # Повний набір зайнятих кодів -- ОКРЕМО від name_to_code.values(): у
    # номенклатурі є коди, чиї назви нормалізуються однаково (регістр/пробіли),
    # тож частина реальних кодів у values() втрачається, і specialty_code()
    # може згенерувати те, що вже зайняте, порушивши UNIQUE(code).
    taken_codes = {code for (code,) in bind.execute(sa.text('SELECT code FROM specialties'))}
    # TRIM, а не просто <> '': рядок із самих пробілів інакше пройшов би далі
    # й після ' '.join(text.split()) перетворився на порожню назву -- код
    # 'specialty' без відповідного рядка в довіднику (legacy_code_for
    # повертає missing='' -- falsy, тож INSERT не станеться, а посилання
    # на неіснуючий код лишиться в courses.bpr_specialty_codes).
    courses = bind.execute(sa.text(
        "SELECT id, bpr_specialties FROM courses "
        "WHERE bpr_specialties IS NOT NULL AND TRIM(bpr_specialties) <> ''"
    )).fetchall()

    update_stmt = sa.text(
        'UPDATE courses SET bpr_specialty_codes = :codes WHERE id = :id'
    ).bindparams(sa.bindparam('codes', type_=sa.JSON))

    for course_id, text in courses:
        code, missing = legacy_code_for(text, name_to_code, taken=taken_codes)
        if missing:
            # Значення, якого немає в номенклатурі, лишається в довіднику
            # деактивованим: у виборі його не пропонують, у наявних курсах
            # воно рендериться далі. Назву обрізаємо до 200 -- ширина
            # specialties.name; вхідний текст курсу міг бути до 500 символів
            # (стара колонка bpr_specialties -- String(500)), і без обрізання
            # INSERT падає на "value too long" посеред деплою.
            bind.execute(
                sa.text('INSERT INTO specialties (code, name, section, is_group, '
                        'sort_order, is_active) VALUES (:code, :name, :section, '
                        'false, 999, false)'),
                {'code': code, 'name': missing[:200], 'section': 'medical'},
            )
            # Ключ -- нормалізована ПОВНА (не обрізана) назва: наступний курс з
            # тим самим довгим текстом має знайти той самий код, а не завести
            # другий рядок-дублікат через розбіжність після обрізання.
            name_to_code[normalize_name(missing)] = code
            taken_codes.add(code)
        bind.execute(update_stmt, {'codes': [code], 'id': course_id})


def _drop_translation_key(bind):
    """Прибрати переклади поля, якого більше немає.

    Інакше ключ 'bpr_specialties' лишався б у courses.translations і виринав
    би в /admin/translations як одиниця перекладу без поля.
    """
    import json

    rows = bind.execute(sa.text(
        'SELECT id, translations FROM courses WHERE translations IS NOT NULL'
    )).fetchall()
    for course_id, stored in rows:
        data = json.loads(stored) if isinstance(stored, str) else stored
        if not isinstance(data, dict):
            continue
        changed = False
        for lang, values in list(data.items()):
            if isinstance(values, dict) and 'bpr_specialties' in values:
                values.pop('bpr_specialties')
                changed = True
        if changed:
            bind.execute(
                sa.text('UPDATE courses SET translations = :value WHERE id = :id')
                .bindparams(sa.bindparam('value', type_=sa.JSON)),
                {'value': data, 'id': course_id},
            )


def downgrade():
    bind = op.get_bind()

    # Обрізати ДО звуження типу, не після: Text -> String(500) на Postgres
    # падає з "value too long for type character varying(500)" на будь-якому
    # знімку, довшому за 500 символів -- а знімок міг стати довшим САМЕ ТОМУ,
    # що upgrade зняв ліміт (список обраних спеціальностей необмежений).
    # Односторонній крок: довші знімки обрізаються назавжди, як і
    # courses.bpr_specialties нижче.
    bind.execute(sa.text(
        "UPDATE certificates SET specialties = SUBSTR(specialties, 1, 500) "
        "WHERE specialties IS NOT NULL"
    ))
    bind.execute(sa.text(
        "UPDATE lecturer_certificates SET specialties = SUBSTR(specialties, 1, 500) "
        "WHERE specialties IS NOT NULL"
    ))

    with op.batch_alter_table('certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.Text(),
                           type_=sa.String(length=500), existing_nullable=True)
    with op.batch_alter_table('lecturer_certificates') as batch:
        batch.alter_column('specialties', existing_type=sa.Text(),
                           type_=sa.String(length=500), existing_nullable=True)

    with op.batch_alter_table('courses') as batch:
        batch.add_column(sa.Column('bpr_specialties', sa.String(length=500),
                                   nullable=True))

    # Односторонній крок: назви склеюємо через кому і обрізаємо до 500
    # символів. Курс, у якому обрано десяток спеціальностей, після відкату
    # матиме урізаний рядок -- відновити його можна тільки повторним
    # накатом ревізії.
    import json

    # dict(Result) тут НЕ можна: у Result є метод .keys() (імена колонок), і
    # dict() бере його за мапінг, а не за ітерований набір пар -- падає з
    # "CursorResult object is not subscriptable". Тому -- .fetchall().
    names = dict(bind.execute(sa.text('SELECT code, name FROM specialties')).fetchall())
    rows = bind.execute(sa.text(
        'SELECT id, bpr_specialty_codes FROM courses '
        'WHERE bpr_specialty_codes IS NOT NULL'
    )).fetchall()
    update_stmt = sa.text('UPDATE courses SET bpr_specialties = :value WHERE id = :id')
    for course_id, stored in rows:
        # SQLite повертає JSON-колонку рядком, Postgres -- уже розібраним
        # списком/словником.
        codes = json.loads(stored) if isinstance(stored, str) else stored
        text = ', '.join(names[c] for c in (codes or []) if c in names)[:500]
        bind.execute(update_stmt, {'value': text or None, 'id': course_id})

    with op.batch_alter_table('course_instances') as batch:
        batch.drop_column('bpr_specialty_codes')
    with op.batch_alter_table('courses') as batch:
        batch.drop_column('bpr_specialty_codes')

    op.drop_index('ix_specialties_section', table_name='specialties')
    op.drop_index('ix_specialties_code', table_name='specialties')
    op.drop_table('specialties')
