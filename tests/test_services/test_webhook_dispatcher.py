"""Tests for webhook_dispatcher.dispatch_one.

Dispatcher -- чистий HTTP-layer: не читає SiteSettings, не пише в DB.
Повертає DispatchResult, який caller (webhook_queue) інтерпретує.
"""
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.webhook_dispatcher import DispatchResult, dispatch_one


SECRET = 'test-webhook-secret-' + 'x' * 40
TARGET_URL = 'https://partner.test/api/webhooks/iprm/events'


def _call(action='updated', course_id=42, course_slug='course-x',
          target_url=TARGET_URL, secret=SECRET, event_uuid='uuid-abc123'):
    return dispatch_one(
        course_id=course_id,
        course_slug=course_slug,
        action=action,
        target_url=target_url,
        secret=secret,
        event_uuid=event_uuid,
    )


class TestSignedPayload:
    def test_posts_to_target_url(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call()

        assert mock_post.called
        call = mock_post.call_args
        assert call.args[0] == TARGET_URL

    def test_signature_is_hmac_sha256_of_body(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call()

        call = mock_post.call_args
        body = call.kwargs['data']  # bytes
        headers = call.kwargs['headers']
        expected_sig = hmac.new(
            SECRET.encode('utf-8'), body, hashlib.sha256,
        ).hexdigest()
        assert headers['X-IPRM-Signature'] == expected_sig

    def test_event_id_header_is_passed_event_uuid(self):
        """X-IPRM-Event-Id -- stable id між retry (передається caller-ом)."""
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(event_uuid='fixed-uuid-xyz')
        headers = mock_post.call_args.kwargs['headers']
        assert headers['X-IPRM-Event-Id'] == 'fixed-uuid-xyz'

    def test_payload_shape(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(course_id=42, course_slug='course-x', action='updated')

        body = mock_post.call_args.kwargs['data']
        payload = json.loads(body)
        assert payload['event_type'] == 'event.updated'
        assert payload['slug'] == 'course-x'
        assert payload['event_id'] == 42
        assert payload['timestamp']

    def test_action_event_type_format(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            _call(action='deleted')
        payload = json.loads(mock_post.call_args.kwargs['data'])
        assert payload['event_type'] == 'event.deleted'


class TestDispatchResultSuccess:
    def test_2xx_returns_ok(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            result = _call()
        assert isinstance(result, DispatchResult)
        assert result.ok is True
        assert result.retryable is False
        assert result.http_status == 200
        assert result.error is None

    def test_201_returns_ok(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=201)
            result = _call()
        assert result.ok is True
        assert result.http_status == 201


class TestDispatchResultTransient:
    def test_5xx_is_retryable(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=503, text='down')
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status == 503
        assert 'down' in result.error

    def test_timeout_is_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.Timeout('read timeout'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status is None
        assert 'timeout' in result.error.lower()

    def test_connection_error_is_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.ConnectionError('partner offline'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is True
        assert result.http_status is None


class TestDispatchResultPermanent:
    def test_4xx_is_not_retryable(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=404, text='Not Found')
            result = _call()
        assert result.ok is False
        assert result.retryable is False
        assert result.http_status == 404

    def test_generic_request_exception_is_not_retryable(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.RequestException('malformed url'),
        ):
            result = _call()
        assert result.ok is False
        assert result.retryable is False


class TestNeverRaises:
    def test_does_not_raise_on_connection_error(self):
        with patch(
            'app.services.webhook_dispatcher.requests.post',
            side_effect=requests.ConnectionError('offline'),
        ):
            # Must not raise -- caller має бути безпечним від збоїв.
            _call()

    def test_does_not_raise_on_5xx(self):
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=503, text='x')
            _call()


class TestPartnerEventRetryPolicy:
    """404 від партнера означає «вимкнено», а не «немає такої адреси».

    Партнер віддає 404 на власному вимикачі інтеграції. Доки ми вважали це
    остаточною відмовою, ЇХНІЙ вимикач мовчки знищував події в НАШІЙ черзі:
    вони ставали `failed` назавжди й після повторного включення не приїжджали.
    """

    @staticmethod
    def _dispatch(status_code):
        from app.services.webhook_dispatcher import dispatch_partner_event

        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(
                ok=status_code < 400, status_code=status_code, text='')
            return dispatch_partner_event(
                event_type='registration.paid',
                payload={'registration_id': 1},
                target_url='https://partner.test/api/partner/iprm/events',
                secret=SECRET,
                event_uuid='uuid-evt-1',
            )

    def test_404_is_retryable(self):
        result = self._dispatch(404)

        assert result.ok is False
        assert result.retryable is True

    def test_503_stays_retryable(self):
        assert self._dispatch(503).retryable is True

    def test_400_is_permanent(self):
        """Зіпсовані дані повторювати марно — і партнер це вже сказав."""
        assert self._dispatch(400).retryable is False

    def test_401_is_permanent(self):
        """Невірний підпис від повтору не виправиться."""
        assert self._dispatch(401).retryable is False

    def test_207_is_retryable(self):
        """Пачка з однієї події: 207 означає «цю не прийняли»."""
        assert self._dispatch(207).retryable is True

    def test_200_is_success(self):
        result = self._dispatch(200)

        assert result.ok is True
        assert result.retryable is False

    def test_catalog_dispatch_keeps_404_permanent(self):
        """Там вимикача немає, тож 404 — справді неправильна адреса."""
        with patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=False, status_code=404, text='')
            result = dispatch_one(
                course_id=1, course_slug='c', action='updated',
                target_url=TARGET_URL, secret=SECRET, event_uuid='u-1',
            )

        assert result.retryable is False


class TestEveryAttemptIsSignedAfresh:
    """Ретрай мусить нести СВІЖУ мітку часу, інакше він мертвий за побудовою.

    У приймача партнерських подій вікно свіжості 300 секунд
    (``_TIMESTAMP_SKEW_SECONDS`` у ``api/partner_iprm.py`` на боці MM Medic):
    запит зі старшою міткою відхиляється як ``stale`` з 401. Наша черга ретраїть
    із backoff 1/2/4/8/16 хвилин, тобто вже друга спроба виходить за це вікно.

    Отже, якби підпис чи мітка кешувались разом із рядком черги, УСІ ретраї
    партнерських подій були б мертві: кожна спроба отримувала б 401, і так до
    вичерпання спроб. Помилка мовчазна -- у логах видно «партнер відхилив»,
    а не «ми надіслали прострочене».

    Тут це закріплено виконанням. Тіло події навмисно заморожене, тож єдине,
    що змінюється між спробами, -- годинник; будь-яка розбіжність підписів
    доводить, що підпис перерахований, а не взятий із кеша.
    """

    #: Вікно свіжості приймача. Дублюється тут свідомо: чуже число, яке ми не
    #: можемо імпортувати, а перевіряти мусимо.
    FRESHNESS_WINDOW = 300
    #: Остання сходинка backoff черги -- найгірший випадок для мітки часу.
    MAX_BACKOFF = 16 * 60

    PARTNER_URL = 'https://partner.test/api/partner/iprm/events'
    PAYLOAD = {
        'leadgen_id': '1234567890',
        'iprm_user_id': 4211,
        'phone': '+380671234567',
    }

    @classmethod
    def _attempt(cls, clock, event_uuid='uuid-lead-1'):
        """Одна спроба відправки о вказаній секунді. Повертає (headers, body).

        Заморожені обидва джерела часу, але з різною метою: ``time.time``
        підміняється, щоб рухати годинник між спробами, а ``datetime.now`` --
        щоб тіло лишалось байт-у-байт тим самим. Інакше підписи розійшлися б
        через зміну тіла, і тест нічого не сказав би про мітку.
        """
        from app.services.webhook_dispatcher import dispatch_partner_event

        frozen = MagicMock()
        frozen.now.return_value.isoformat.return_value = '2026-08-19T10:00:00+00:00'

        with patch('time.time', return_value=clock), \
                patch('app.services.webhook_dispatcher.datetime', frozen), \
                patch('app.services.webhook_dispatcher.requests.post') as mock_post:
            mock_post.return_value = MagicMock(ok=True, status_code=200)
            dispatch_partner_event(
                event_type='lead.created',
                payload=cls.PAYLOAD,
                target_url=cls.PARTNER_URL,
                secret=SECRET,
                event_uuid=event_uuid,
            )

        call = mock_post.call_args
        return call.kwargs['headers'], call.kwargs['data']

    @classmethod
    def _two_attempts(cls):
        """Перша спроба і ретрай після найдовшого backoff -- та сама подія."""
        first = cls._attempt(clock=1_755_600_000.0)
        second = cls._attempt(clock=1_755_600_000.0 + cls.MAX_BACKOFF)
        return first, second

    def test_body_stays_identical_between_attempts(self):
        """Контроль умови: подія не змінилась, змінився лише годинник."""
        (_, body_1), (_, body_2) = self._two_attempts()

        assert body_1 == body_2

    def test_timestamp_header_is_rebuilt_on_every_attempt(self):
        (headers_1, _), (headers_2, _) = self._two_attempts()

        assert headers_1['X-IPRM-Timestamp'] == '1755600000'
        assert headers_2['X-IPRM-Timestamp'] == str(1_755_600_000 + self.MAX_BACKOFF)
        assert headers_1['X-IPRM-Timestamp'] != headers_2['X-IPRM-Timestamp']

    def test_signature_is_rebuilt_on_every_attempt(self):
        """Те саме тіло, інша мітка -- отже інший підпис."""
        (headers_1, _), (headers_2, _) = self._two_attempts()

        assert headers_1['X-IPRM-Signature'] != headers_2['X-IPRM-Signature']

    def test_each_signature_is_valid_for_its_own_timestamp(self):
        """Рахуємо рівно те, що рахує ``require_iprm_hmac`` на тому боці."""
        for headers, body in self._two_attempts():
            signed = headers['X-IPRM-Timestamp'].encode('utf-8') + b'.' + body
            expected = hmac.new(
                SECRET.encode('utf-8'), signed, hashlib.sha256,
            ).hexdigest()

            assert headers['X-IPRM-Signature'] == expected

    def test_retry_after_the_longest_backoff_is_still_fresh(self):
        """Мітка ретраю -- це мить ретраю, а не мить постановки в чергу."""
        _, (headers_2, _) = self._two_attempts()
        sent_at = 1_755_600_000 + self.MAX_BACKOFF

        assert abs(sent_at - int(headers_2['X-IPRM-Timestamp'])) <= self.FRESHNESS_WINDOW

    def test_reusing_the_first_timestamp_would_be_rejected(self):
        """Негативний контроль: без перерахунку тест був би порожній.

        Якби мітка кешувалась, ретрай прилетів би з нею -- і приймач відхилив
        би його як ``stale``. Різниця нижче показує, наскільки саме: 960 секунд
        проти вікна в 300.
        """
        (headers_1, _), _ = self._two_attempts()
        sent_at = 1_755_600_000 + self.MAX_BACKOFF

        assert sent_at - int(headers_1['X-IPRM-Timestamp']) > self.FRESHNESS_WINDOW

    def test_event_id_stays_stable_across_attempts(self):
        """Зворотний бік: ідемпотентний ключ оновлювати НЕ можна.

        Партнер дедуплікує доставку саме за ним. Свіжий ``event_id`` на ретраї
        означав би, що прийнята-але-не-підтверджена подія застосується вдруге.
        """
        (headers_1, _), (headers_2, _) = self._two_attempts()

        assert headers_1['X-IPRM-Event-Id'] == headers_2['X-IPRM-Event-Id'] == 'uuid-lead-1'

    def test_dispatcher_takes_no_precomputed_signature(self):
        """Кешувати підпис нема куди: його неможливо передати ззовні.

        Динамічна перевірка вище доводить поведінку сьогоднішнього коду;
        ця -- відсутність самої можливості передати старий підпис із черги.
        """
        import inspect

        from app.services.webhook_dispatcher import dispatch_partner_event

        params = set(inspect.signature(dispatch_partner_event).parameters)

        assert not params & {'timestamp', 'signature', 'signed_body', 'headers'}

    def test_queue_row_stores_neither_signature_nor_timestamp(self):
        """І в рядку черги, який переживає спроби, їх теж немає."""
        from app.models.webhook_delivery import WebhookDelivery

        columns = set(WebhookDelivery.__table__.columns.keys())

        assert not columns & {'signature', 'signed_at', 'timestamp', 'signed_body'}
