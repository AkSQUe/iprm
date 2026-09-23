"""Справжній `EmailService.send_email` без мережі.

Підміняється лише транспорт: конфіг SMTP (щоб пошта вважалась увімкненою) і
фоновий потік, що говорить із сервером. Усе, що стоїть перед ним, -- дедуп,
ключ ідемпотентності, рендер у локалі отримувача, запис у `email_logs` --
працює як у проді. Саме там і ховались помилки, яких не видно тестам, що
мокають `send_email` цілком.
"""
from app.services import email_service
from app.services.email_service import EmailService

_SMTP = {
    'server': 'smtp.example.com', 'port': 587, 'use_ssl': False, 'use_tls': True,
    'username': 'u@example.com', 'password': 'x', 'is_enabled': True,
    'has_password': True, 'sender': 'u@example.com',
}


def enable_live_mail(monkeypatch):
    monkeypatch.setattr(email_service, '_get_smtp_config', lambda app: dict(_SMTP))
    monkeypatch.setattr(EmailService, '_send_in_thread',
                        staticmethod(lambda *a, **k: None))
    # Накопичені failed-логи інших тестів не мають відкривати запобіжник.
    monkeypatch.setattr(EmailService, '_check_circuit_breaker',
                        staticmethod(lambda: False))
