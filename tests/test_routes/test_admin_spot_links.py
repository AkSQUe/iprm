"""Точкові значення шести реєстрів адмінки: технічне чи особисте значення
однієї клітинки веде туди, де воно розкривається повністю.

Сертифікати: «Ким видано» -- у картку адміна, лише коли зв'язок є. Історія
змін заявки на курс: автор переходу -- туди ж. Тестування: розмір банку і
прохідний бал курсового тесту ведуть у той самий редактор, що й кнопка
рядка. Промокоди: «N з M» використань -- у картку коду, лише коли
використань хоч одне. Перф-прогони: вердикт -- у той самий реєстр, звужений
цим вердиктом.

`sku` у `material_kit_edit.html`/`materials_picking.html` (пункт 3 брифа) не
чіпаємо: жодного реального ендпоінта `admin.materials` немає, а обидва
кандидати -- `materials_overview` (без фільтра за sku) і `instance_materials`
(з фільтром `q`, який ігнорується, щойно документ уже в MM Medic) --
або не приймають значення, або тихо його відкидають. Тест на неіснуюче чи
ненадійне посилання не пишемо.
"""
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_quiz import CourseQuiz, QuizQuestion
from app.models.course_request import CourseRequest, CourseRequestAudit
from app.models.perf_run import PerfRun, VERDICT_WARN
from app.models.promo_code import PromoCode, DISCOUNT_PERCENT
from app.models.registration import EventRegistration
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'sl-{_uid()}@test.com', 'password123',
        first_name='S', last_name='L', is_admin=True, email_confirmed=True,
    )
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_certificate_issuer_links_to_user_detail(client, admin):
    """«Ким видано» -- у картку адміна, що видав сертифікат."""
    recipient = User.create_with_password(
        f'sl-{_uid()}@test.com', 'password123',
        first_name='Отримувач', last_name=_uid(), email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='completed', event_format='offline',
                          start_date=datetime.now(timezone.utc))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=recipient.id, instance_id=inst.id, phone='+380671110004',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    cert_number = f'sl-{_uid()}'
    cert = Certificate(
        registration_id=reg.id, user_id=recipient.id, number=cert_number,
        recipient_name=f'{recipient.first_name} {recipient.last_name}',
        event_title=course.title, pdf_path=f'certificates/{cert_number}.pdf',
        issued_by_id=admin.id,
    )
    db.session.add(cert)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/certificates?q={cert_number}').get_data(as_text=True)
        href = f'/admin/users/{admin.id}'
        assert re.search(
            rf'<small><a href="{re.escape(href)}">\s*{re.escape(admin.email)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(cert))
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(recipient))
        db.session.commit()


def test_certificate_without_issuer_stays_plain_text(client, admin):
    """Без issued_by (історичний запис) -- нема кому дзвонити, нема куди вести."""
    recipient = User.create_with_password(
        f'sl-{_uid()}@test.com', 'password123',
        first_name='Без', last_name='Видавця', email_confirmed=True,
    )
    db.session.flush()
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, status='completed', event_format='offline',
                          start_date=datetime.now(timezone.utc))
    db.session.add(inst)
    db.session.flush()
    reg = EventRegistration(
        user_id=recipient.id, instance_id=inst.id, phone='+380671110005',
        specialty='T', workplace='Клініка', status='confirmed', payment_status='paid',
    )
    db.session.add(reg)
    db.session.flush()
    cert_number = f'sl-{_uid()}'
    cert = Certificate(
        registration_id=reg.id, user_id=recipient.id, number=cert_number,
        recipient_name=f'{recipient.first_name} {recipient.last_name}',
        event_title=course.title, pdf_path=f'certificates/{cert_number}.pdf',
    )
    db.session.add(cert)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/certificates?q={cert_number}').get_data(as_text=True)
        # Немає issued_by -- у комірці лише прочерк, жодного <a> навколо нього.
        assert not re.search(r'<small><a href="/admin/users/\d+">', html)
    finally:
        db.session.delete(db.session.merge(cert))
        db.session.delete(db.session.merge(reg))
        db.session.delete(db.session.merge(inst))
        db.session.delete(db.session.merge(course))
        db.session.delete(db.session.merge(recipient))
        db.session.commit()


def test_course_request_audit_author_links_to_user_detail(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    req = CourseRequest(course_id=course.id, email=f'sl-{_uid()}@test.com', status='responded')
    db.session.add(req)
    db.session.flush()
    audit = CourseRequestAudit(
        request_id=req.id, from_status='pending', to_status='responded',
        changed_by_id=admin.id,
    )
    db.session.add(audit)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/course-requests/{req.id}/edit').get_data(as_text=True)
        href = f'/admin/users/{admin.id}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*{re.escape(admin.email)}', html)
    finally:
        # `audits` каскадується від request (delete-orphan) -- видаляти
        # рядок audit окремо не потрібно, і навіть шкідливо: SQLAlchemy
        # намагається видалити його ще раз при видаленні req.
        db.session.delete(db.session.merge(req))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_course_request_audit_without_author_stays_plain_text(client, admin):
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.flush()
    req = CourseRequest(course_id=course.id, email=f'sl-{_uid()}@test.com', status='dismissed')
    db.session.add(req)
    db.session.flush()
    audit = CourseRequestAudit(
        request_id=req.id, from_status='pending', to_status='dismissed',
        changed_by_id=None,
    )
    db.session.add(audit)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/course-requests/{req.id}/edit').get_data(as_text=True)
        # Без changed_by клітинка «Хто» в РЯДКУ АУДИТУ лишається голим тире,
        # не обгорнутим в <a>. Саме цю клітинку (другий <td> рядка), а не
        # відсутність /admin/users/ на всій сторінці: інакше сторож зламався б
        # у день, коли цю сторінку почнуть лінкувати з іншої причини.
        match = re.search(
            r'<tbody>\s*<tr>\s*<td>.*?</td>\s*<td>(.*?)</td>', html, re.S,
        )
        assert match, 'рядок історії змін не знайдено'
        author_cell = match.group(1).strip()
        assert author_cell == '–'
    finally:
        db.session.delete(db.session.merge(req))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def _quiz_with_bank(course, bank=2, passing_score=1):
    quiz = CourseQuiz(
        course_id=course.id, questions_per_attempt=bank, passing_score=passing_score,
        max_attempts=3, shuffle_answers=False, is_active=True,
    )
    db.session.add(quiz)
    db.session.flush()
    for i in range(bank):
        db.session.add(QuizQuestion(
            quiz_id=quiz.id, text=f'Питання {i + 1}?', sort_order=i,
            answers=[{'text': 'a', 'is_correct': False},
                     {'text': 'b', 'is_correct': True},
                     {'text': 'c', 'is_correct': False},
                     {'text': 'd', 'is_correct': False}],
        ))
    db.session.flush()
    return quiz


def test_quiz_bank_size_and_passing_score_link_to_course_quiz_edit(client, admin, app):
    """Обидва значення живуть у тесті КУРСУ -- редактор той самий, що й
    кнопка «Редагувати» цього рядка."""
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True,
                    bpr_event_number=_uid(), cpd_points=10)
    db.session.add(course)
    db.session.flush()
    quiz = _quiz_with_bank(course, bank=2, passing_score=1)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/quizzes?q={course.slug}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.course_quiz_edit', course_id=course.id)
        assert re.search(rf'<a href="{re.escape(href)}">\s*{quiz.bank_size}\s*</a>', html)
        # Уся фраза «N з M, спроб: K» -- в одному посиланні, а не лише бала:
        # клікабельним має бути весь текст, не одна цифра всередині нього.
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*{quiz.passing_score}\s*з\s*'
            rf'{quiz.questions_per_attempt}\s*,\s*спроб:\s*{quiz.max_attempts}\s*</a>',
            html,
        )
    finally:
        db.session.delete(db.session.merge(quiz))
        db.session.delete(db.session.merge(course))
        db.session.commit()


def test_quiz_missing_stays_plain_text(client, admin):
    """Гілка «тесту немає» -- нічого редагувати, нікуди вести.

    Кнопка «Створити» в колонці «Дії» веде на той самий `course_quiz_edit`
    незалежно від наявності тесту, тож перевіряємо не відсутність URL на
    сторінці взагалі, а що прочерк і напис «тесту немає» НЕ обгорнуті в
    <a> -- саме так, як того вимагає сторож «тег навколо значення».
    """
    course = Course(title=f'Курс {_uid()}', slug=f'sl-{_uid()}', is_active=True)
    db.session.add(course)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/quizzes?q={course.slug}').get_data(as_text=True)
        assert '<span class="admin-text-muted">&ndash;</span>' in html
        assert '<span class="admin-text-muted">тесту немає</span>' in html
        assert not re.search(
            r'<a href="[^"]*/quiz">\s*<span class="admin-text-muted">', html,
        )
    finally:
        db.session.delete(db.session.merge(course))
        db.session.commit()


def _promo(code, used_count=0, max_uses=None):
    promo = PromoCode(
        code=code, code_norm=code.casefold(),
        discount_type=DISCOUNT_PERCENT, discount_value=10,
        max_uses=max_uses, used_count=used_count, is_active=True,
    )
    db.session.add(promo)
    db.session.flush()
    return promo


def test_promo_usage_links_to_promo_code_detail_when_redeemed(client, admin, app):
    code = f'SL{_uid()}'
    promo = _promo(code, used_count=3, max_uses=10)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/promo-codes?q={code}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.promo_code_detail', promo_id=promo.id)
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*{re.escape(promo.usage_label)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(promo))
        db.session.commit()


def test_promo_usage_stays_plain_text_when_never_redeemed(client, admin):
    code = f'SL{_uid()}'
    promo = _promo(code, used_count=0, max_uses=10)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/promo-codes?q={code}').get_data(as_text=True)
        assert not re.search(rf'<a href="/admin/promo-codes/{promo.id}">\s*{re.escape(promo.usage_label)}', html)
    finally:
        db.session.delete(db.session.merge(promo))
        db.session.commit()


def test_perf_run_verdict_links_to_perf_runs_filtered_by_verdict(client, admin, app):
    """Вердикт -- у той самий реєстр, звужений НИМ, а не поточним зрізом
    сторінки (тут узагалі немає активного зрізу, лишень пошук, щоб знайти
    рядок серед чужих прогонів)."""
    note = f'sl-{_uid()}'
    run = PerfRun(
        measured_at=datetime.now(timezone.utc), base_url='https://iprm.space',
        source='sl-test', note=note, verdict=VERDICT_WARN,
        pages_total=5, pages_warn=2, pages_fail=0,
    )
    db.session.add(run)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/perf?q={note}').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.perf_runs', verdict=VERDICT_WARN)
        assert re.search(
            rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*{VERDICT_WARN}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(run))
        db.session.commit()
