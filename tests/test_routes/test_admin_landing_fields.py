"""Адмінка продажної сторінки: збереження нових полів через POST форми.

Раніше ці поля перевірялись лише руками. Форма -- єдина точка входу для
контенту лендінгу, тож помилка в мапінгу тихо з'їдає введене: сторінка
просто не показує секцію, і це помічають не одразу.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.online_course import OnlineCourse
from app.models.user import User


@pytest.fixture
def admin_client(app, client):
    # Унікальний email на кожен тест: база живе через увесь модуль, і
    # фікстура з фіксованою адресою падала б на другому ж виклику.
    user = User.create_with_password(
        f'landing-admin-{uuid4().hex[:8]}@test.com', 'Passw0rd!123',
        first_name='Адмін', email_confirmed=True,
    )
    user.is_admin = True
    user.is_active = True
    db.session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    yield client
    # Прибираємо за собою: база живе через увесь прогін, і зайві користувачі
    # зсувають сторінку /api/v1/participants -- сусідній тест переставав
    # знаходити свого учасника у перших 200 рядках.
    db.session.delete(user)
    db.session.commit()


# --------------------------------------------------------- очний курс

def test_course_form_saves_landing_content(admin_client):
    slug = f'adm-course-{uuid4().hex[:8]}'
    course = Course(slug=slug, title='Курс', is_active=True,
                    event_type='course')
    db.session.add(course)
    db.session.commit()

    resp = admin_client.post(f'/admin/courses/{course.id}/edit', data={
        'title': 'Курс', 'slug': slug, 'event_type': 'course',
        'difficulty_level': '0', 'sort_order': '0', 'base_price': '0',
        'is_active': 'y',
        'proof_stats_text': '6+ | проведених груп\n100% | практика',
        'benefits_text': 'Перша\nТекст першої.\n\nДруга\nТекст другої.',
        'practice_note_title': 'Ви робите руками',
        'practice_note_text': 'Тренер контролює.',
        'gallery_intro': 'Як минає день',
    }, follow_redirects=True)
    assert resp.status_code == 200

    saved = db.session.get(Course, course.id)
    assert saved.proof_stats == [
        {'value': '6+', 'label': 'проведених груп'},
        {'value': '100%', 'label': 'практика'},
    ]
    assert saved.benefits == [
        {'title': 'Перша', 'text': 'Текст першої.'},
        {'title': 'Друга', 'text': 'Текст другої.'},
    ]
    assert saved.practice_note_title == 'Ви робите руками'
    assert saved.gallery_intro == 'Як минає день'


# ------------------------------------------------------- онлайн-курс

def _online():
    suffix = uuid4().hex[:8]
    course = OnlineCourse(sintegrum_id=int(suffix, 16) % 10**6,
                          remote_name='Remote', slug=f'adm-online-{suffix}',
                          price=Decimal('2500'))
    db.session.add(course)
    db.session.commit()
    return course


def test_online_form_saves_landing_content(admin_client):
    course = _online()

    resp = admin_client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug, 'price': '2500',
        'proof_stats_text': '500+ | випускників',
        'benefits_text': 'Картка\nТекст картки.',
        'target_audience_text': 'Лікарі\nКосметологи',
        'faq_text': 'Питання?\nВідповідь.',
        'practice_note_title': 'Практика',
        'final_cta_text': 'Почніть сьогодні',
    }, follow_redirects=True)
    assert resp.status_code == 200

    saved = db.session.get(OnlineCourse, course.id)
    assert saved.proof_stats == [{'value': '500+', 'label': 'випускників'}]
    assert saved.benefits == [{'title': 'Картка', 'text': 'Текст картки.'}]
    assert saved.target_audience == ['Лікарі', 'Косметологи']
    assert saved.faq == [{'question': 'Питання?', 'answer': 'Відповідь.'}]
    assert saved.final_cta_text == 'Почніть сьогодні'


def test_online_form_saves_program_block_translations(admin_client):
    """Форма офлайнового курсу зберігала переклади блоків, онлайнова -- ні:
    у роуті не було виклику, а в шаблоні -- полів."""
    course = _online()

    # Перший сабміт створює блок: id ще немає, тож і полів перекладу теж.
    admin_client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug, 'price': '2500',
        'block_0_heading': 'Теорія', 'block_0_items': 'Пункт А\nПункт Б',
    }, follow_redirects=True)

    course = db.session.get(OnlineCourse, course.id)
    assert len(course.program_blocks) == 1
    block = course.program_blocks[0]

    # Другий -- уже з перекладами.
    admin_client.post(f'/admin/online-courses/{course.id}', data={
        'slug': course.slug, 'price': '2500',
        'block_0_id': str(block.id),
        'block_0_heading': 'Теорія', 'block_0_items': 'Пункт А\nПункт Б',
        # Формат імені -- {prefix}__{lang}__{field} (див. _i18n_tabs.html).
        f'trblk__{block.id}__ru__heading': 'Теория',
        f'trblk__{block.id}__en__heading': 'Theory',
    }, follow_redirects=True)

    db.session.expire_all()
    block = db.session.get(OnlineCourse, course.id).program_blocks[0]
    assert block.t('heading', 'ru') == 'Теория'
    assert block.t('heading', 'en') == 'Theory'


# ------------------------------------------------------------ тарифи

def _instance_with_tariffs(count=2):
    course = Course(slug=f'adm-tariffs-{uuid4().hex[:8]}', title='Курс',
                    is_active=True)
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(course_id=course.id, status='published')
    db.session.add(instance)
    db.session.flush()
    tariffs = []
    for index in range(count):
        tariff = InstanceTariff(
            instance_id=instance.id, name=f'Тариф {index}',
            price=Decimal('1000'), sort_order=index,
        )
        db.session.add(tariff)
        tariffs.append(tariff)
    db.session.commit()
    return instance, tariffs


def test_featured_tariff_is_unique_per_instance(admin_client):
    """Дві золоті рамки поруч не підказують нічого, тож виділений -- один."""
    instance, (first, second) = _instance_with_tariffs()
    first.is_featured = True
    db.session.commit()

    admin_client.post(f'/admin/tariffs/{second.id}/edit', data={
        'name': 'Тариф 1', 'price': '1000', 'sort_order': '1',
        'is_active': 'y', 'is_featured': 'y',
    }, follow_redirects=True)

    db.session.expire_all()
    assert db.session.get(InstanceTariff, second.id).is_featured is True
    assert db.session.get(InstanceTariff, first.id).is_featured is False


def test_unfeaturing_leaves_others_alone(admin_client):
    """Знімаючи прапорець, не чіпаємо чужі -- інакше форма мовчки гасила б
    виділення сусіда."""
    instance, (first, second) = _instance_with_tariffs()
    first.is_featured = True
    db.session.commit()

    admin_client.post(f'/admin/tariffs/{second.id}/edit', data={
        'name': 'Тариф 1', 'price': '1000', 'sort_order': '1',
        'is_active': 'y',
    }, follow_redirects=True)

    db.session.expire_all()
    assert db.session.get(InstanceTariff, first.id).is_featured is True
