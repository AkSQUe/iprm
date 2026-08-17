"""Локалізація публічного потоку тестування.

Тест проходять і російськомовні учасники, тож блюпринт мусить мати мовні
префікси, а нові рядки -- реальні переклади. Без цієї перевірки каталог легко
лишити з порожніми msgstr: сторінка тоді просто показує українську, і помітять
це не скоро.
"""
from datetime import datetime, timedelta, timezone
from itertools import count
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.user import User

_event_numbers = count(5000000)

FULL_PROFILE = {
    'participant_type': 'doctor', 'middle_name': 'Іванович',
    'birth_date': datetime(1985, 3, 12).date(), 'education': '2010, НМУ',
    'workplace': 'Клініка', 'position': 'лікар', 'specializations': ['therapy'],
}


@pytest.fixture
def ready_registration(app):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    db.session.flush()

    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'ql-{uuid4().hex[:6]}',
        is_active=True, event_type='course', cpd_points=12,
        bpr_event_number=str(next(_event_numbers)),
    )
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        start_date=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.session.add(inst)
    db.session.flush()

    quiz = CourseQuiz(course_id=course.id, questions_per_attempt=2,
                      passing_score=2, is_active=True, shuffle_answers=False)
    db.session.add(quiz)
    db.session.flush()
    for i in range(2):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': f'Варіант {j + 1}', 'is_correct': j == 0}
                     for j in range(4)]))

    user = User.create_with_password(
        f'ql-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Іван', last_name='Тестовий', email_confirmed=True)
    db.session.flush()
    profile = user.medical_profile or MedicalProfile(user_id=user.id)
    for field, value in FULL_PROFILE.items():
        setattr(profile, field, value)
    user.medical_profile = profile
    db.session.add(profile)
    db.session.flush()

    reg = EventRegistration(
        user_id=user.id, instance_id=inst.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='confirmed',
        payment_status='paid')
    db.session.add(reg)
    db.session.flush()
    return reg


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_quiz_urls_have_language_prefixes(client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)
    for prefix in ('', '/ru', '/en'):
        assert client.get(f'{prefix}/quiz/{reg.id}').status_code == 200, prefix


def test_uk_prefix_redirects_to_canonical(client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)
    resp = client.get(f'/uk/quiz/{reg.id}')
    assert resp.status_code == 301
    assert f'/quiz/{reg.id}' in resp.headers['Location']


def test_start_page_is_translated(get_localized, client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)

    uk = get_localized(f'/quiz/{reg.id}').get_data(as_text=True)
    ru = get_localized(f'/ru/quiz/{reg.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/{reg.id}').get_data(as_text=True)

    # Напис на кнопці підтверджує звірені дані анкети, тож він довший за просте
    # «Почати тест» (те лишається для випадку, коли зведення показати нічим).
    assert 'Дані правильні, почати тест' in uk
    assert 'Данные верны, начать тест' in ru
    assert 'Details are correct, start the test' in en


def test_certificate_data_block_is_translated(get_localized, client,
                                              ready_registration):
    """Підписи полів анкети живуть у сервісі, а не в шаблоні -- їх легко
    забути обгорнути в `_()`, і тоді ru/en побачили б українські назви."""
    reg = ready_registration
    _login(client, reg.user)

    ru = get_localized(f'/ru/quiz/{reg.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/{reg.id}').get_data(as_text=True)

    assert 'Данные для сертификата' in ru
    assert 'Место работы' in ru
    assert 'Certificate details' in en
    assert 'Place of work' in en


def test_deadline_line_is_translated(get_localized, client, ready_registration):
    from app.services import quiz_service

    reg = ready_registration
    reg.instance.end_date = datetime.now(timezone.utc) - timedelta(hours=1)
    quiz = quiz_service.resolve_quiz(reg.instance)
    quiz.deadline_days_after_end = 2
    db.session.flush()
    _login(client, reg.user)

    ru = get_localized(f'/ru/quiz/{reg.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/{reg.id}').get_data(as_text=True)

    assert 'Пройти можно до' in ru
    assert 'You can take the test until' in en


def test_terms_with_placeholders_are_translated(get_localized, client,
                                                ready_registration):
    """Рядки з %(count)s легко лишити неперекладеними -- вони найдовші."""
    reg = ready_registration
    _login(client, reg.user)

    ru = get_localized(f'/ru/quiz/{reg.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/{reg.id}').get_data(as_text=True)

    assert 'вопросов, нужно правильных' in ru
    assert 'correct answers required' in en
    assert 'Попыток осталось' in ru
    assert 'Attempts left' in en


def test_question_page_is_translated(get_localized, client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    from app.models.quiz_attempt import QuizAttempt
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    ru = get_localized(f'/ru/quiz/attempt/{attempt.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/attempt/{attempt.id}').get_data(as_text=True)

    assert 'Вопрос 1 из 2' in ru
    assert 'Question 1 of 2' in en


def test_blocked_state_is_translated(get_localized, client, ready_registration):
    reg = ready_registration
    reg.payment_status = 'unpaid'
    db.session.flush()
    _login(client, reg.user)

    ru = get_localized(f'/ru/quiz/{reg.id}').get_data(as_text=True)
    en = get_localized(f'/en/quiz/{reg.id}').get_data(as_text=True)

    assert 'после оплаты участия' in ru
    assert 'once your participation is paid' in en


def test_question_content_uses_translations(get_localized, client,
                                            ready_registration):
    """Самі питання перекладаються через TranslatableMixin, а не каталог."""
    reg = ready_registration
    from app.models.quiz_attempt import QuizAttempt

    quiz = CourseQuiz.query.filter_by(
        course_id=reg.instance.course_id).one()
    for question in quiz.questions:
        question.set_translation('en', 'text', f'EN {question.text}')
        question.set_translation('en', 'answers', {'0.text': 'EN option one'})
    db.session.flush()

    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()

    en = get_localized(f'/en/quiz/attempt/{attempt.id}').get_data(as_text=True)
    assert 'EN Питання' in en
    assert 'EN option one' in en


# ---- захист від fuzzy-підстановок -------------------------------------------
#
# `pybabel update` копіює новому msgid переклад найсхожішого наявного і ставить
# `#, fuzzy`. Схожість -- за difflib, тож результат буває абсурдним: «Пройти
# тестування» отримало «Sorting», «Продовжити тестування» -- «Continue with
# Apple». Компіляція fuzzy пропускає, тож сторінка тихо падає на українську.
# Ці перевірки ловлять і те, і те: якщо запис знову стане fuzzy або втратить
# переклад, у HTML буде українська і тест впаде.

def test_result_page_is_translated(get_localized, client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)
    client.post(f'/quiz/{reg.id}/start')
    from app.models.course_quiz import QuizQuestion
    from app.models.quiz_attempt import QuizAttempt
    attempt = QuizAttempt.query.filter_by(registration_id=reg.id).one()
    for position, question_id in enumerate(attempt.question_ids):
        question = db.session.get(QuizQuestion, question_id)
        order = attempt.ordered_answer_indexes(question_id)
        client.post(f'/quiz/attempt/{attempt.id}/answer', data={
            'position': str(position), 'question_id': str(question_id),
            'choice': str(order.index(question.correct_index)),
            'direction': 'next',
        })

    ru = get_localized(f'/ru/quiz/attempt/{attempt.id}/review').get_data(as_text=True)
    en = get_localized(f'/en/quiz/attempt/{attempt.id}/review').get_data(as_text=True)
    assert 'Проверка ответов' in ru
    assert 'Check your answers' in en
    assert 'Завершить тест' in ru
    assert 'Finish the test' in en


def test_cabinet_quiz_cta_is_translated(get_localized, client, ready_registration):
    reg = ready_registration
    _login(client, reg.user)

    ru = get_localized('/ru/auth/account').get_data(as_text=True)
    en = get_localized('/en/auth/account').get_data(as_text=True)
    assert 'Пройти тестирование' in ru
    assert 'Take the test' in en


def test_quiz_messages_have_translations(app):
    """Рядки тестування присутні в каталогах і не порожні.

    Fuzzy-прапорці стережеться окремо й для всього каталогу --
    `test_translation_hardening.test_catalogs_have_no_fuzzy_entries`. Тут -- саме
    наявність перекладу для сторінок, які рендер-тестами вище не покриті
    (привітання після успіху, стани в кабінеті).
    """
    from babel.messages.pofile import read_po

    watched = {
        'Пройти тестування', 'Продовжити тестування', 'Тестування складено',
        'Вітаємо!', 'Номер сертифіката', 'Завантажити сертифікат (PDF)',
        'Спроби тестування вичерпано',
        'Заповніть анкету, щоб пройти тестування',
        'Анкета та тестування',
    }
    for lang in ('ru', 'en'):
        path = f'app/translations/{lang}/LC_MESSAGES/messages.po'
        with open(path, encoding='utf-8') as fh:
            catalog = read_po(fh)
        for msgid in watched:
            message = catalog.get(msgid)
            assert message is not None, f'{lang}: немає msgid {msgid!r}'
            assert message.string, f'{lang}: немає перекладу для {msgid!r}'
