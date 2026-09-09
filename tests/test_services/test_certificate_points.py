"""Ім'я файлу розетки балів БПР має відповідати показаному числу.

points_badge_url збирав ім'я файлу простою f-строкою навколо Decimal, тож
Decimal('9.00') шукав «9.00-points-BPR.webp», якого немає -- і дев'ятибальний
захід тихо отримував десятибальну розетку (фолбек на 10). Ім'я мусить іти
через той самий нормалізатор, що й показ балів людині (format_points).
"""
from decimal import Decimal

from app.services.certificate_service import points_badge_url


def test_badge_name_has_no_trailing_zeros(app, monkeypatch):
    seen = []

    def fake_exists(path):
        seen.append(path)
        return False

    monkeypatch.setattr('app.services.certificate_service.os.path.exists', fake_exists)
    with app.app_context():
        points_badge_url(Decimal('9.00'))
    assert any(p.endswith('9-points-BPR.webp') for p in seen)
    assert not any(p.endswith('9.00-points-BPR.webp') for p in seen)


def test_badge_name_keeps_fraction_with_dot(app, monkeypatch):
    seen = []
    monkeypatch.setattr(
        'app.services.certificate_service.os.path.exists',
        lambda p: seen.append(p) or False,
    )
    with app.app_context():
        points_badge_url(Decimal('7.50'))
    assert any(p.endswith('7.5-points-BPR.webp') for p in seen)
