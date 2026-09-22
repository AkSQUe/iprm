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
