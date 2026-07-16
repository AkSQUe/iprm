"""Тести адмін-CRUD відгуків + публічного блоку на Головній."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.user import User
from app.models.review import Review


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'a-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='A', last_name='D', is_admin=True, email_confirmed=True,
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_reviews_list_and_create(client, admin):
    _login(client, admin)
    assert client.get('/admin/reviews').status_code == 200
    assert client.get('/admin/reviews/new').status_code == 200
    r = client.post('/admin/reviews/new', data={
        'author_name': 'Тест Автор', 'author_role': 'лікар', 'city': 'Київ',
        'text': 'Дуже корисний курс', 'rating': '5', 'sort_order': '0',
        'is_published': 'y',
    }, follow_redirects=True)
    assert r.status_code == 200
    rev = Review.query.filter_by(author_name='Тест Автор').first()
    assert rev is not None and rev.is_published and rev.rating == 5


def test_review_toggle_and_delete(client, admin):
    rev = Review(author_name='Тимч', text='текст', rating=4, is_published=True)
    db.session.add(rev)
    db.session.flush()
    _login(client, admin)
    client.post(f'/admin/reviews/{rev.id}/toggle')
    assert Review.query.get(rev.id).is_published is False
    client.post(f'/admin/reviews/{rev.id}/delete')
    assert Review.query.get(rev.id) is None


def test_home_shows_stub_without_reviews(client, db_session):
    # Прибираємо закомічені іншими тестами відгуки (спільна in-memory БД).
    Review.query.delete()
    db.session.commit()
    r = client.get('/')
    assert r.status_code == 200
    assert 'Олена · Київ'.encode() in r.data      # заглушка


def test_home_shows_published_review(client, db_session):
    db.session.add(Review(author_name='Реальний', text='Топ курс',
                          rating=5, is_published=True))
    db.session.flush()
    r = client.get('/')
    assert 'Реальний'.encode() in r.data
    assert 'Олена · Київ'.encode() not in r.data   # заглушка прихована


def test_review_linked_to_course_shows_on_course_page(client, db_session):
    from uuid import uuid4
    from app.models.course import Course
    course = Course(title='Курс Відгуків', slug=f'kv-{uuid4().hex[:6]}', is_active=True)
    db.session.add(course)
    db.session.flush()
    db.session.add(Review(author_name='Учасниця', text='Дуже сподобалось',
                          rating=5, is_published=True, course_id=course.id))
    # Неопублікований відгук того ж курсу -- не показуємо.
    db.session.add(Review(author_name='Прихований', text='чернетка',
                          rating=3, is_published=False, course_id=course.id))
    db.session.flush()
    r = client.get(f'/courses/{course.slug}')
    assert r.status_code == 200
    assert 'Учасниця'.encode() in r.data
    assert 'Прихований'.encode() not in r.data
