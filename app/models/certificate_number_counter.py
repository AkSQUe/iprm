"""Лічильник порядкових номерів сертифікатів -- окремий на кожен захід БПР.

Номер сертифіката -- РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ, і останній сегмент є порядковим
номером учасника В МЕЖАХ ЗАХОДУ: у кожного заходу нумерація своя, з 000001
(учасники) і 100001 (тренери, `LECTURER_NUMBER_OFFSET`). Захід тут -- саме
префікс номера РРРР-ПППП-ЗЗЗЗЗЗЗ, а не проведення: дві дати, що успадковують
від курсу той самий номер заходу, для реєстру БПР -- один захід, і нумерація в
них спільна.

Раніше лічильник був один на весь сайт (site_settings), тож номери заходу йшли
не з одиниці й перемішувались з сусідніми: сертифікат, дописаний до минулого
заходу після того, як видали наступний, отримував номер з-за його хвоста.

Лічильник монотонний, а не MAX(сегмент) по таблицях: видалення реєстрації
каскадом прибирає її сертифікат, і MAX віддав би той самий номер наступній
людині, хоча перший уже міг піти в реєстр. Значення видаються під блокуванням
рядка site_settings (certificate_service._lock_numbering).
"""
from app.extensions import db

# Види лічильника: у тренерів свій діапазон номерів.
COUNTER_KINDS = ('participant', 'lecturer')


class CertificateNumberCounter(db.Model):
    __tablename__ = 'certificate_number_counters'

    # РРРР-ПППП-ЗЗЗЗЗЗЗ (Certificate.format_prefix). Довжина -- із запасом під
    # незаповнені нулями або довші за норму номери провайдера й заходу.
    prefix = db.Column(db.String(64), primary_key=True)
    kind = db.Column(db.String(20), primary_key=True)
    # Останній виданий порядковий номер БЕЗ зсуву тренерського діапазону.
    last_value = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    __table_args__ = (
        db.CheckConstraint(
            "kind IN ('participant', 'lecturer')",
            name='ck_certificate_number_counters_kind',
        ),
    )

    def __repr__(self):
        return f'<CertificateNumberCounter {self.prefix} {self.kind}={self.last_value}>'
