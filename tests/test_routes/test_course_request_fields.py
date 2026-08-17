"""Заявка з продажної форми: ім'я, канал зв'язку, згода.

Згода фіксується моментом (consent_at), а не галочкою: для згоди на обробку
даних важливо КОЛИ вона дана, і NULL чесно означає "згоди немає".
"""
from app.extensions import db
from app.models.course import Course
from app.models.course_request import CourseRequest


def _course(slug='req-course'):
    course = Course(slug=slug, title='Курс заявки', is_active=True)
    db.session.add(course)
    db.session.commit()
    return course


def _post(client, course, **overrides):
    data = {
        'email': 'lead@example.com',
        'name': 'Олена',
        'phone': '+380670000000',
        'messenger': 'telegram',
        'consent': '1',
        'message': 'Цікавить дата',
    }
    data.update(overrides)
    return client.post(f'/courses/{course.slug}/request', data=data,
                       follow_redirects=True)


def test_new_fields_are_saved(client):
    course = _course()
    assert _post(client, course).status_code == 200

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.name == 'Олена'
    assert req.messenger == 'telegram'
    assert req.consent_at is not None


def test_consent_absent_leaves_null(client):
    """Коротка форма запиту згоди не питає -- там лишається NULL."""
    course = _course('req-no-consent')
    _post(client, course, consent='')

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.consent_at is None


def test_unknown_messenger_is_dropped_not_fatal(client):
    """Чуже значення завалило б CHECK і втратило б заявку цілком."""
    course = _course('req-bad-messenger')
    assert _post(client, course, messenger='pigeon').status_code == 200

    req = CourseRequest.query.filter_by(course_id=course.id).one()
    assert req.messenger is None
    assert req.email == 'lead@example.com'


def test_messenger_choices_match_db_constraint(client):
    """Перелік у формі й CHECK у БД мають збігатися."""
    course = _course('req-choices')
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    for value, _label in CourseRequest.MESSENGERS:
        assert f'value="{value}"' in html, f'{value} немає у формі'
