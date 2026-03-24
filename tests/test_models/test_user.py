from app.models.user import User


def test_user_creation(db_session):
    """Створення користувача з паролем."""
    user = User(email='Test@Example.com', password='secret123')
    db_session.add(user)
    db_session.flush()

    assert user.id is not None
    assert user.email == 'test@example.com'
    assert user.check_password('secret123')
    assert not user.check_password('wrong')
    assert user.is_active is True
    assert user.is_admin is False


def test_user_timestamps(db_session):
    """created_at та updated_at заповнюються автоматично."""
    user = User(email='ts@test.com', password='pass1234')
    db_session.add(user)
    db_session.flush()

    assert user.created_at is not None
    assert user.updated_at is not None
