"""Тести поштового сервісу: інваріант тригерів, plain-text конвертер,
smoke-рендер усіх шаблонів і гарди send_email (suppression/opt-out/
idempotency/dedup/невідомий trigger)."""
import os
import re

import pytest
from jinja2 import Undefined

from app.extensions import db
from app.models.email_log import EmailLog
from app.models.email_suppression import EmailSuppression
from app.models.user import User
from app.services import email_service
from app.services.email_service import EmailService, _html_to_plaintext


# ---------------------------------------------------------------------------
# 1. Інваріант тригерів: кожен trigger='...' у коді має бути в ALLOWED_TRIGGERS,
#    а ALLOWED_TRIGGERS має точно збігатися з CHECK ck_email_logs_trigger.
#    Це назавжди вбиває клас багів (certificate / blog_comment / password_reset).
# ---------------------------------------------------------------------------
_TRIGGER_LITERAL_RE = re.compile(r"""trigger\s*=\s*['"]([a-z_]+)['"]""")


def _iter_app_py_files():
    app_dir = os.path.dirname(os.path.dirname(email_service.__file__))  # app/
    for root, _dirs, files in os.walk(app_dir):
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)


def test_all_code_triggers_are_allowed():
    used = set()
    for path in _iter_app_py_files():
        with open(path, encoding='utf-8') as fh:
            used.update(_TRIGGER_LITERAL_RE.findall(fh.read()))
    unknown = used - EmailLog.ALLOWED_TRIGGERS
    assert not unknown, (
        f'Тригери {unknown} використані в коді, але відсутні в '
        f'EmailLog.TRIGGERS/CHECK. Додайте їх + міграцію CHECK.'
    )


def test_check_constraint_matches_allowed_triggers():
    from sqlalchemy import CheckConstraint
    sqltext = None
    for c in EmailLog.__table__.constraints:
        if isinstance(c, CheckConstraint) and c.name == 'ck_email_logs_trigger':
            sqltext = str(c.sqltext)
            break
    assert sqltext is not None, 'CHECK ck_email_logs_trigger не знайдено в моделі'
    in_constraint = set(re.findall(r"'([a-z_]+)'", sqltext))
    assert in_constraint == EmailLog.ALLOWED_TRIGGERS, (
        'CHECK і EmailLog.TRIGGERS розійшлися: '
        f'{in_constraint ^ EmailLog.ALLOWED_TRIGGERS}'
    )


# ---------------------------------------------------------------------------
# 2. _html_to_plaintext: чистий текст без CSS/коментарів/невидимих символів,
#    із збереженими URL і декодованими entity.
# ---------------------------------------------------------------------------
def test_html_to_plaintext_strips_css_and_keeps_links():
    html = (
        '<html><head><title>X</title>'
        '<style>body { margin:0; } @media x { .a{} }</style></head>'
        '<body><!--[if mso]><xml>96</xml><![endif]-->'
        '<div style="display:none">Pre&#8199;&#65279;&#847;</div>'
        '<h1>Заголовок</h1><p>Текст листа.</p>'
        '<a href="https://plasma-regen.com/p/1">Кнопка</a>'
        '<p>Компанія &mdash; ІПРМ&nbsp;2026</p></body></html>'
    )
    out = _html_to_plaintext(html)
    assert 'margin' not in out and 'font-size' not in out  # CSS прибрано
    assert '96' not in out  # MSO-коментар прибрано
    assert 'https://plasma-regen.com/p/1' in out  # URL збережено
    assert '—' in out  # &mdash; -> em-dash
    assert 'ІПРМ 2026' in out  # &nbsp; -> пробіл
    assert '﻿' not in out and ' ' not in out  # невидимий спам прибрано


# ---------------------------------------------------------------------------
# 3. Smoke-рендер кожного шаблона листа -- ловить Jinja/макро-помилки до прода.
# ---------------------------------------------------------------------------
class _SmokeUndefined(Undefined):
    """Поблажливий Undefined: доступ/виклик/ітерація/арифметика/порівняння
    не падають -- щоб smoke-рендер ловив лише структурні помилки шаблона."""
    __slots__ = ()

    def __getattr__(self, _name):
        return self

    def __getitem__(self, _key):
        return self

    def __call__(self, *a, **k):
        return self

    def __iter__(self):
        return iter(())

    # Арифметика (напр. days_label: n % 10) -> повертаємо себе.
    def _self(self, *a, **k):
        return self
    __add__ = __radd__ = __sub__ = __rsub__ = _self
    __mul__ = __rmul__ = __mod__ = __rmod__ = _self
    __floordiv__ = __truediv__ = _self

    def __int__(self):
        return 0

    def __float__(self):
        return 0.0

    # Порівняння (n >= 11 and n <= 19) -> завжди False.
    def _false(self, *a, **k):
        return False
    __eq__ = __ne__ = __lt__ = __le__ = __gt__ = __ge__ = _false

    def __hash__(self):
        return 0


def test_all_email_templates_render(app):
    from flask import render_template
    tpl_dir = os.path.join(os.path.dirname(email_service.__file__), '..', 'templates', 'emails')
    tpl_dir = os.path.abspath(tpl_dir)
    names = [
        f for f in os.listdir(tpl_dir)
        if f.endswith('.html') and not f.startswith('_') and f not in ('base.html',)
    ]
    assert names, 'Не знайдено шаблонів листів'
    original = app.jinja_env.undefined
    app.jinja_env.undefined = _SmokeUndefined
    try:
        with app.test_request_context('/'):
            for name in names:
                try:
                    render_template(f'emails/{name}')
                except Exception as exc:  # noqa: BLE001
                    pytest.fail(f'Шаблон emails/{name} не рендериться: {exc!r}')
    finally:
        app.jinja_env.undefined = original


# ---------------------------------------------------------------------------
# 4. Гарди send_email.
# ---------------------------------------------------------------------------
@pytest.fixture
def enabled_mail(monkeypatch):
    """Імітувати увімкнену пошту без мережі: мокаємо _get_smtp_config (щоб не
    залежати від БД-сесії всередині вкладеного app_context) і _send_in_thread."""
    cfg = {
        'server': 'smtp.example.com', 'port': 587, 'use_ssl': False, 'use_tls': True,
        'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
        'has_password': True, 'sender': 'u@example.com',
    }
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: cfg)
    monkeypatch.setattr(EmailService, '_send_in_thread', staticmethod(lambda *a, **k: None))
    # Ізолюємо від накопичених failed-логів інших тестів (circuit breaker).
    monkeypatch.setattr(EmailService, '_check_circuit_breaker', staticmethod(lambda: False))


def test_unknown_trigger_is_coerced_not_crashing():
    # Пошту вимкнено -> створює failed-лог; trigger має стати NULL, без винятку.
    log = EmailService.send_email(
        to='x@example.com', subject='s', template_name='test',
        trigger='totally_unknown_trigger',
    )
    assert log is not None
    assert log.trigger is None


def test_bounce_suppression_blocks_all():
    EmailSuppression.add('dead@example.com', reason=EmailSuppression.REASON_BOUNCE)
    db.session.flush()
    result = EmailService.send_email(
        to='dead@example.com', subject='s', template_name='test', trigger='registration',
    )
    assert result is None
    assert EmailLog.query.filter_by(to_email='dead@example.com').first() is None


def test_optout_blocks_optional_only():
    u = User(email='opt@example.com', email_opt_out=True)
    db.session.add(u)
    db.session.flush()
    # reminder -- необов'язковий -> блок
    assert EmailService.send_email(
        to='opt@example.com', subject='s', template_name='test', trigger='reminder',
    ) is None
    # registration -- транзакційний -> не блокується opt-out (іде далі)
    assert EmailService.send_email(
        to='opt@example.com', subject='s', template_name='test', trigger='registration',
    ) is not None


def test_idempotency_skips_duplicate(enabled_mail):
    first = EmailService.send_email(
        to='i1@example.com', subject='s', template_name='test',
        trigger='registration', idempotency_key='dup-key-1',
    )
    assert first is not None
    second = EmailService.send_email(
        to='i2@example.com', subject='s', template_name='test',
        trigger='registration', idempotency_key='dup-key-1',
    )
    assert second is None


def test_stale_pending_is_not_retryable():
    """Регресія: stale-pending має НЕВІДОМУ доставку -> не авто-ретраїмо,
    інакше дублі (циклічна розсилка, на яку поскаржився користувач)."""
    e = EmailLog(
        to_email='x@example.com', subject='s', template_name='test',
        status='failed', trigger='registration', retry_count=0,
        html_body='<p>x</p>', error_message='Timeout: stuck in pending >5 min',
    )
    assert e.is_retryable is False


def test_transient_failure_is_retryable():
    e = EmailLog(
        to_email='x@example.com', subject='s', template_name='test',
        status='failed', trigger='registration', retry_count=0,
        html_body='<p>x</p>', error_message='Connection unexpectedly closed',
    )
    assert e.is_retryable is True


def test_dedup_skips_same_recipient_trigger(enabled_mail):
    first = EmailService.send_email(
        to='dd@example.com', subject='s', template_name='test', trigger='registration',
    )
    assert first is not None
    second = EmailService.send_email(
        to='dd@example.com', subject='s', template_name='test', trigger='registration',
    )
    assert second is None
