"""AggregateRating будується лише з реальних опублікованих відгуків."""
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.review import Review
from tests.test_seo.helpers import jsonld_blocks


@pytest.fixture
def course_without_reviews(app):
    course = Course(
        title='Курс без відгуків', slug=f'ar-none-{uuid4().hex[:6]}',
        is_active=True,
    )
    db.session.add(course)
    db.session.flush()
    return course


@pytest.fixture
def course_with_reviews(app):
    course = Course(
        title='Курс з відгуками', slug=f'ar-some-{uuid4().hex[:6]}',
        is_active=True,
    )
    db.session.add(course)
    db.session.flush()
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


def _course_schema(html):
    for block in jsonld_blocks(html):
        if block.get('@type') == 'Course':
            return block
    raise AssertionError('Course-схеми на сторінці немає')


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
