"""POST /materials/<token>/confirm -- trainer confirms the prepared kit
without logging in (signed token, public route). See
app/main/routes.py:trainer_materials_confirm.
"""
from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem,
)
from app.models.trainer import Trainer


def _make_instance(slug_suffix='n'):
    trainer = Trainer(full_name='Іван Тренер', slug=f'trainer-conf-{slug_suffix}',
                      email=f'trainer-conf-{slug_suffix}@example.com')
    db.session.add(trainer)
    course = Course(title='Плазмотерапія', slug=f'course-conf-{slug_suffix}', trainer=trainer)
    db.session.add(course)
    db.session.flush()
    now = datetime.now(timezone.utc)
    inst = CourseInstance(
        course_id=course.id, trainer_id=trainer.id,
        start_date=now + timedelta(days=2), end_date=now + timedelta(days=3),
        location='Київ',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _make_reservation(inst, slug_suffix='n'):
    res = MaterialReservation(instance_id=inst.id, external_ref=f'iprm-instance-{inst.id}')
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(
        sku='NDL-21', name='Голка 21G', quantity_reserved=5))
    db.session.flush()
    return res


def _token(app, inst_id):
    from app.services import material_reservation_service as mrs
    with app.app_context():
        return mrs.make_trainer_token(inst_id)


def test_confirm_sets_timestamp_and_comment(app, client):
    inst = _make_instance(slug_suffix='ok')
    res = _make_reservation(inst, slug_suffix='ok')
    token = _token(app, inst.id)

    r = client.post(f'/materials/{token}/confirm', data={'comment': 'все на місці'})
    assert r.status_code in (200, 302)

    updated = db.session.get(MaterialReservation, res.id)
    assert updated.trainer_confirmed_at is not None
    assert updated.trainer_comment == 'все на місці'


def test_confirm_bad_token_404(client):
    r = client.post('/materials/not-a-real-token/confirm', data={'comment': 'x'})
    assert r.status_code == 404


def test_confirm_without_reservation_404(app, client):
    inst = _make_instance(slug_suffix='noreserv')
    token = _token(app, inst.id)
    r = client.post(f'/materials/{token}/confirm', data={'comment': 'x'})
    assert r.status_code == 404


def test_reconfirm_updates_comment_without_duplicating(app, client):
    inst = _make_instance(slug_suffix='again')
    res = _make_reservation(inst, slug_suffix='again')
    token = _token(app, inst.id)

    client.post(f'/materials/{token}/confirm', data={'comment': 'перший коментар'})
    first = db.session.get(MaterialReservation, res.id)
    first_confirmed_at = first.trainer_confirmed_at
    assert first_confirmed_at is not None

    r = client.post(f'/materials/{token}/confirm', data={'comment': 'ще треба голок'})
    assert r.status_code in (200, 302)

    second = db.session.get(MaterialReservation, res.id)
    assert second.trainer_comment == 'ще треба голок'
    # Idempotent: the original confirmation time does not move.
    assert second.trainer_confirmed_at == first_confirmed_at


def test_confirmation_visible_on_the_page_after_confirming(app, client):
    inst = _make_instance(slug_suffix='visible')
    _make_reservation(inst, slug_suffix='visible')
    token = _token(app, inst.id)

    client.post(f'/materials/{token}/confirm', data={'comment': ''})
    page = client.get(f'/materials/{token}')
    assert page.status_code == 200
    assert 'Підтверджено'.encode('utf-8') in page.data
