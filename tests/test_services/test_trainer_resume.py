"""Реєстр колонок резюме тренера."""
from app.extensions import db
from app.models.trainer_profile import TrainerProfile
from app.services import trainer_resume_service as rs
from tests.support.rbac import make_super_admin, make_user_with_role
from tests.test_trainer_cabinet._factories import make_trainer, make_user


def test_default_keys_are_known_columns(app):
    known = {c.key for c in rs.COLUMNS}
    assert set(rs.DEFAULT_KEYS) <= known


def test_normalize_drops_unknown_keys(app):
    admin = make_super_admin(email='tc-res-admin@test.com')
    db.session.commit()
    keys = rs.normalize_keys(['full_name', 'no_such_column'], admin)
    assert keys == ['full_name']


def test_normalize_falls_back_to_defaults_when_empty(app):
    admin = make_super_admin(email='tc-res-admin2@test.com')
    db.session.commit()
    assert rs.normalize_keys([], admin) == list(rs.DEFAULT_KEYS)


def test_normalize_keeps_canonical_order(app):
    admin = make_super_admin(email='tc-res-admin3@test.com')
    db.session.commit()
    canonical = [c.key for c in rs.COLUMNS]
    reversed_pick = list(reversed(canonical[:3]))
    assert rs.normalize_keys(reversed_pick, admin) == canonical[:3]


def test_requisite_fields_are_not_in_registry(app):
    keys = {c.key for c in rs.COLUMNS}
    forbidden = {'fop_iban', 'fop_rnokpp', 'card_number', 'tax_id',
                 'registration_address', 'edrpou'}
    assert keys & forbidden == set()


def test_birth_date_hidden_without_finance_permission(app):
    # content_editor має trainers.view/manage/delete, але НЕ trainers.finance
    # (явний перелік у rbac/registry.py саме заради цього).
    plain = make_user_with_role('content_editor', email='tc-res-plain@test.com')
    db.session.commit()
    assert 'birth_date' not in {c.key for c in rs.available_columns(plain)}


def test_normalize_keys_drops_forbidden_column_even_if_requested(app):
    """Право перевіряється і на шляху нормалізації, не лише при побудові діалогу.

    Саме сюди приходять ключі з форми користувача, тож обхід тут був би
    видачею персональних даних тому, кому їх не показує навіть анкета.
    """
    plain = make_user_with_role('content_editor', email='tc-res-bypass@test.com')
    db.session.commit()
    assert rs.normalize_keys(['birth_date', 'full_name'], plain) == ['full_name']


def test_normalize_keys_keeps_allowed_column_for_finance(app):
    """Дзеркало попереднього тесту: право є -- колонка не зникає.

    Без цієї пари попередній тест міг би проходити з хибної причини --
    наприклад, якби 'birth_date' відкидався як нібито невідомий ключ.
    """
    admin = make_super_admin(email='tc-res-finance@test.com')
    db.session.commit()
    assert 'birth_date' in rs.normalize_keys(['birth_date', 'full_name'], admin)


def test_trainer_without_profile_still_yields_row(app):
    trainer = make_trainer(name='Безанкетний Т.')
    db.session.commit()
    rows = rs.build_rows([trainer], ['full_name', 'workplace'])
    assert rows == [['Безанкетний Т.', '']]


def test_profile_name_wins_over_directory_name(app):
    trainer = make_trainer(name='Довідниковий Т.')
    db.session.add(TrainerProfile(trainer_id=trainer.id,
                                  full_name='Анкетний Т.'))
    db.session.commit()
    db.session.refresh(trainer)
    rows = rs.build_rows([trainer], ['full_name'])
    assert rows == [['Анкетний Т.']]


def test_load_trainers_keeps_request_order_and_drops_unknown(app):
    first = make_trainer(name='Перший Т.')
    second = make_trainer(name='Другий Т.')
    db.session.commit()
    loaded = rs.load_trainers([second.id, 999999, first.id])
    assert [t.id for t in loaded] == [second.id, first.id]


def test_build_rows_reads_profiles_without_extra_queries(app):
    """Кожна клітинка читає поле анкети: анкети мусять прийти разом із
    тренерами, а не окремим запитом на кожен рядок документа."""
    from sqlalchemy import event

    ids = []
    for i in range(5):
        trainer = make_trainer(name=f'Резюме {i} Т.')
        db.session.add(TrainerProfile(trainer_id=trainer.id, workplace=f'Клініка {i}'))
        ids.append(trainer.id)
    db.session.commit()
    db.session.expire_all()

    trainers = rs.load_trainers(ids)
    queries = []
    listener = lambda *a, **k: queries.append(1)  # noqa: E731
    event.listen(db.engine, 'before_cursor_execute', listener)
    try:
        rows = rs.build_rows(trainers, ['full_name', 'workplace'])
    finally:
        event.remove(db.engine, 'before_cursor_execute', listener)
    assert [r[1] for r in rows] == [f'Клініка {i}' for i in range(5)]
    assert queries == []


# --- Офіційна форма «Резюме викладача/тренера» для реєстру БПР -------------

OFFICIAL_FORM_LABELS = [
    'Прізвище, власне ім’я, по батькові (за наявності)',
    'Дата народження',
    'Засоби зв’язку (електронна адреса, номер телефону)',
    'Освіта (рівень освіти та навчальні заклади)',
    'Місце роботи',
    'Професійні сертифікати',
    'Інші відомості',
]


def _profiled_trainer(name, **fields):
    from datetime import date
    trainer = make_trainer(name=name)
    fields.setdefault('birth_date', date(1980, 5, 17))
    db.session.add(TrainerProfile(trainer_id=trainer.id, **fields))
    db.session.commit()
    db.session.refresh(trainer)
    return trainer


def test_form_has_the_official_rows_in_the_official_order(app):
    """Документ іде в пакет до реєстру БПР: рядки й порядок -- як в офіційній
    формі, інакше це вже не та форма."""
    trainer = _profiled_trainer('Формальний Т.')
    pages = rs.build_form([trainer], [c.key for c in rs.COLUMNS])
    assert [label for label, _value in pages[0]] == OFFICIAL_FORM_LABELS


def test_form_fills_rows_from_the_questionnaire(app):
    trainer = _profiled_trainer(
        'Повний Т.', full_name='Іваненко Іван Іванович', education='КНМУ, 2004',
        workplace='Клініка «Здоров’я», Київ', professional_certificates='PRP, 2021',
        position_titles='к.мед.н., доцент', email='ivan@example.com',
        phone='+380501112233')
    values = dict(rs.build_form([trainer], [c.key for c in rs.COLUMNS])[0])

    assert values['Прізвище, власне ім’я, по батькові (за наявності)'] == 'Іваненко Іван Іванович'
    assert values['Дата народження'] == '17.05.1980'
    assert values['Освіта (рівень освіти та навчальні заклади)'] == 'КНМУ, 2004'
    assert values['Місце роботи'] == 'Клініка «Здоров’я», Київ'
    assert values['Професійні сертифікати'] == 'PRP, 2021'
    # «Інші відомості» -- посада та регалії: окремого рядка для них у формі немає.
    assert values['Інші відомості'] == 'к.мед.н., доцент'


def test_form_contacts_row_joins_email_and_phone(app):
    trainer = _profiled_trainer('Контактний Т.', email='a@example.com',
                                phone='+380500000000')
    values = dict(rs.build_form([trainer], ['email', 'phone'])[0])
    contacts = values['Засоби зв’язку (електронна адреса, номер телефону)']
    assert contacts.splitlines() == ['a@example.com', '+380500000000']


def test_unselected_row_stays_in_the_form_but_empty(app):
    """Вибір колонок вирішує, що ЗАПОВНИТИ, а не що показати: без рядка
    документ перестав би бути офіційною формою. Порожній -- для ручного."""
    trainer = _profiled_trainer('Вибірковий Т.', workplace='Клініка', education='КНМУ')
    pages = rs.build_form([trainer], ['full_name', 'workplace'])
    values = dict(pages[0])

    assert [label for label, _v in pages[0]] == OFFICIAL_FORM_LABELS
    assert values['Місце роботи'] == 'Клініка'
    assert values['Освіта (рівень освіти та навчальні заклади)'] == ''


def test_form_birth_date_empty_without_finance_permission(app):
    """Межа приватності та сама, що в анкеті: без trainers.finance рядок
    лишається, а дата -- ні (normalize_keys відкидає ключ)."""
    plain = make_user_with_role('content_editor', email='tc-res-form-plain@test.com')
    trainer = _profiled_trainer('Приватний Т.')
    keys = rs.normalize_keys([c.key for c in rs.COLUMNS], plain)

    values = dict(rs.build_form([trainer], keys)[0])
    assert values['Дата народження'] == ''


def test_form_is_one_page_per_trainer_in_request_order(app):
    first = _profiled_trainer('Перший Т.')
    second = _profiled_trainer('Другий Т.')
    pages = rs.build_form(rs.load_trainers([second.id, first.id]), ['full_name'])
    names = [dict(page)['Прізвище, власне ім’я, по батькові (за наявності)']
             for page in pages]
    assert names == ['Другий Т.', 'Перший Т.']


def test_form_html_has_the_title_and_a_page_per_trainer(app):
    """HTML форми без WeasyPrint: заголовок форми й розрив сторінки між
    тренерами -- кожне резюме окремим аркушем пакета."""
    first = _profiled_trainer('Аркушевий А.')
    second = _profiled_trainer('Аркушевий Б.')
    with app.test_request_context():
        html = rs.render_form_html([first, second], ['full_name'])

    assert 'Резюме' in html and 'викладача/тренера' in html
    assert html.count('<section>') == 2
    assert 'page-break-after' in html or 'break-after' in html


def test_default_keys_cover_the_official_form(app):
    """За замовчуванням -- усе, з чого складається офіційна форма, інакше
    перше ж вивантаження дало б форму з порожніми «Засобами зв’язку»."""
    assert {'full_name', 'birth_date', 'email', 'phone', 'education',
            'workplace', 'professional_certificates',
            'position_titles'} <= set(rs.DEFAULT_KEYS)
