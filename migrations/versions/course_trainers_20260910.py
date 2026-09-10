"""перехід на таблиці звʼязку course_trainers / course_instance_trainers

Revision ID: course_trainers_20260910
Revises: merge_bpr_heads_20260910
Create Date: 2026-09-10 00:00:00.000000

Захід міг мати лише одного тренера (courses.trainer_id, course_instances.
trainer_id -- одиночний FK). Тепер список тренерів живе в двох таблицях
звʼязку з позицією (перший -- головний лектор), моделі (app/models/
trainer_links.py) уже написані й читаються кодом кількома тасками раніше --
цій міграції лишається створити самі таблиці, перенести дані й прибрати
одиночні колонки.

Заразом:
* lecturer_certificates: UNIQUE(instance_id) -> UNIQUE(instance_id, trainer_id).
  Захід із кількома лекторами видає кілька сертифікатів (по одному на
  тренера), і стара пара "один сертифікат на проведення" більше не тримає.
  Прибираємо старий UNIQUE інтроспекцією (_drop_instance_unique), а не за
  жорсткою назвою: на dev-БД цього плану він виявився голим unique-індексом
  без named constraint (db.create_all() десь випередив ланцюжок міграцій),
  тож жорстка назва впала б на "обмеження не існує".
* courses.speaker_info прибирається: вільний текст біографії, який ніколи не
  рендерився публічно (блок спікерів завжди збирався з карток тренерів) і
  вже прибраний з усього коду (попередній коміт).

П'ять кроків upgrade -- у цьому порядку, бо кожен наступний спирається на
попередній: спершу мають існувати таблиці звʼязку (1), потім у них має бути
що читати (2), лише тоді можна прибирати джерело (3), і лише після цього
чіпати lecturer_certificates (4) і speaker_info (5), що від trainer_id/
course_trainers не залежать -- порядок між 4-5 і 1-3 довільний, але лишається
той самий, що в спеці задачі.
"""
from alembic import op
import sqlalchemy as sa


revision = 'course_trainers_20260910'
down_revision = 'merge_bpr_heads_20260910'
branch_labels = None
depends_on = None


# (таблиця звʼязку, її FK-колонка на "захід", таблиця-джерело trainer_id)
_LINKS = (
    ('course_trainers', 'course_id', 'courses'),
    ('course_instance_trainers', 'instance_id', 'course_instances'),
)


def _backfill_sql(link_table, link_fk, source_table):
    """Наявний trainer_id стає головним (position=0) записом таблиці
    звʼязку. WHERE відсікає NULL на рівні SELECT -- рядки без тренера не
    породжують запису, а не породжують і одразу видаляються."""
    return (
        f'INSERT INTO {link_table} ({link_fk}, trainer_id, position) '
        f'SELECT id, trainer_id, 0 FROM {source_table} WHERE trainer_id IS NOT NULL'
    )


def _restore_first_trainer_sql(target_table, link_table, link_fk):
    """Дзеркало _backfill_sql для downgrade: у колонку повертається рівно
    той тренер, що на position=0. Тренери 1+ у джерелі UPDATE не бачить --
    колонка вміщає одного, це і є втрата, задокументована в downgrade()."""
    return (
        f'UPDATE {target_table} SET trainer_id = ('
        f'SELECT {link_table}.trainer_id FROM {link_table} '
        f'WHERE {link_table}.{link_fk} = {target_table}.id '
        f'AND {link_table}.position = 0'
        f')'
    )


def _duplicate_certificate_instances(bind):
    """instance_id-и з більш ніж одним lecturer_certificates -- саме вони
    зроблять UNIQUE(instance_id) непоновлюваним. Нормальний стан після
    переходу на кількох лекторів (кожному -- свій сертифікат), тож перевірка
    очікує знайти такі рядки на будь-якій живій БД, а не трактує їх як
    пошкодження даних."""
    rows = bind.execute(sa.text(
        'SELECT instance_id FROM lecturer_certificates '
        'GROUP BY instance_id HAVING COUNT(*) > 1 '
        'ORDER BY instance_id'
    )).fetchall()
    return [row[0] for row in rows]


def _drop_instance_unique(bind):
    """Прибрати наявне UNIQUE(instance_id) на lecturer_certificates --
    named constraint АБО голий unique-індекс, залежно від того, як
    конкретна БД фактично прийшла до цього стану.

    Ревізія a7c8e9f05b62 створювала саме named constraint
    (uq_lecturer_certificates_instance), але дев-БД цього плану показала
    голий UNIQUE INDEX ix_lecturer_certificates_instance_id без жодного
    named constraint (get_unique_constraints() -- порожньо; перевірено
    інтроспекцією перед написанням цієї функції) -- десь по дорозі схему
    піднімали через db.create_all() замість повного програвання ланцюжка
    міграцій. `ALTER TABLE ... DROP CONSTRAINT` на голому індексі падає з
    «обмеження не існує», а `DROP INDEX` на constraint-індексі -- з
    протилежною помилкою, тож перевіряємо інтроспекцією, а не вгадуємо
    назву й тип наперед.
    """
    inspector = sa.inspect(bind)
    for uc in inspector.get_unique_constraints('lecturer_certificates'):
        if uc['column_names'] == ['instance_id']:
            op.drop_constraint(uc['name'], 'lecturer_certificates', type_='unique')
            return
    for idx in inspector.get_indexes('lecturer_certificates'):
        if idx['unique'] and idx['column_names'] == ['instance_id']:
            op.drop_index(idx['name'], table_name='lecturer_certificates')
            return
    raise RuntimeError(
        'Не знайдено UNIQUE(instance_id) на lecturer_certificates -- ні '
        'named constraint, ні unique-індекс. Схема відрізняється від '
        'очікуваної (жодна з двох форм, під які написана ця міграція) -- '
        'перевірте вручну перед тим, як продовжувати upgrade.'
    )


def _guard_unique_instance_restorable(bind):
    """Падаємо зрозуміло ДО спроби ALTER TABLE, а не після: сира помилка
    Postgres 'violates unique constraint uq_lecturer_certificates_instance'
    не називає жодного проведення, і той, хто відкочує міграцію вночі,
    лишається без зачіпки, з якої зайвий сертифікат прибирати."""
    duplicates = _duplicate_certificate_instances(bind)
    if duplicates:
        ids = ', '.join(str(i) for i in duplicates)
        raise RuntimeError(
            'Відкат course_trainers_20260910 неможливий: проведення '
            f'(course_instances.id) {ids} мають більше одного лекторського '
            'сертифіката (lecturer_certificates) -- UNIQUE(instance_id) '
            'такого не витримає. Це очікувано для заходів з кількома '
            'лекторами (кожен отримує окремий сертифікат): перед відкатом '
            'вирішіть вручну, який запис лишити на кожне з цих проведень, '
            'або не відкочуйте цю ревізію.'
        )


def upgrade():
    # --- 1: таблиці звʼязку (структура -- дзеркало app/models/trainer_links.py) ---
    op.create_table(
        'course_trainers',
        sa.Column('course_id', sa.BigInteger(), nullable=False),
        sa.Column('trainer_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainer_id'], ['trainers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('course_id', 'trainer_id'),
    )
    op.create_index(
        'ix_course_trainers_trainer_id', 'course_trainers', ['trainer_id'],
    )

    op.create_table(
        'course_instance_trainers',
        sa.Column('instance_id', sa.BigInteger(), nullable=False),
        sa.Column('trainer_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['instance_id'], ['course_instances.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainer_id'], ['trainers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('instance_id', 'trainer_id'),
    )
    op.create_index(
        'ix_course_instance_trainers_trainer_id', 'course_instance_trainers', ['trainer_id'],
    )

    # --- 2: бекфіл -- наявний trainer_id стає головним (position 0) ---
    bind = op.get_bind()
    for link_table, link_fk, source_table in _LINKS:
        bind.execute(sa.text(_backfill_sql(link_table, link_fk, source_table)))

    # --- 3: одиночні колонки більше нікому не потрібні (усі читачі -- на
    # таблицях звʼязку ще з попередніх тасків цього плану) ---
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('trainer_id')
    with op.batch_alter_table('course_instances', schema=None) as batch_op:
        batch_op.drop_column('trainer_id')

    # --- 4: захід із кількома лекторами -- кілька сертифікатів ---
    _drop_instance_unique(bind)
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_lecturer_certificates_instance_trainer', ['instance_id', 'trainer_id'],
        )

    # --- 5: вільний текст біографії, який ніколи не рендерився публічно ---
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.drop_column('speaker_info')


def downgrade():
    """УВАГА: тренери з позицій 1+ при відкаті ВТРАЧАЮТЬСЯ -- одиночна
    колонка trainer_id вміщає рівно одного, у неї повертається лише
    position=0. Це незворотно: другого й третього лектора заходу після
    відкату ніде не лишається, доки міграцію не накотять знову.

    Колонка courses.speaker_info повертається ПОРОЖНЬОЮ: її вміст -- вручну
    переписані біографії тренерів, які вже дублюються в картках тренерів
    (звідти й береться публічний блок спікерів). Відновлювати нема звідки
    (текст ніде більше не зберігався) і нема навіщо (те саме є в картці).

    Перед поверненням UNIQUE(instance_id) перевіряємо дублікати самі й
    падаємо зі зрозумілим текстом -- інакше ALTER TABLE впаде на "violates
    unique constraint uq_lecturer_certificates_instance", не назвавши, які
    саме проведення заважають.
    """
    bind = op.get_bind()
    _guard_unique_instance_restorable(bind)

    # --- 5 reversed: колонка повертається, вміст -- ні (див. докстрінг) ---
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('speaker_info', sa.Text(), nullable=True))

    # --- 4 reversed: guard вище вже підтвердив, що ALTER не впаде ---
    with op.batch_alter_table('lecturer_certificates', schema=None) as batch_op:
        batch_op.drop_constraint(
            'uq_lecturer_certificates_instance_trainer', type_='unique',
        )
        batch_op.create_unique_constraint(
            'uq_lecturer_certificates_instance', ['instance_id'],
        )

    # --- 3 reversed: одиночні колонки повертаються порожніми ---
    with op.batch_alter_table('courses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_courses_trainer_id', 'trainers', ['trainer_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_courses_trainer_id', 'courses', ['trainer_id'])

    with op.batch_alter_table('course_instances', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trainer_id', sa.BigInteger(), nullable=True))
        batch_op.create_foreign_key(
            'fk_course_instances_trainer_id', 'trainers', ['trainer_id'], ['id'], ondelete='SET NULL',
        )
    op.create_index('ix_course_instances_trainer_id', 'course_instances', ['trainer_id'])

    # --- 2 reversed: заповнюємо щойно повернуті колонки з position=0 ---
    for target_table, link_table, link_fk in (
        ('courses', 'course_trainers', 'course_id'),
        ('course_instances', 'course_instance_trainers', 'instance_id'),
    ):
        bind.execute(sa.text(
            _restore_first_trainer_sql(target_table, link_table, link_fk),
        ))

    # --- 1 reversed: таблиці звʼязку більше нізвідки не читаються ---
    op.drop_index(
        'ix_course_instance_trainers_trainer_id', table_name='course_instance_trainers',
    )
    op.drop_table('course_instance_trainers')
    op.drop_index('ix_course_trainers_trainer_id', table_name='course_trainers')
    op.drop_table('course_trainers')
