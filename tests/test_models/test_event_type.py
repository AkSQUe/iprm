"""Довідник видів заходів: цілісність сидінгу і переклади."""
from uuid import uuid4

from app.extensions import db
from app.models.event_type import SEED_ROWS, EventType

LEGACY = {'course', 'webinar', 'conference'}


def test_seed_has_twelve_active_and_three_legacy():
    active = [r for r in SEED_ROWS if r['is_active']]
    legacy = [r for r in SEED_ROWS if not r['is_active']]
    assert len(active) == 12
    assert {r['code'] for r in legacy} == LEGACY


def test_seed_codes_unique_and_active_order_is_dense():
    codes = [r['code'] for r in SEED_ROWS]
    assert len(codes) == len(set(codes))
    active = [r for r in SEED_ROWS if r['is_active']]
    assert [r['sort_order'] for r in active] == list(range(1, 13))


def test_seed_keeps_existing_codes_active():
    """seminar і masterclass уже стоять у даних -- вони мусять лишитись
    активними, інакше наявні курси втратять чинний тип."""
    active = {r['code'] for r in SEED_ROWS if r['is_active']}
    assert {'seminar', 'masterclass'} <= active


def test_every_seed_row_carries_both_cases_in_lower():
    for row in SEED_ROWS:
        assert row['name_accusative'], row['code']
        assert row['name_genitive'], row['code']
        assert row['name_accusative'][0].islower(), row['code']
        assert row['name_genitive'][0].islower(), row['code']
        assert row['name'][0].isupper(), row['code']


def test_translation_falls_back_to_ukrainian(db_session):
    row = EventType(code=f't-{uuid4().hex[:6]}', name='Тест', sort_order=99)
    db.session.add(row)
    db.session.flush()

    assert row.t('name') == 'Тест'
    assert row.t('name', 'en') == 'Тест'

    row.set_translation('en', 'name', 'Test')
    assert row.t('name', 'en') == 'Test'
