"""Прогін панелі фільтрів (filter_bar) на реєстрах, що досі жили без неї.

Файл спільний для плану `docs/superpowers/plans/2026-08-29-admin-filter-bar-
rollout.md`: кожне з його завдань додає СЮДИ свою секцію, а не заводить
окремий файл --

  * Task 1 -- Коментарі блогу (тут);
  * Task 2 -- Webhook черга;
  * Task 3 -- Результати тестування по групі;
  * Task 4 -- Перф-прогони.

Секції незалежні одна від одної: спільне -- лише autouse-фікстура нижче,
що прибирає за собою власних User (SQLite без каскадів, а
/api/v1/participants?per_page=200 мовчки вважає, що більше 200 юзерів не
буває -- лишений тут акаунт валить TestParticipants ЛИШЕ в повному прогоні).
"""
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.auth_identity import AuthIdentity
from app.models.blog_comment import BlogComment
from app.models.blog_post import BlogPost
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.perf_run import PerfPageMetric, PerfRun, VERDICT_FAIL, VERDICT_OK
from app.models.registration import EventRegistration
from app.models.user import User
from app.models.webhook_delivery import WebhookDelivery

EMAIL_PREFIX = 'mf-'

# Маркер у target_url -- за ним прибираємо власні WebhookDelivery в teardown
# (таблиця без FK-дітей, тож досить одного DELETE, на відміну від User нижче).
WH_TARGET_MARKER = 'https://wh-test.example/'


@pytest.fixture(autouse=True)
def clean(app):
    """Порожні власні дописи/коментарі блогу і власні користувачі."""
    def _wipe():
        own_posts = db.session.query(BlogPost.id).filter(
            BlogPost.slug.like(f'{EMAIL_PREFIX}%'))
        # Явно, дитина перед батьком: BlogPost.comments оголошено з
        # passive_deletes=True (ORM свідомо покладається на БД-каскад), а
        # SQLite тестового прогону PRAGMA foreign_keys=ON всередині
        # транзакції не тримає -- каскад мовчки не спрацьовує, і коментарі
        # лишаються сирітками з post_id на видалений допис.
        BlogComment.query.filter(BlogComment.post_id.in_(own_posts)).delete(
            synchronize_session=False)
        BlogPost.query.filter(BlogPost.slug.like(f'{EMAIL_PREFIX}%')).delete(
            synchronize_session=False)
        stale = [
            row.id for row in User.query.filter(
                User.email.like(f'{EMAIL_PREFIX}%@test.com')).all()
        ]
        if stale:
            for model in (AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


@pytest.fixture
def admin(app):
    user = User.create_with_password(
        f'{EMAIL_PREFIX}{uuid4().hex[:8]}@test.com', 'password123',
        first_name='А', last_name='Адмін', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = str(user.id)


def _post(**kwargs):
    kwargs.setdefault('title', f'Допис {uuid4().hex[:6]}')
    post = BlogPost(slug=f'{EMAIL_PREFIX}{uuid4().hex[:8]}', **kwargs)
    db.session.add(post)
    db.session.commit()
    return post


def _comment(post, **kwargs):
    kwargs.setdefault('author_name', f'Автор {uuid4().hex[:4]}')
    kwargs.setdefault('email', f'{uuid4().hex[:8]}@example.com')
    kwargs.setdefault('body', 'Звичайний коментар без нічого особливого.')
    kwargs.setdefault('status', BlogComment.STATUS_PENDING)
    comment = BlogComment(post_id=post.id, **kwargs)
    db.session.add(comment)
    db.session.commit()
    return comment


# --------------------------- Коментарі блогу ---------------------------


class TestBlogCommentsFilters:
    def test_search_narrows_to_matching_comment(self, client, admin):
        post = _post()
        target = _comment(post, author_name='Незвичне Прізвище')
        other = _comment(post, author_name='Хтось Інший')

        _login(client, admin)
        body = client.get('/admin/blog/comments?q=Незвичне').get_data(as_text=True)

        assert target.author_name in body
        assert other.author_name not in body

    def test_post_filter_shows_only_its_comments(self, client, admin):
        post_a = _post(title='Допис А')
        post_b = _post(title='Допис Б')
        own = _comment(post_a, author_name='Коментар допису А')
        foreign = _comment(post_b, author_name='Коментар допису Б')

        _login(client, admin)
        body = client.get(f'/admin/blog/comments?post_id={post_a.id}').get_data(as_text=True)

        assert own.author_name in body
        assert foreign.author_name not in body

    def test_second_page_carries_status_and_filter(self, client, admin):
        post = _post()
        # 26 коментарів під одним пошуковим словом -- при per_page=25 це
        # рівно дві сторінки, і на другій лишається один інакший рядок.
        for _ in range(26):
            _comment(post, author_name='Сторінковий-' + uuid4().hex[:6])

        _login(client, admin)
        page1 = client.get(
            '/admin/blog/comments?per_page=25&q=Сторінковий'
        ).get_data(as_text=True)
        page2 = client.get(
            '/admin/blog/comments?per_page=25&q=Сторінковий&page=2'
        ).get_data(as_text=True)

        assert 'page=2' in page1
        assert 'status=pending' in page1
        assert 'q=' in page1

        # Рядки на сторінках різні: 25 авторів на першій, 1 -- на другій, і
        # той один не мусить траплятись на першій.
        page1_authors = set(re.findall(r'Сторінковий-\w{6}', page1))
        page2_authors = set(re.findall(r'Сторінковий-\w{6}', page2))
        assert len(page1_authors) == 25
        assert len(page2_authors) == 1
        assert not (page1_authors & page2_authors)

    def test_empty_filtered_result_says_nothing_found(self, client, admin):
        post = _post()
        _comment(post)

        _login(client, admin)
        body = client.get('/admin/blog/comments?q=НемаєТакогоНіде').get_data(as_text=True)

        assert 'Нічого не знайдено' in body
        assert 'Коментарів немає' not in body

    def test_empty_without_filter_says_no_comments(self, client, admin):
        _login(client, admin)
        body = client.get('/admin/blog/comments?status=spam').get_data(as_text=True)

        assert 'Коментарів немає' in body


# ----------------------------- Webhook черга -----------------------------


@pytest.fixture(autouse=True)
def clean_webhooks(app):
    """Порожня власна частина webhook_deliveries.

    Таблиця -- лист (немає FK-дітей), тож на відміну від User/BlogPost вище
    досить одного DELETE за міткою в target_url.
    """
    def _wipe():
        WebhookDelivery.query.filter(
            WebhookDelivery.target_url.like(f'{WH_TARGET_MARKER}%')
        ).delete(synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _delivery(**kwargs):
    """WebhookDelivery за замовчуванням -- каталожна подія (курс), якщо
    виклик явно не задав event_type чи course_id (партнерська подія)."""
    kwargs.setdefault('event_uuid', uuid4().hex)
    kwargs.setdefault('target_url', WH_TARGET_MARKER + uuid4().hex[:8])
    kwargs.setdefault('status', 'pending')
    if 'event_type' not in kwargs and 'course_id' not in kwargs:
        kwargs.setdefault('course_id', 1)
        kwargs.setdefault('course_slug', 'course-' + uuid4().hex[:8])
        kwargs.setdefault('action', 'updated')
    delivery = WebhookDelivery(**kwargs)
    db.session.add(delivery)
    db.session.commit()
    return delivery


class TestWebhookQueueFilters:
    def test_search_narrows_by_course_slug(self, client, admin):
        marker = uuid4().hex[:10]
        target = _delivery(course_slug=f'course-{marker}')
        other = _delivery(course_slug='course-unrelated')

        _login(client, admin)
        body = client.get(f'/admin/webhooks?q={marker}').get_data(as_text=True)

        assert target.course_slug in body
        assert other.course_slug not in body

    def test_search_narrows_by_event_uuid(self, client, admin):
        target = _delivery()
        other = _delivery()

        _login(client, admin)
        body = client.get(f'/admin/webhooks?q={target.event_uuid}').get_data(as_text=True)

        assert target.event_uuid[:12] in body
        assert other.event_uuid[:12] not in body

    def test_event_type_catalog_shows_only_empty_event_type(self, client, admin):
        catalog = _delivery()  # event_type=None, курс/дія задані
        partner = _delivery(event_type='lead.created', target_url=WH_TARGET_MARKER + uuid4().hex[:8])

        _login(client, admin)
        body = client.get('/admin/webhooks?event_type=catalog').get_data(as_text=True)

        assert catalog.event_uuid[:12] in body
        assert partner.event_uuid[:12] not in body

    def test_second_page_keeps_status_and_q(self, client, admin):
        marker = 'whpage' + uuid4().hex[:6]
        for _ in range(26):
            _delivery(course_slug=f'{marker}-{uuid4().hex[:6]}', status='pending')

        _login(client, admin)
        page1 = client.get(
            f'/admin/webhooks?per_page=25&status=pending&q={marker}'
        ).get_data(as_text=True)
        page2 = client.get(
            f'/admin/webhooks?per_page=25&status=pending&q={marker}&page=2'
        ).get_data(as_text=True)

        assert 'page=2' in page1
        assert 'status=pending' in page1
        assert marker in page1

        page1_slugs = set(re.findall(rf'{re.escape(marker)}-\w{{6}}', page1))
        page2_slugs = set(re.findall(rf'{re.escape(marker)}-\w{{6}}', page2))
        assert len(page1_slugs) == 25
        assert len(page2_slugs) == 1
        assert not (page1_slugs & page2_slugs)

    def test_webhook_delete_redirects_with_saved_slice(self, client, admin):
        delivery = _delivery(status='failed')

        _login(client, admin)
        resp = client.post(
            f'/admin/webhooks/{delivery.id}/delete?status=failed&q=abc&page=2',
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers['Location']
        assert 'status=failed' in location
        assert 'q=abc' in location
        assert 'page=2' in location

    def test_status_filter_with_no_matches_says_nothing_found(self, client, admin):
        # Черга не порожня -- в ній є доставки, просто жодної "failed". Це
        # той самий зріз "лише status", що й у docstring narrow_args:
        # filter_args сама по собі не містить status (він не в fields
        # макроса), тож без narrow_args -- і без фіксу порядку reject у
        # empty_state -- сторінка брехала б "Записів немає".
        _delivery(status='pending')
        _delivery(status='sent')

        _login(client, admin)
        body = client.get('/admin/webhooks?status=failed').get_data(as_text=True)

        assert 'Нічого не знайдено' in body
        assert 'скинути фільтри' in body
        assert 'Записів немає' not in body

    def test_empty_queue_without_filter_says_no_records(self, client, admin):
        # Черга справді порожня (жодної власної доставки, жодного фільтра) --
        # тут "Записів немає" лишається правдою.
        _login(client, admin)
        body = client.get('/admin/webhooks').get_data(as_text=True)

        assert 'Записів немає' in body
        assert 'Нічого не знайдено' not in body


# ------------------------- Результати тестування по групі -------------------

# Маркер у Course.slug і в email учасників -- за ним прибираємо власні
# Course/CourseInstance/EventRegistration/Certificate і власних User.
QR_PREFIX = 'qr-'


@pytest.fixture(autouse=True)
def clean_quiz_results(app):
    """Порожня власна частина курсів/проведень/реєстрацій тестування.

    Дитина перед батьком (SQLite тестового прогону PRAGMA foreign_keys=ON
    усередині транзакції каскади не тримає, так само, як у секції коментарів
    блогу вище): Certificate -> EventRegistration -> CourseInstance -> Course,
    а власних User (маркер у email) -- AuthIdentity/MedicalProfile перед User.
    """
    def _wipe():
        own_courses = db.session.query(Course.id).filter(
            Course.slug.like(f'{QR_PREFIX}%'))
        own_instances = db.session.query(CourseInstance.id).filter(
            CourseInstance.course_id.in_(own_courses))
        own_regs = db.session.query(EventRegistration.id).filter(
            EventRegistration.instance_id.in_(own_instances))
        Certificate.query.filter(
            Certificate.registration_id.in_(own_regs)).delete(synchronize_session=False)
        EventRegistration.query.filter(
            EventRegistration.instance_id.in_(own_instances)).delete(synchronize_session=False)
        CourseInstance.query.filter(
            CourseInstance.course_id.in_(own_courses)).delete(synchronize_session=False)
        Course.query.filter(Course.slug.like(f'{QR_PREFIX}%')).delete(synchronize_session=False)
        stale = [
            row.id for row in User.query.filter(
                User.email.like(f'{QR_PREFIX}%@test.com')).all()
        ]
        if stale:
            for model in (AuthIdentity, MedicalProfile):
                model.query.filter(model.user_id.in_(stale)).delete(
                    synchronize_session=False)
            User.query.filter(User.id.in_(stale)).delete(
                synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _qr_course(**kwargs):
    kwargs.setdefault('title', f'Курс {uuid4().hex[:6]}')
    kwargs.setdefault('is_active', True)
    course = Course(slug=f'{QR_PREFIX}{uuid4().hex[:8]}', **kwargs)
    db.session.add(course)
    db.session.commit()
    return course


def _qr_instance(course, **kwargs):
    kwargs.setdefault('start_date', datetime.now(timezone.utc) + timedelta(days=7))
    kwargs.setdefault('end_date', datetime.now(timezone.utc) + timedelta(days=7, hours=4))
    kwargs.setdefault('event_format', 'offline')
    kwargs.setdefault('status', 'published')
    instance = CourseInstance(course_id=course.id, **kwargs)
    db.session.add(instance)
    db.session.commit()
    return instance


def _qr_participant(**kwargs):
    kwargs.setdefault('first_name', 'Учасник')
    last_name = kwargs.pop('last_name', f'Тест{uuid4().hex[:6]}')
    user = User.create_with_password(
        f'{QR_PREFIX}{uuid4().hex[:8]}@test.com', 'password123',
        last_name=last_name, email_confirmed=True, **kwargs,
    )
    db.session.commit()
    return user


def _qr_registration(user, instance, **kwargs):
    kwargs.setdefault('phone', '+380501234567')
    kwargs.setdefault('specialty', 'Кардіологія')
    kwargs.setdefault('workplace', 'Лікарня')
    kwargs.setdefault('status', 'confirmed')
    kwargs.setdefault('payment_status', 'paid')
    reg = EventRegistration(user_id=user.id, instance_id=instance.id, **kwargs)
    db.session.add(reg)
    db.session.commit()
    return reg


def _qr_certificate(reg, **kwargs):
    kwargs.setdefault('recipient_name', reg.user.full_name)
    kwargs.setdefault('event_title', 'Захід')
    kwargs.setdefault('number', f'QR-{uuid4().hex[:10]}')
    kwargs.setdefault('pdf_path', f'certs/{uuid4().hex[:8]}.pdf')
    cert = Certificate(registration_id=reg.id, user_id=reg.user_id, **kwargs)
    db.session.add(cert)
    db.session.commit()
    return cert


class TestQuizResultsFilters:
    def test_state_not_passed_hides_who_passed_shows_who_did_not(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        passed = _qr_participant(last_name='Пройшов' + uuid4().hex[:6])
        pending = _qr_participant(last_name='Очікує' + uuid4().hex[:6])
        _qr_registration(passed, instance, quiz_passed_at=datetime.now(timezone.utc))
        _qr_registration(pending, instance)

        _login(client, admin)
        body = client.get(
            f'/admin/instances/{instance.id}/quiz-results?state=not_passed'
        ).get_data(as_text=True)

        assert pending.last_name in body
        assert passed.last_name not in body

    def test_state_no_certificate_hides_participant_with_issued_certificate(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        certified = _qr_participant(last_name='Сертифікований' + uuid4().hex[:6])
        uncertified = _qr_participant(last_name='БезСертифіката' + uuid4().hex[:6])
        reg_certified = _qr_registration(
            certified, instance, quiz_passed_at=datetime.now(timezone.utc))
        _qr_certificate(reg_certified)
        _qr_registration(uncertified, instance)

        _login(client, admin)
        body = client.get(
            f'/admin/instances/{instance.id}/quiz-results?state=no_certificate'
        ).get_data(as_text=True)

        assert uncertified.last_name in body
        assert certified.last_name not in body

    def test_search_by_last_name_narrows_list(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        target = _qr_participant(last_name='Неповторний' + uuid4().hex[:6])
        other = _qr_participant(last_name='Інший' + uuid4().hex[:6])
        _qr_registration(target, instance)
        _qr_registration(other, instance)

        _login(client, admin)
        body = client.get(
            f'/admin/instances/{instance.id}/quiz-results?q={target.last_name}'
        ).get_data(as_text=True)

        assert target.last_name in body
        assert other.last_name not in body

    def test_stat_card_counters_do_not_move_under_filter(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        passed = _qr_participant(last_name='Пройшов2' + uuid4().hex[:6])
        pending = _qr_participant(last_name='Очікує2' + uuid4().hex[:6])
        reg_passed = _qr_registration(
            passed, instance, quiz_passed_at=datetime.now(timezone.utc))
        _qr_certificate(reg_passed)
        _qr_registration(pending, instance)

        _login(client, admin)
        unfiltered = client.get(
            f'/admin/instances/{instance.id}/quiz-results'
        ).get_data(as_text=True)
        filtered = client.get(
            f'/admin/instances/{instance.id}/quiz-results?state=not_passed'
        ).get_data(as_text=True)

        def _counts(body):
            return re.findall(r'admin-stat-card__value">(\d+)<', body)

        # Учасників: 2, склали: 1, сертифікатів видано: 1 -- і під фільтром, і
        # без нього: лічильники рахуються з `base` (уся група), а не зі зрізу.
        assert _counts(unfiltered) == ['2', '1', '1']
        assert _counts(filtered) == ['2', '1', '1']


# ------------------------------- Перф-прогони -------------------------------

# Маркер у base_url -- за ним прибираємо власні PerfRun (і дітей
# PerfPageMetric, у цих тестах не використовуються, але teardown вписаний на
# випадок появи в майбутньому).
PERF_BASE_MARKER = 'https://perf-test.example/'


@pytest.fixture(autouse=True)
def clean_perf(app):
    """Порожня власна частина perf_runs (+ дочірні perf_page_metrics).

    PerfRun.pages оголошено з cascade='all, delete-orphan' на ORM-рівні, але
    SQLite тестового прогону каскад на БД-рівні всередині транзакції не
    тримає (та сама пастка, що й у секціях вище) -- дитина видаляється перед
    батьком явним запитом.
    """
    def _wipe():
        own_runs = db.session.query(PerfRun.id).filter(
            PerfRun.base_url.like(f'{PERF_BASE_MARKER}%'))
        PerfPageMetric.query.filter(PerfPageMetric.run_id.in_(own_runs)).delete(
            synchronize_session=False)
        PerfRun.query.filter(
            PerfRun.base_url.like(f'{PERF_BASE_MARKER}%')
        ).delete(synchronize_session=False)
        db.session.commit()

    _wipe()
    yield
    _wipe()


def _perf_run(**kwargs):
    kwargs.setdefault('measured_at', datetime.now(timezone.utc))
    kwargs.setdefault('base_url', PERF_BASE_MARKER + uuid4().hex[:8])
    kwargs.setdefault('source', 'local')
    kwargs.setdefault('note', '')
    kwargs.setdefault('runs_per_page', 1)
    kwargs.setdefault('tool_version', '1.0.0')
    kwargs.setdefault('verdict', VERDICT_OK)
    kwargs.setdefault('pages_total', 1)
    kwargs.setdefault('pages_warn', 0)
    kwargs.setdefault('pages_fail', 0)
    kwargs.setdefault('budgets', {})
    run = PerfRun(**kwargs)
    db.session.add(run)
    db.session.commit()
    return run


class TestPerfRunsFilters:
    def test_verdict_fail_leaves_only_failed_runs(self, client, admin):
        failed = _perf_run(verdict=VERDICT_FAIL, note='Провалений ' + uuid4().hex[:6])
        ok = _perf_run(verdict=VERDICT_OK, note='Успішний ' + uuid4().hex[:6])

        _login(client, admin)
        body = client.get('/admin/perf?verdict=FAIL').get_data(as_text=True)

        assert failed.note in body
        assert ok.note not in body

    def test_source_ci_hides_local_runs(self, client, admin):
        ci = _perf_run(source='ci', note='CI-замір ' + uuid4().hex[:6])
        local = _perf_run(source='local', note='Локальний замір ' + uuid4().hex[:6])

        _login(client, admin)
        body = client.get('/admin/perf?source=ci').get_data(as_text=True)

        assert ci.note in body
        assert local.note not in body

    def test_latest_run_block_hidden_under_active_filter(self, client, admin):
        _perf_run(verdict=VERDICT_OK)

        _login(client, admin)
        unfiltered = client.get('/admin/perf').get_data(as_text=True)
        filtered = client.get('/admin/perf?verdict=OK').get_data(as_text=True)

        # Без фільтра сторінка 1 -- це і є найновіший замір узагалі, тож блок
        # "останній замір" (шапка + картки) малюється. Під фільтром перший
        # рядок сторінки 1 -- лише найновіший У ЗРІЗІ, і блок брехав би,
        # підписуючи його як "останній замір" -- тому не малюється.
        assert 'Останній замір' in unfiltered
        assert 'Останній замір' not in filtered

    def test_reveal_flag_not_in_chips_or_pagination(self, client, admin):
        # 21 прогін під одним активним фільтром -- рівно дві сторінки при
        # PER_PAGE=20, тож і чіпс фільтра, і посилання пагінації присутні.
        for _ in range(21):
            _perf_run(verdict=VERDICT_FAIL, source='ci')

        _login(client, admin)
        body = client.get(
            '/admin/perf?verdict=FAIL&source=ci&reveal=1'
        ).get_data(as_text=True)

        # Доказ, що чіпси й пагінація справді відрендерились (інакше нижні
        # перевірки нічого не доводили б).
        chips = re.search(
            r'<div class="admin-filters__chips">.*?</div>', body, re.DOTALL)
        pager_nav = re.search(
            r'<nav class="admin-pagination">.*?</nav>', body, re.DOTALL)
        assert chips is not None
        assert pager_nav is not None
        assert 'page=2' in pager_nav.group()
        # ?reveal=1 -- окремий, не-фільтровий параметр: не мусить потрапити
        # ні в чіпси (кожен -- href на цей самий зріз), ні в посилання
        # пагінації. Перевіряємо саме ці два блоки, а не весь body: тег
        # og:url у <head> завжди відбиває поточний URL запиту, і це не
        # витік -- лише сам факт запиту з ?reveal=1, а не копіювання прапорця
        # в кожне посилання зрізу.
        assert 'reveal' not in chips.group()
        assert 'reveal' not in pager_nav.group()


# --------------------- Фінальний прогін ревʼю: чотири правки ---------------
#
# Секція для чотирьох Important-знахідок фінального ревʼю плану
# `docs/superpowers/plans/2026-08-29-admin-filter-bar-rollout.md`:
#
#   1. stat-картка статусу webhook-черги губила решту фільтрів;
#   2. шапка перф-прогонів брехала "Замірів ще немає" під зрізом із рядками;
#   3. (empty_state/narrow_args) уже покрито тестами вище й у самому макросі;
#   4. POST-редіректи тестування учасників губили активний зріз.
#
# Власних фікстур не заводимо -- використовуємо ті самі фабрики й autouse-
# teardown, що й секції вище (вони прибирають за собою в тому самому файлі).


class TestWebhookStatCardPreservesFilters:
    def test_stat_card_link_keeps_active_search(self, client, admin):
        marker = 'whcard' + uuid4().hex[:6]
        _delivery(course_slug=f'{marker}-pending', status='pending')
        _delivery(course_slug=f'{marker}-failed', status='failed')

        _login(client, admin)
        body = client.get(f'/admin/webhooks?q={marker}').get_data(as_text=True)

        # Картка "Failed" веде на status=failed, і той самий href мусить
        # нести активний пошук -- інакше клік по картці показує ВСІ
        # помилки, а не лише ті, що під поточним пошуком.
        card_href = re.search(r'href="([^"]*status=failed[^"]*)"', body)
        assert card_href is not None
        assert f'q={marker}' in card_href.group(1)


class TestPerfHeroUnderFilter:
    def test_hero_does_not_claim_no_measurements_when_filtered_rows_exist(
        self, client, admin,
    ):
        _perf_run(source='ci', verdict=VERDICT_OK,
                  note='Наявний під фільтром ' + uuid4().hex[:6])

        _login(client, admin)
        body = client.get('/admin/perf?source=ci').get_data(as_text=True)

        # 40 прогонів джерела ci з рядками на екрані -- шапка не мусить
        # писати "Замірів ще немає": це неправда під активним зрізом, що й
        # містить справжні рядки.
        assert 'Замірів ще немає' not in body

    def test_unfiltered_page_two_does_not_ask_to_reset_filter(self, client, admin):
        # `latest` -- None і без жодного фільтра на другій сторінці
        # (routes_perf.py: `page == 1 and not filter_args`), а не лише під
        # активним зрізом. Шапка не мусить пропонувати "скинути фільтр",
        # якого тут узагалі нема -- це той самий факт, що й на сторінці 1
        # без фільтра, просто інший рядок замірів попереду.
        for _ in range(25):
            _perf_run(verdict=VERDICT_OK)

        _login(client, admin)
        body = client.get('/admin/perf?page=2').get_data(as_text=True)

        assert 'скиньте фільтр' not in body


class TestQuizResultsActionsKeepSlice:
    def test_unlock_action_redirects_back_to_active_slice(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        participant = _qr_participant(last_name='Розблокування' + uuid4().hex[:6])
        reg = _qr_registration(participant, instance)

        _login(client, admin)
        resp = client.post(
            f'/admin/registrations/{reg.id}/quiz/unlock'
            '?state=not_passed&payment=paid&page=2',
            data={'extra': '1'},
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers['Location']
        assert f'/admin/instances/{instance.id}/quiz-results' in location
        assert 'state=not_passed' in location
        assert 'payment=paid' in location
        assert 'page=2' in location

    def test_reset_action_redirects_back_to_active_slice(self, client, admin):
        course = _qr_course()
        instance = _qr_instance(course)
        participant = _qr_participant(last_name='Обнулення' + uuid4().hex[:6])
        reg = _qr_registration(
            participant, instance, quiz_passed_at=datetime.now(timezone.utc))

        _login(client, admin)
        resp = client.post(
            f'/admin/registrations/{reg.id}/quiz/reset?state=passed',
            follow_redirects=False,
        )

        assert resp.status_code == 302
        location = resp.headers['Location']
        assert f'/admin/instances/{instance.id}/quiz-results' in location
        assert 'state=passed' in location
        # Сторінка не задана в запиті (типова, 1) -- back_redirect не мусить
        # дописувати порожній page=1 у кожен пост-екшн-URL.
        assert 'page=' not in location
