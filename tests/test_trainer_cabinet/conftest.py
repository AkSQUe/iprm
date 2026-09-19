import pytest

from tests.support.users import wipe_users


@pytest.fixture(autouse=True)
def _wipe_tc_users():
    yield
    from app.extensions import db
    from app.models.registration import EventRegistration
    from app.models.user import User
    ids = [u.id for u in User.query.filter(User.email.like('tc-%@test.com')).all()]
    if ids:
        EventRegistration.query.filter(EventRegistration.user_id.in_(ids)).delete(
            synchronize_session=False)
        db.session.commit()
    wipe_users('tc-')
