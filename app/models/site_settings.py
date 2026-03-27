from app.extensions import db
from app.models.mixins import TimestampMixin


class SiteSettings(TimestampMixin, db.Model):
    """Singleton: site-wide settings stored in DB, managed via admin panel."""
    __tablename__ = 'site_settings'

    id = db.Column(db.Integer, primary_key=True, default=1)

    # Company info
    company_name = db.Column(db.String(100), default='ІПРМ')
    company_full_name = db.Column(
        db.String(500),
        default='Інститут Плазмотерапії та Регенеративної Медицини',
    )
    company_legal_name = db.Column(db.String(500), default='ПО "ІПРМ"')
    edrpou = db.Column(db.String(20), default='45871060')

    # Contacts
    phone_primary = db.Column(db.String(50), default='+380670050707')
    phone_secondary = db.Column(db.String(50), default='+380 96 090 0007')
    email = db.Column(db.String(255), default='office@iprm.com')
    address = db.Column(
        db.Text,
        default='02002, Україна, місто Київ, вулиця Микільсько-слобідська, будинок 2б, квартира 246',
    )
    city = db.Column(db.String(200), default='Київ, Україна')

    # Social media
    facebook_url = db.Column(
        db.String(500),
        default='https://www.facebook.com/profile.php?id=61583812599479',
    )
    instagram_url = db.Column(
        db.String(500),
        default='https://www.instagram.com/Plasmotherapy/',
    )
    telegram_url = db.Column(db.String(500), default='')

    # Business
    business_hours = db.Column(db.String(200), default='Пн-Пт: 09:00-18:00')
    website_url = db.Column(db.String(500), default='https://iprm.space')

    @classmethod
    def get(cls):
        """Get or create singleton settings row."""
        settings = cls.query.get(1)
        if not settings:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    def __repr__(self):
        return f'<SiteSettings {self.company_name}>'
