"""Тести синхронізації каталогу онлайн-курсів із Sintegrum.

Клієнт підмінюється цілком: перевіряємо поведінку дзеркала, а не HTTP
(транспорт покритий у test_sintegrum_client.py).
"""
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.online_course import OnlineCourse
from app.models.site_settings import SiteSettings
from app.services import online_course_sync as sync_mod
from app.services.online_course_sync import (
    STATUS_DISABLED, STATUS_ERROR, STATUS_OK, sync_courses,
)
from app.services.sintegrum_client import SintegrumResult


def _course(course_id, name='Плазмотерапія', **extra):
    data = {
        'id': course_id, 'name': name, 'description': 'Опис курсу',
        'price': 4500, 'status': 1, 'parent_id': None,
    }
    data.update(extra)
    return data


@pytest.fixture(autouse=True)
def clean_mirror(app):
    """Чисте дзеркало перед кожним тестом.

    sync_courses комітить (інакше фонова джоба нічого б не зберегла), тож
    рядки переживають відкат тестової транзакції -- рівно як сертифікати в
    тестах quiz_service. Прибираємо явно, щоб лічильники в перевірках
    означали саме те, що написано.
    """
    OnlineCourse.query.delete()
    db.session.commit()
    yield
    OnlineCourse.query.delete()
    db.session.commit()


@pytest.fixture
def configured(app):
    settings = SiteSettings.get()
    settings.sintegrum_enabled = True
    settings.sintegrum_api_base_url = 'https://api.sintegrum.com'
    settings.sintegrum_company_alias = 'multimededu'
    settings.sintegrum_api_key = 'key'
    db.session.flush()
    return settings


def _feed(monkeypatch, payloads=None, result=None):
    """Підмінити клієнта так, щоб list_all_courses віддав задане."""
    class _Client:
        company = 'multimededu'

        def list_all_courses(self):
            return result or SintegrumResult(ok=True, http_status=200, data=payloads or [])

    monkeypatch.setattr(
        sync_mod.SintegrumClient, 'from_settings',
        classmethod(lambda cls, settings: _Client()),
    )


# ----------------------------- базовий цикл -----------------------------

def test_first_run_creates_drafts(configured, monkeypatch):
    _feed(monkeypatch, [_course(1), _course(2, name='Ботулінотерапія')])
    report = sync_courses()

    assert report.ok
    assert report.created == 2
    courses = OnlineCourse.query.order_by(OnlineCourse.sintegrum_id).all()
    assert [c.sintegrum_id for c in courses] == [1, 2]
    # Нові курси не публікуються самі -- для продажу бракує ціни й посилання.
    assert all(c.is_published is False for c in courses)
    assert all(c.slug for c in courses)
    assert courses[0].remote_price == Decimal('4500')
    assert courses[0].first_seen_at is not None


def test_second_run_does_not_duplicate(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()
    report = sync_courses()

    assert report.created == 0
    assert OnlineCourse.query.count() == 1


def test_remote_change_is_picked_up(configured, monkeypatch):
    _feed(monkeypatch, [_course(1, price=4500)])
    sync_courses()

    _feed(monkeypatch, [_course(1, price=5200, name='Плазмотерапія 2.0')])
    report = sync_courses()

    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
    assert report.updated == 1
    assert course.remote_price == Decimal('5200')
    assert course.remote_name == 'Плазмотерапія 2.0'


# ----------------------------- захист локальних полів -----------------------------

def test_local_fields_survive_sync(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()

    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
    course.title = 'Наша назва'
    course.description = 'Наш маркетинговий опис'
    course.price = Decimal('6000')
    course.access_url = 'https://multimededu.sintegrum.com/register/abc'
    course.slug = 'nasha-nazva'
    course.is_published = True
    course.sort_order = 5
    db.session.flush()

    _feed(monkeypatch, [_course(1, name='Змінена назва', price=100)])
    sync_courses()

    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
    assert course.title == 'Наша назва'
    assert course.description == 'Наш маркетинговий опис'
    assert course.price == Decimal('6000')
    assert course.access_url == 'https://multimededu.sintegrum.com/register/abc'
    assert course.slug == 'nasha-nazva'
    assert course.is_published is True
    assert course.sort_order == 5
    # А ось дані Sintegrum оновились.
    assert course.remote_name == 'Змінена назва'
    assert course.remote_price == Decimal('100')


def test_effective_values_prefer_our_texts(configured, monkeypatch):
    _feed(monkeypatch, [_course(1, name='Remote', description='Remote опис')])
    sync_courses()
    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

    assert course.effective_title == 'Remote'
    course.title = 'Наша'
    assert course.effective_title == 'Наша'
    assert course.effective_description == 'Remote опис'


# ----------------------------- зниклі курси -----------------------------

def test_missing_course_is_marked_vanished_not_deleted(configured, monkeypatch):
    _feed(monkeypatch, [_course(1), _course(2)])
    sync_courses()

    _feed(monkeypatch, [_course(1)])
    report = sync_courses()

    assert report.vanished == 1
    assert OnlineCourse.query.count() == 2
    assert OnlineCourse.query.filter_by(sintegrum_id=2).one().is_vanished is True


def test_returning_course_clears_the_flag(configured, monkeypatch):
    _feed(monkeypatch, [_course(1), _course(2)])
    sync_courses()
    _feed(monkeypatch, [_course(1)])
    sync_courses()

    _feed(monkeypatch, [_course(1), _course(2)])
    report = sync_courses()

    assert report.restored == 1
    assert OnlineCourse.query.filter_by(sintegrum_id=2).one().is_vanished is False


def test_empty_feed_does_not_hide_everything(configured, monkeypatch):
    """Порожня видача майже завжди означає проблему на тому боці."""
    _feed(monkeypatch, [_course(1), _course(2)])
    sync_courses()

    _feed(monkeypatch, [])
    report = sync_courses()

    assert report.vanished == 0
    assert OnlineCourse.query.filter_by(is_vanished=True).count() == 0


# ----------------------------- збої -----------------------------

def test_api_failure_leaves_mirror_untouched(configured, monkeypatch):
    _feed(monkeypatch, [_course(1), _course(2)])
    sync_courses()

    _feed(monkeypatch, result=SintegrumResult(ok=False, http_status=500, error='Sintegrum 500'))
    report = sync_courses()

    assert report.status == STATUS_ERROR
    assert OnlineCourse.query.count() == 2
    assert OnlineCourse.query.filter_by(is_vanished=True).count() == 0
    settings = SiteSettings.get()
    assert settings.sintegrum_last_sync_status == STATUS_ERROR
    assert 'Sintegrum 500' in settings.sintegrum_last_sync_error


def test_disabled_integration_reports_and_does_nothing(app, monkeypatch):
    settings = SiteSettings.get()
    settings.sintegrum_enabled = False
    db.session.flush()

    report = sync_courses()

    assert report.status == STATUS_DISABLED
    assert OnlineCourse.query.count() == 0


def test_malformed_entries_are_skipped_not_fatal(configured, monkeypatch):
    _feed(monkeypatch, [
        _course(1),
        {'id': None, 'name': 'Без id'},
        {'id': 9, 'name': ''},
        'не словник',
    ])
    report = sync_courses()

    assert report.ok
    assert report.created == 1
    assert OnlineCourse.query.count() == 1


def test_successful_run_records_status(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()

    settings = SiteSettings.get()
    assert settings.sintegrum_last_sync_status == STATUS_OK
    assert settings.sintegrum_last_sync_at is not None
    assert settings.sintegrum_last_sync_error == ''


# ----------------------------- slug -----------------------------

def test_slug_collision_gets_suffix(configured, monkeypatch):
    _feed(monkeypatch, [_course(1, name='Плазмотерапія'), _course(2, name='Плазмотерапія')])
    sync_courses()

    slugs = sorted(c.slug for c in OnlineCourse.query.all())
    assert len(set(slugs)) == 2
    assert slugs[0] and slugs[1].endswith('-2')


def test_slug_is_transliterated(configured, monkeypatch):
    _feed(monkeypatch, [_course(1, name='Плазмотерапія в косметології')])
    sync_courses()

    slug = OnlineCourse.query.filter_by(sintegrum_id=1).one().slug
    assert slug.isascii()
    assert ' ' not in slug


# ----------------------------- готовність до продажу -----------------------------

def test_publication_requires_price_and_access_url(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()
    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

    assert course.can_be_published is False
    assert 'ціна' in course.missing_for_publication
    assert 'посилання на навчання' in course.missing_for_publication

    course.price = Decimal('4500')
    course.access_url = 'https://multimededu.sintegrum.com/register/abc'
    assert course.can_be_published is True

    course.is_vanished = True
    assert course.can_be_published is False


def test_purchasable_requires_publication(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()
    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
    course.price = Decimal('4500')
    course.access_url = 'https://x/register'

    assert course.is_purchasable is False
    course.is_published = True
    assert course.is_purchasable is True


# ----------------------------- періодичність джоби -----------------------------

def test_sync_is_due_when_never_run(configured):
    from app.services.scheduler_service import sintegrum_sync_is_due

    configured.sintegrum_last_sync_at = None
    assert sintegrum_sync_is_due() is True


def test_sync_is_not_due_before_interval(configured):
    from datetime import datetime, timedelta, timezone
    from app.services.scheduler_service import sintegrum_sync_is_due

    now = datetime.now(timezone.utc)
    configured.sintegrum_sync_interval_minutes = 60
    configured.sintegrum_last_sync_at = now - timedelta(minutes=30)
    assert sintegrum_sync_is_due(now=now) is False

    configured.sintegrum_last_sync_at = now - timedelta(minutes=61)
    assert sintegrum_sync_is_due(now=now) is True


def test_sync_is_never_due_when_disabled(app):
    from app.services.scheduler_service import sintegrum_sync_is_due

    settings = SiteSettings.get()
    settings.sintegrum_enabled = False
    settings.sintegrum_last_sync_at = None
    db.session.flush()
    assert sintegrum_sync_is_due() is False
