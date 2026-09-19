import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from tests.test_trainer_cabinet._factories import make_trainer, make_user


def test_active_trainer_requires_link_and_active():
    user = make_user()
    assert user.active_trainer is None
    trainer = make_trainer(user)
    db.session.expire(user)
    assert user.active_trainer.id == trainer.id
    trainer.is_active = False
    db.session.commit()
    db.session.expire(user)
    assert user.active_trainer is None


def test_user_linked_to_one_trainer_only():
    user = make_user()
    make_trainer(user)
    with pytest.raises(IntegrityError):
        make_trainer(user)
    db.session.rollback()


def test_profile_encrypts_sensitive_fields():
    trainer = make_trainer(make_user())
    profile = TrainerProfile(trainer_id=trainer.id)
    profile.fop_iban = 'UA213052990000026003006239637'
    profile.tax_id = '1234567890'
    db.session.add(profile)
    db.session.commit()
    raw = db.session.execute(db.text(
        'SELECT fop_iban, tax_id FROM trainer_profiles WHERE id = :id'),
        {'id': profile.id}).one()
    assert 'UA2130' not in raw[0]
    assert raw[1] != '1234567890'
    db.session.expire(profile)
    assert profile.fop_iban == 'UA213052990000026003006239637'
    assert trainer.profile.id == profile.id


def test_profile_is_complete():
    profile = TrainerProfile(
        full_name='Іваненко Іван', phone='+380671234567', email='i@test.com',
        registration_address='Київ',
    )
    assert not profile.is_complete
    profile.fop_iban = 'UA1'
    profile.fop_rnokpp = '1'
    profile.tax_id = '1'
    assert profile.is_complete


def test_mask():
    assert TrainerProfile.mask('') == ''
    assert TrainerProfile.mask('1234567890') == '•••• 7890'


def test_proposal_defaults_and_status_check():
    trainer = make_trainer(make_user())
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС крові', theses=['A'])
    db.session.add(p)
    db.session.commit()
    assert p.status == TrainerCourseProposal.DRAFT
    assert p.is_editable
    assert trainer.proposals.count() == 1
    p.status = 'bogus'
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_site_settings_trainer_fields():
    s = SiteSettings.get()
    assert s.trainer_contract_email == ''
    assert not s.has_trainer_contract
    s.trainer_contract_pdf = b'%PDF-1.4 test'
    s.trainer_contract_filename = 'Договір.pdf'
    db.session.commit()
    assert s.has_trainer_contract
