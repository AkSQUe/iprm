"""AggregateRating будується лише з реальних опублікованих відгуків.

Раунд 1 фіксу (аудит): AggregateRating рахується ОКРЕМИМ SQL-запитом
(COUNT/AVG) за ВСІМА опублікованими живими відгуками курсу, а не з
обрізаного до 6 списку, що йде на відображення карток -- інакше
керований адміном sort_order міг би "закріпити" 5.0, приховавши решту
відгуків від Google. Тести нижче доводять і саму цю поведінку (Клас
TestAggregateBeyondDisplayLimit), і ряд негативних сценаріїв, які мали
нуль покриття до цього раунду: онлайн-курс, м'яке видалення,
крос-курсове протікання, загальний відгук без прив'язки.
"""
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.online_course import OnlineCourse
from app.models.review import Review
from tests.test_seo.helpers import jsonld_blocks


def _course(**kwargs):
    kwargs.setdefault('title', 'Курс')
    kwargs.setdefault('slug', f'ar-{uuid4().hex[:8]}')
    kwargs.setdefault('is_active', True)
    course = Course(**kwargs)
    db.session.add(course)
    db.session.flush()
    return course


def _online_course(**kwargs):
    kwargs.setdefault('sintegrum_id', int(uuid4().int % 10_000_000))
    kwargs.setdefault('remote_name', 'Онлайн-курс')
    kwargs.setdefault('slug', f'ar-online-{uuid4().hex[:8]}')
    kwargs.setdefault('is_published', True)
    kwargs.setdefault('is_vanished', False)
    course = OnlineCourse(**kwargs)
    db.session.add(course)
    db.session.flush()
    return course


def _course_schema(html):
    for block in jsonld_blocks(html):
        if block.get('@type') == 'Course':
            return block
    raise AssertionError('Course-схеми на сторінці немає')


@pytest.fixture
def course_without_reviews(app):
    return _course(title='Курс без відгуків')


@pytest.fixture
def course_with_reviews(app):
    course = _course(title='Курс з відгуками')
    db.session.add_all([
        Review(author_name='А', text='Добре', rating=5,
               is_published=True, course_id=course.id),
        Review(author_name='Б', text='Норм', rating=3,
               is_published=True, course_id=course.id),
        # Неопублікований у розрахунок НЕ входить.
        Review(author_name='В', text='Чернетка', rating=1,
               is_published=False, course_id=course.id),
    ])
    db.session.flush()
    return course


class TestAggregateRating:
    def test_absent_without_reviews(self, client, course_without_reviews):
        resp = client.get(f'/courses/{course_without_reviews.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema
        assert 'review' not in schema

    def test_built_from_published_reviews_only(self, client, course_with_reviews):
        resp = client.get(f'/courses/{course_with_reviews.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        rating = schema['aggregateRating']
        assert rating['@type'] == 'AggregateRating'
        # Середнє (5 + 3) / 2 = 4; чернетка з rating=1 не враховується.
        assert float(rating['ratingValue']) == 4.0
        assert int(rating['reviewCount']) == 2
        assert len(schema['review']) == 2

        # datePublished -- реальна ISO-дата зі created_at рядка, а не
        # вигадане значення.
        alive_published = Review.alive().filter_by(
            course_id=course_with_reviews.id, is_published=True,
        ).all()
        expected_dates = {r.created_at.date().isoformat() for r in alive_published}
        for node in schema['review']:
            assert node['datePublished'] in expected_dates


class TestOnlineCourseAggregateRating:
    """Онлайн-сторінка мала нульове покриття -- саме тут виклик
    apply_rating мовчки перестав би виконуватись, якби голий {{ }} колись
    опинився поза блоком jsonld (як на очному курсі)."""

    def test_present_with_published_reviews(self, client, app):
        course = _online_course()
        db.session.add_all([
            Review(author_name='О1', text='Дуже допомогло', rating=5,
                   is_published=True, online_course_id=course.id),
            Review(author_name='О2', text='Було корисно', rating=4,
                   is_published=True, online_course_id=course.id),
        ])
        db.session.flush()

        resp = client.get(f'/online-courses/{course.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        rating = schema['aggregateRating']
        assert float(rating['ratingValue']) == 4.5
        assert int(rating['reviewCount']) == 2
        assert len(schema['review']) == 2

    def test_absent_without_reviews(self, client, app):
        course = _online_course()
        resp = client.get(f'/online-courses/{course.slug}')
        assert resp.status_code == 200
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema
        assert 'review' not in schema


class TestExclusionsAndScoping:
    """Негативні сценарії: усе, що НЕ мусить впливати на рейтинг курсу."""

    def test_soft_deleted_review_excluded_from_count_and_average(self, client, app):
        course = _course(title='Курс з видаленим відгуком')
        alive = Review(author_name='Жива', text='Ок', rating=4,
                        is_published=True, course_id=course.id)
        removed = Review(author_name='Видалена', text='Не має рахуватись',
                          rating=1, is_published=True, course_id=course.id)
        db.session.add_all([alive, removed])
        db.session.flush()
        # Це саме сценарій, що вже раз регресив у репо (commit add4356:
        # Review.query замість Review.alive()).
        removed.deleted_at = datetime.now(timezone.utc)
        db.session.flush()

        resp = client.get(f'/courses/{course.slug}')
        schema = _course_schema(resp.data.decode('utf-8'))
        rating = schema['aggregateRating']
        assert int(rating['reviewCount']) == 1
        assert float(rating['ratingValue']) == 4.0
        assert len(schema['review']) == 1

    def test_review_on_another_course_does_not_leak(self, client, app):
        course_a = _course(title='Курс А')
        course_b = _course(title='Курс Б')
        db.session.add(Review(
            author_name='Чужий', text='Про інший курс', rating=5,
            is_published=True, course_id=course_b.id,
        ))
        db.session.flush()

        resp = client.get(f'/courses/{course_a.slug}')
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema
        assert 'review' not in schema

    def test_online_review_does_not_leak_to_offline_course(self, client, app):
        offline = _course(title='Очний курс')
        online = _online_course()
        db.session.add(Review(
            author_name='Онлайновий', text='Про онлайн-курс', rating=5,
            is_published=True, online_course_id=online.id,
        ))
        db.session.flush()

        resp = client.get(f'/courses/{offline.slug}')
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema

    def test_offline_review_does_not_leak_to_online_course(self, client, app):
        offline = _course(title='Очний курс 2')
        online = _online_course()
        db.session.add(Review(
            author_name='Очний', text='Про очний курс', rating=5,
            is_published=True, course_id=offline.id,
        ))
        db.session.flush()

        resp = client.get(f'/online-courses/{online.slug}')
        schema = _course_schema(resp.data.decode('utf-8'))
        assert 'aggregateRating' not in schema

    def test_general_review_without_any_fk_appears_on_no_course_page(self, client, app):
        """Відгук про Інститут загалом (обидва FK NULL) -- штатний випадок
        за докстрінгом моделі, і жодній сторінці курсу він не належить."""
        offline = _course(title='Курс без прив\'язаного відгуку')
        online = _online_course()
        db.session.add(Review(
            author_name='Загальний', text='Про Інститут загалом', rating=5,
            is_published=True,
        ))
        db.session.flush()

        resp_offline = client.get(f'/courses/{offline.slug}')
        schema_offline = _course_schema(resp_offline.data.decode('utf-8'))
        assert 'aggregateRating' not in schema_offline

        resp_online = client.get(f'/online-courses/{online.slug}')
        schema_online = _course_schema(resp_online.data.decode('utf-8'))
        assert 'aggregateRating' not in schema_online


class TestAggregateBeyondDisplayLimit:
    """Головна поведінка раунду 1: середнє й кількість -- за ВСІМА
    опублікованими відгуками, а не лише за шістьма показаними."""

    def test_true_total_and_average_beyond_display_limit(self, client, app):
        course = _course(title='Курс з багатьма відгуками')
        reviews = [
            Review(author_name=f'Задоволений {i}', text='Чудово', rating=5,
                   is_published=True, course_id=course.id, sort_order=i)
            for i in range(6)
        ] + [
            Review(author_name=f'Незадоволений {i}', text='Погано', rating=1,
                   is_published=True, course_id=course.id, sort_order=100 + i)
            for i in range(2)
        ]
        db.session.add_all(reviews)
        db.session.flush()

        resp = client.get(f'/courses/{course.slug}')
        schema = _course_schema(resp.data.decode('utf-8'))
        rating = schema['aggregateRating']
        # (6*5 + 2*1) / 8 = 4.0 -- істинне середнє за ВСІМА 8 відгуками,
        # а не лише за шістьма, що йдуть на відображення карток.
        assert float(rating['ratingValue']) == 4.0
        assert int(rating['reviewCount']) == 8
        # Масив review -- рівно те, що бачить відвідувач: перші 6 за
        # sort_order (усі п'ятизіркові -- двозіркові мають вищий sort_order
        # і на сторінку не потрапляють).
        assert len(schema['review']) == 6
        assert all(
            node['reviewRating']['ratingValue'] == 5 for node in schema['review']
        )
