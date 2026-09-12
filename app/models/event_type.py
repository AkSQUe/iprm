"""Довідник видів заходів БПР.

Вид заходу друкується в сертифікаті й іде у звітність, тож перелік має
збігатися з нормативною номенклатурою. Тримати його константою в коді
означало б деплой на кожну зміну номенклатури -- тому це таблиця з
власною сторінкою в адмінці.

Курс посилається сюди КОДОМ (courses.event_type -- рядок), а не через FK:
код уже їде в партнерське API та в xlsx, і заміна його на id зламала б
обидва контракти заради цілісності, яку тут дає заборона видаляти
вживаний рядок.

Тип, якого більше немає в номенклатурі, не видаляється й не
перемапується -- йому знімають is_active. Тоді він зникає з вибору, але
курси, де він уже стоїть, показуються як раніше.
"""
from app.extensions import db
from app.models.mixins import BigIntPK, TimestampMixin, TranslatableMixin


class EventType(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'event_types'
    __translatable__ = ('name',)

    id = db.Column(BigIntPK, primary_key=True)

    # Стабільний ключ. Саме його зберігає courses.event_type і віддає API.
    code = db.Column(db.String(30), unique=True, nullable=False)

    # Називний, з великої -- це бейдж на картці курсу.
    name = db.Column(db.String(120), nullable=False)

    # Відмінки друкуються всередині речення сертифіката, тож зберігаються
    # з малої. Знахідний: "успішно завершив(-ла) наукову конференцію".
    # Родовий: "тренера наукової конференції".
    name_accusative = db.Column(db.String(120))
    name_genitive = db.Column(db.String(120))

    sort_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    def __repr__(self):
        return f'<EventType {self.code}>'


# Канонічна номенклатура. Звідси сідається тестова схема (create_all не
# знає про міграції) і звідси ж копіювався сидінг міграції.
SEED_ROWS = (
    {'code': 'seminar', 'name': 'Семінар',
     'name_accusative': 'семінар', 'name_genitive': 'семінару',
     'sort_order': 1, 'is_active': True},
    {'code': 'scientific_conference', 'name': 'Наукова конференція',
     'name_accusative': 'наукову конференцію',
     'name_genitive': 'наукової конференції',
     'sort_order': 2, 'is_active': True},
    {'code': 'elearning_course', 'name': 'Електронний навчальний курс',
     'name_accusative': 'електронний навчальний курс',
     'name_genitive': 'електронного навчального курсу',
     'sort_order': 3, 'is_active': True},
    {'code': 'congress', 'name': 'Конгрес',
     'name_accusative': 'конгрес', 'name_genitive': 'конгресу',
     'sort_order': 4, 'is_active': True},
    {'code': 'practical_conference', 'name': 'Науково-практична конференція',
     'name_accusative': 'науково-практичну конференцію',
     'name_genitive': 'науково-практичної конференції',
     'sort_order': 5, 'is_active': True},
    {'code': 'symposium', 'name': 'Симпозіум',
     'name_accusative': 'симпозіум', 'name_genitive': 'симпозіуму',
     'sort_order': 6, 'is_active': True},
    {'code': 'convention', 'name': 'З\'їзд',
     'name_accusative': 'з\'їзд', 'name_genitive': 'з\'їзду',
     'sort_order': 7, 'is_active': True},
    {'code': 'simulation_training', 'name': 'Симуляційний тренінг',
     'name_accusative': 'симуляційний тренінг',
     'name_genitive': 'симуляційного тренінгу',
     'sort_order': 8, 'is_active': True},
    {'code': 'skills_training',
     'name': 'Тренінг з оволодіння практичними навичками',
     'name_accusative': 'тренінг з оволодіння практичними навичками',
     'name_genitive': 'тренінгу з оволодіння практичними навичками',
     'sort_order': 9, 'is_active': True},
    {'code': 'training', 'name': 'Тренінг',
     'name_accusative': 'тренінг', 'name_genitive': 'тренінгу',
     'sort_order': 10, 'is_active': True},
    {'code': 'masterclass', 'name': 'Майстер-клас',
     'name_accusative': 'майстер-клас', 'name_genitive': 'майстер-класу',
     'sort_order': 11, 'is_active': True},
    {'code': 'professional_school', 'name': 'Фахова (тематична) школа',
     'name_accusative': 'фахову (тематичну) школу',
     'name_genitive': 'фахової (тематичної) школи',
     'sort_order': 12, 'is_active': True},

    # Застарілі: у номенклатурі БПР їх немає, але вони стоять у наявних
    # курсах. Лишаються рядками, щоб ті курси не показували голий код.
    {'code': 'course', 'name': 'Курс',
     'name_accusative': 'курс', 'name_genitive': 'курсу',
     'sort_order': 90, 'is_active': False},
    {'code': 'webinar', 'name': 'Вебінар',
     'name_accusative': 'вебінар', 'name_genitive': 'вебінару',
     'sort_order': 91, 'is_active': False},
    {'code': 'conference', 'name': 'Конференція',
     'name_accusative': 'конференцію', 'name_genitive': 'конференції',
     'sort_order': 92, 'is_active': False},
)
