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

def test_publication_requires_a_price(configured, monkeypatch):
    """Посилання не потрібне: доступ відкривається через API."""
    _feed(monkeypatch, [_course(1, price=None)])
    sync_courses()
    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

    assert course.can_be_published is False
    assert 'ціна' in course.missing_for_publication

    # Ціна з Sintegrum достатня -- своя не обов'язкова.
    course.remote_price = Decimal('3500')
    assert course.can_be_published is True

    course.is_vanished = True
    assert course.can_be_published is False


def test_purchasable_requires_publication(configured, monkeypatch):
    _feed(monkeypatch, [_course(1)])
    sync_courses()
    course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
    course.price = Decimal('4500')

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


# ----------------------------- опис із чужої системи -----------------------------

class TestRemoteHtml:
    """Sintegrum віддає опис розміткою свого редактора.

    Три речі, які тут стережуться: чужий скрипт не потрапляє на сторінку,
    чужі кольори не ламають темну тему, а теги не показуються як текст.
    """

    SAMPLE = (
        '<p id="isPasted">Курс для лікарів.&nbsp;<br>&nbsp;</p>'
        '<p><span style="color: rgb(0, 0, 0);">Знання основ.</span></p>'
        '<ul><li><strong>Практика</strong></li></ul>'
        '<p></p>'
    )

    def test_script_is_removed(self):
        from app.services.remote_html import clean_html

        dirty = '<p>Опис</p><script>alert(1)</script>'
        cleaned = clean_html(dirty)

        assert '<script' not in cleaned
        assert 'alert(1)' not in cleaned
        assert 'Опис' in cleaned

    def test_inline_styles_are_stripped(self):
        """`color: rgb(0, 0, 0)` у темній темі -- чорний текст на темному."""
        from app.services.remote_html import clean_html

        cleaned = clean_html(self.SAMPLE)

        assert 'style=' not in cleaned
        assert 'rgb(0, 0, 0)' not in cleaned

    def test_formatting_survives(self):
        from app.services.remote_html import clean_html

        cleaned = clean_html(self.SAMPLE)

        assert '<ul>' in cleaned and '<li>' in cleaned
        assert '<strong>' in cleaned
        assert 'Курс для лікарів' in cleaned

    def test_empty_paragraphs_are_dropped(self):
        from app.services.remote_html import clean_html

        cleaned = clean_html(self.SAMPLE)
        assert '<p></p>' not in cleaned

    def test_to_text_strips_everything(self):
        from app.services.remote_html import to_text

        text = to_text(self.SAMPLE)

        assert '<' not in text
        assert 'Курс для лікарів' in text
        # Нерозривні пробіли чужого редактора не лишають рваних дір.
        assert '\xa0' not in text
        assert '  ' not in text

    def test_empty_input_gives_empty_string(self):
        from app.services.remote_html import clean_html, to_text

        assert clean_html(None) == ''
        assert to_text(None) == ''


class TestDescriptionForDisplay:
    def test_remote_html_is_cleaned(self, configured, monkeypatch):
        _feed(monkeypatch, [_course(
            1, description='<p>Опис</p><script>alert(1)</script>')])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        assert '<script' not in course.remote_description_html
        assert '<p>Опис</p>' in course.remote_description_html

    def test_our_plain_text_becomes_paragraph_breaks(self, configured, monkeypatch):
        _feed(monkeypatch, [_course(1)])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
        course.description = 'Рядок один\nРядок два'

        assert str(course.description_html) == 'Рядок один<br>Рядок два'

    def test_script_in_our_field_never_goes_live(self, configured, monkeypatch):
        """Наш опис теж чиститься: адмінка не є приводом довіряти розмітці."""
        _feed(monkeypatch, [_course(1)])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
        course.description = '<p>Опис</p><script>alert(1)</script>'

        rendered = str(course.description_html)
        assert '<script' not in rendered
        assert 'alert(1)' not in rendered
        assert '<p>Опис</p>' in rendered

    def test_plain_text_with_angle_brackets_is_escaped(self, configured, monkeypatch):
        """Текст без розмітки лишається текстом, а не стає тегами."""
        _feed(monkeypatch, [_course(1)])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()
        course.description = 'Ціна < 5000 грн'

        assert '&lt; 5000' in str(course.description_html)

    def test_short_description_falls_back_to_remote_text(self, configured, monkeypatch):
        _feed(monkeypatch, [_course(1, description='<p>Довгий опис курсу</p>')])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        assert course.effective_short_description == 'Довгий опис курсу'


# --------------------------- обкладинки з фіду ---------------------------

class TestCovers:
    """`avatar_link` із фіду -> MediaFile у нашому реєстрі.

    Мережа підміняється цілком: перевіряємо рішення (тягнути / не тягнути /
    не перезаписати руками поставлене), а не HTTP.
    """

    LINK = 'https://fs1.sintegrum.com/api/v1/files/TOKEN1'
    LINK2 = 'https://fs1.sintegrum.com/api/v1/files/TOKEN2'

    @pytest.fixture
    def media_root(self, app):
        import tempfile
        prev = app.config.get('MEDIA_FOLDER')
        app.config['MEDIA_FOLDER'] = tempfile.mkdtemp()
        yield app.config['MEDIA_FOLDER']
        app.config['MEDIA_FOLDER'] = prev

    @staticmethod
    def _jpeg(color=(120, 80, 160)):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', (1280, 762), color).save(buf, 'JPEG')
        return buf.getvalue()

    def _network(self, monkeypatch, body=None, status=200, ctype='image/jpeg'):
        """Підмінити requests.get у сервісі обкладинок. Повертає лічильник."""
        from app.services import online_course_media as media_mod

        calls = []
        payload = body if body is not None else self._jpeg()

        class _Response:
            status_code = status
            headers = {'Content-Type': ctype}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def iter_content(self, chunk_size):
                yield payload

        def _get(url, **kwargs):
            calls.append(url)
            return _Response()

        monkeypatch.setattr(media_mod.requests, 'get', _get)
        return calls

    def test_cover_is_ingested_into_media_registry(self, configured, monkeypatch, media_root):
        calls = self._network(monkeypatch)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK)])

        report = sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        assert report.covers == 1
        assert calls == [self.LINK]
        assert course.card_media_id is not None
        assert course.card_avatar_src == self.LINK
        # Показуємо своїм WebP-варіантом, а не чужим посиланням.
        assert course.card_src.startswith('/media/')
        assert course.card_src.endswith('.webp')
        assert course.card_media.entity_type == 'online_course'
        assert course.card_media.usage_type == 'card'

    def test_second_run_does_not_refetch(self, configured, monkeypatch, media_root):
        self._network(monkeypatch)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK)])
        sync_courses()

        calls = self._network(monkeypatch)
        report = sync_courses()

        assert calls == []
        assert report.covers == 0

    def test_changed_link_replaces_the_cover(self, configured, monkeypatch, media_root):
        from app.models.media_file import MediaFile

        self._network(monkeypatch)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK)])
        sync_courses()
        first_id = OnlineCourse.query.filter_by(sintegrum_id=1).one().card_media_id

        self._network(monkeypatch)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK2)])
        report = sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        assert report.covers == 1
        assert course.card_media_id != first_id
        assert course.card_avatar_src == self.LINK2
        # Стару НАШУ копію прибираємо, інакше реєстр заростає сиротами.
        assert db.session.get(MediaFile, first_id) is None

    def test_manual_image_is_never_overwritten(self, configured, monkeypatch, media_root):
        """Картинка, поставлена людиною (без мітки), лишається на місці."""
        self._network(monkeypatch)
        _feed(monkeypatch, [_course(1)])
        sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        import io
        from PIL import Image
        from werkzeug.datastructures import FileStorage

        from app.services import media_service
        buf = io.BytesIO()
        Image.new('RGB', (800, 480), (10, 200, 90)).save(buf, 'PNG')
        buf.seek(0)
        media, err = media_service.create_from_upload(
            FileStorage(stream=buf, filename='manual.png', content_type='image/png'),
            entity_type='online_course', entity_id=course.id, usage_type='card',
        )
        assert err is None
        course.card_media_id = media.id
        course.card_avatar_src = None
        db.session.commit()

        calls = self._network(monkeypatch)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK)])
        report = sync_courses()
        course = OnlineCourse.query.filter_by(sintegrum_id=1).one()

        assert calls == []
        assert report.covers == 0
        assert course.card_media_id == media.id

    def test_broken_download_does_not_break_the_sync(self, configured, monkeypatch, media_root):
        self._network(monkeypatch, status=500)
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK), _course(2)])

        report = sync_courses()

        assert report.ok
        assert report.created == 2
        assert report.covers == 0
        assert OnlineCourse.query.filter_by(sintegrum_id=1).one().card_media_id is None

    def test_non_image_response_is_rejected(self, configured, monkeypatch, media_root):
        self._network(monkeypatch, body=b'<html>login</html>', ctype='text/html')
        _feed(monkeypatch, [_course(1, avatar_link=self.LINK)])

        report = sync_courses()

        assert report.covers == 0
        assert OnlineCourse.query.filter_by(sintegrum_id=1).one().card_media_id is None

    def test_feed_without_avatar_link_is_fine(self, configured, monkeypatch, media_root):
        calls = self._network(monkeypatch)
        _feed(monkeypatch, [_course(1)])

        report = sync_courses()

        assert report.ok and report.covers == 0
        assert calls == []
