"""Тести публічного маршруту відписки (List-Unsubscribe one-click)."""
from app.extensions import db
from app.models.user import User


def _make_user(email='u@example.com', token='unsub-token-123', opt_out=False):
    u = User(email=email, email_opt_out=opt_out, unsubscribe_token=token)
    db.session.add(u)
    db.session.flush()
    return u


def test_invalid_token_returns_404(client):
    resp = client.get('/unsubscribe/nope-not-a-real-token')
    assert resp.status_code == 404


def test_get_shows_email(client):
    _make_user(email='show@example.com', token='tok-get')
    resp = client.get('/unsubscribe/tok-get')
    assert resp.status_code == 200
    assert b'show@example.com' in resp.data


def test_post_opts_out(client):
    u = _make_user(email='out@example.com', token='tok-post')
    resp = client.post('/unsubscribe/tok-post')
    assert resp.status_code == 200
    db.session.refresh(u)
    assert u.email_opt_out is True


def test_post_resubscribe(client):
    u = _make_user(email='back@example.com', token='tok-re', opt_out=True)
    resp = client.post('/unsubscribe/tok-re', data={'action': 'resubscribe'})
    assert resp.status_code == 200
    db.session.refresh(u)
    assert u.email_opt_out is False
