"""Модифікатори бейджів черги вебхуків.

Регресія: `STATUS_BADGES` лежав у моделі, а властивості `status_badge` не
було -- шаблон звертався до неіснуючого атрибута, Jinja віддавала порожньо,
і в розмітку йшло `class="badge badge--"`. Усі чотири стани черги
малювались однаковою безбарвною таблеткою, і жоден тест цього не бачив:
сторінка віддавала 200, розмітка була валідна, просто без кольору.
"""
import pytest

from app.models.webhook_delivery import WebhookDelivery


@pytest.mark.parametrize('status,expected', [
    ('pending', 'pending'),
    ('sent', 'active'),
    ('retrying', 'warning'),
    ('failed', 'cancelled'),
])
def test_status_badge_maps_every_status(status, expected):
    assert WebhookDelivery(status=status).status_badge == expected


def test_status_badge_covers_every_allowed_status():
    """Перелік станів моделі й перелік бейджів не мають розходитись.

    Інакше новий стан тихо отримає дефолт і виглядатиме як `pending`.
    """
    assert set(WebhookDelivery.STATUS_BADGES) == {
        'pending', 'sent', 'retrying', 'failed'}


@pytest.mark.parametrize('action,expected', [
    ('created', 'active'),
    ('updated', 'format'),
    ('deleted', 'cancelled'),
])
def test_action_badge_maps_every_action(action, expected):
    assert WebhookDelivery(action=action).action_badge == expected


def test_badges_never_render_empty_modifier():
    """Жодне значення не сміє дати порожній модифікатор.

    Саме порожній хвіст (`badge--`) і був вадою: клас формально є, правила
    під нього немає ніде, таблетка лишається без тла.
    """
    for status in list(WebhookDelivery.STATUS_BADGES) + [None, 'unknown']:
        assert WebhookDelivery(status=status).status_badge
    for action in list(WebhookDelivery.ACTION_BADGES) + [None, 'unknown']:
        assert WebhookDelivery(action=action).action_badge
