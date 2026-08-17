"""Тестування учасників після заходу: налаштування тесту, банк питань, спроби.

Учасник отримує сертифікат з балами БПР, лише коли виконав дві умови: заповнив
анкету МОЗ №725 (`MedicalProfile.is_complete`) і склав тест. Гейт і оцінювання --
`app/services/quiz_service.py`; тут лише дані.

Прив'язка тесту -- XOR: або до курсу (базовий набір, спільний для всіх
проведень), або до конкретного проведення (перевизначення). Курс проводиться
багато разів -- «Базовий курс з плазмотерапії» вже мав 12 проведень -- тож
тримати питання на проведенні означало б копіювати їх щоразу. Перевизначення
лишається для випадків, коли окреме проведення читалось за іншою програмою.

Варіанти відповідей -- JSON-список на питанні, а не окрема таблиця. Причини:
  * прецедент у проєкті -- `ProgramBlock.items` і `Course.faq`;
  * механізм перекладів це вже вміє: `app.i18n.walk_leaves` обходить лише
    str-листя, тож булеве `is_correct` він ігнорує сам собою, а макрос
    `json_panes` в адмінці рендерить мовні вкладки для JSON-списку;
  * за варіантами ми ніколи не фільтруємо й не агрегуємо.

Ключ тексту варіанта мусить називатися саме `text`: ключі з
`app.i18n.TECHNICAL_KEYS` (зокрема `code`, `type`, `id`) з перекладу виключені.
"""
from sqlalchemy.orm import validates

from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK

# Скільки варіантів відповіді має питання. Формат фіксований: одне питання --
# чотири варіанти, рівно один правильний.
ANSWERS_PER_QUESTION = 4

DEFAULT_QUESTIONS_PER_ATTEMPT = 10
DEFAULT_PASSING_SCORE = 8
DEFAULT_MAX_ATTEMPTS = 3


class CourseQuiz(TimestampMixin, TranslatableMixin, db.Model):
    __tablename__ = 'course_quizzes'

    # Вступний текст читає учасник, а сторінка тесту локалізована (uk/ru/en),
    # тож він мусить перекладатись -- як і самі питання.
    __translatable__ = ('intro',)

    id = db.Column(BigIntPK, primary_key=True)

    # Рівно одне з двох заповнене -- гарантує ck_course_quizzes_owner.
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    instance_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_instances.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )

    # Скільки питань тягнемо з банку на одну спробу і скільки з них треба
    # правильних. Поріг тримаємо КІЛЬКІСТЮ, а не відсотком: замовник формулює
    # правило як «хоча б 8 з 10», і округлення відсотка тут лише плутало б.
    questions_per_attempt = db.Column(
        db.Integer, nullable=False,
        default=DEFAULT_QUESTIONS_PER_ATTEMPT,
        server_default=str(DEFAULT_QUESTIONS_PER_ATTEMPT),
    )
    passing_score = db.Column(
        db.Integer, nullable=False,
        default=DEFAULT_PASSING_SCORE,
        server_default=str(DEFAULT_PASSING_SCORE),
    )
    max_attempts = db.Column(
        db.Integer, nullable=False,
        default=DEFAULT_MAX_ATTEMPTS,
        server_default=str(DEFAULT_MAX_ATTEMPTS),
    )
    shuffle_answers = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.true(),
    )

    # Вступний текст, який учасник читає перед стартом: правила заходу, на що
    # звернути увагу, посилання на матеріали. Без цього поля роздатка з умовами
    # тесту не мала де жити, і сторінка старту показувала лише згенеровані числа
    # («10 питань, потрібно 8»).
    intro = db.Column(db.Text)

    # Скільки днів після завершення заходу тест лишається відкритим.
    # NULL -- без обмеження (початкова поведінка: відкрився з початком заходу і
    # не закривався ніколи). 0 -- до кінця дня, коли захід завершився: саме так
    # правило сформульоване в роздатці учасникам («до 23:59 у день завершення»).
    #
    # Днями від дати заходу, а не абсолютною міткою: тест може належати КУРСУ,
    # спільному для десятка проведень, і одна дата на всіх там безглузда.
    deadline_days_after_end = db.Column(db.Integer)

    # Свідомо False за замовчуванням: щойно створений тест ще не має банку
    # питань, і відкривати його учасникам не можна.
    is_active = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
    )

    course = db.relationship('Course', foreign_keys=[course_id])
    instance = db.relationship('CourseInstance', foreign_keys=[instance_id])
    questions = db.relationship(
        'QuizQuestion',
        back_populates='quiz',
        cascade='all, delete-orphan',
        order_by='QuizQuestion.sort_order',
    )
    # БЕЗ delete-orphan: видалення тесту не має стирати історію складань, лише
    # від'єднати її (FK оголошено ondelete='SET NULL'). Зв'язок потрібен ще й
    # сторінці результатів в адмінці.
    attempts = db.relationship('QuizAttempt', back_populates='quiz')

    __table_args__ = (
        db.CheckConstraint(
            '(course_id IS NOT NULL AND instance_id IS NULL) OR '
            '(course_id IS NULL AND instance_id IS NOT NULL)',
            name='ck_course_quizzes_owner',
        ),
        db.CheckConstraint(
            'questions_per_attempt >= 1', name='ck_course_quizzes_per_attempt',
        ),
        db.CheckConstraint(
            'passing_score >= 1', name='ck_course_quizzes_passing_positive',
        ),
        db.CheckConstraint(
            'passing_score <= questions_per_attempt',
            name='ck_course_quizzes_passing_within',
        ),
        db.CheckConstraint(
            'max_attempts >= 1', name='ck_course_quizzes_max_attempts',
        ),
        db.CheckConstraint(
            'deadline_days_after_end IS NULL OR deadline_days_after_end >= 0',
            name='ck_course_quizzes_deadline_non_negative',
        ),
        # Один тест на курс і один на проведення. Partial-unique, бо друга
        # колонка у своєму рядку завжди NULL (той самий підхід, що в
        # uq_registrations_instance_place).
        db.Index(
            'uq_course_quizzes_course', 'course_id', unique=True,
            postgresql_where=db.text('course_id IS NOT NULL'),
            sqlite_where=db.text('course_id IS NOT NULL'),
        ),
        db.Index(
            'uq_course_quizzes_instance', 'instance_id', unique=True,
            postgresql_where=db.text('instance_id IS NOT NULL'),
            sqlite_where=db.text('instance_id IS NOT NULL'),
        ),
    )

    @property
    def active_questions(self):
        return [q for q in self.questions if q.is_active]

    @property
    def bank_size(self):
        return len(self.active_questions)

    @property
    def is_ready(self):
        """Банк достатній і кожне питання коректне.

        Окремо від `is_active`: адмін міг увімкнути тест, а потім вивести
        питання з банку. Гейт учасника питає саме `is_ready`, інакше людина
        побачила б тест, який неможливо скласти.
        """
        questions = self.active_questions
        return (
            len(questions) >= self.questions_per_attempt
            and all(q.is_valid for q in questions)
        )

    @property
    def owner_label(self):
        if self.instance_id:
            return 'проведення'
        return 'курс'

    def __repr__(self):
        owner = f'instance={self.instance_id}' if self.instance_id else f'course={self.course_id}'
        return f'<CourseQuiz {owner} bank={self.bank_size}>'


class QuizQuestion(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'quiz_questions'
    __translatable__ = ('text', 'answers')

    id = db.Column(BigIntPK, primary_key=True)
    quiz_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_quizzes.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    text = db.Column(db.Text, nullable=False)
    # [{"text": str, "is_correct": bool}, ...] -- рівно ANSWERS_PER_QUESTION
    # елементів, рівно один правильний.
    answers = db.Column(db.JSON, nullable=False, default=list)
    sort_order = db.Column(db.Integer, default=0)
    # Вивести питання з банку, не втрачаючи його та вже зіграні спроби, які на
    # нього посилаються.
    is_active = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.true(),
    )

    quiz = db.relationship('CourseQuiz', back_populates='questions')

    @validates('answers')
    def _normalize_answers(self, _key, value):
        """Привести варіанти до канонічного вигляду [{'text', 'is_correct'}].

        Нормалізуємо на рівні моделі, а не лише у формі: варіанти пишуться і з
        адмінки, і з сідів/скриптів, і мовчазна розбіжність у формі ключів
        зламала б і оцінювання, і переклади (walk_leaves шукає саме `text`).
        Валідність (4 варіанти / 1 правильний) перевіряє `is_valid` -- тут не
        кидаємо, щоб адмін міг зберегти чернетку з помилкою і побачити її у
        формі, а не 500.
        """
        normalized = []
        for item in value or []:
            if not isinstance(item, dict):
                continue
            text = (item.get('text') or '').strip()
            if not text:
                continue
            normalized.append({
                'text': text,
                'is_correct': bool(item.get('is_correct')),
            })
        return normalized

    @property
    def correct_index(self):
        """Індекс правильного варіанта; None -- питання некоректне."""
        found = [i for i, a in enumerate(self.answers or []) if a.get('is_correct')]
        return found[0] if len(found) == 1 else None

    @property
    def is_valid(self):
        return (
            len(self.answers or []) == ANSWERS_PER_QUESTION
            and self.correct_index is not None
            and bool((self.text or '').strip())
        )

    def answer_texts(self, translated=True):
        """Лише ТЕКСТИ варіантів -- те, що можна віддавати у шаблон.

        Правильність назовні не йде ніколи: інакше відповідь видно у HTML.
        """
        answers = self.t('answers') if translated else (self.answers or [])
        return [(a.get('text') or '') for a in answers or []]

    def __repr__(self):
        return f'<QuizQuestion {self.id} quiz={self.quiz_id}>'
