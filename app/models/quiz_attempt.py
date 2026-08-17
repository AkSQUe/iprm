"""Спроба проходження тесту -- одна на кнопку «Почати», з фіксованим набором.

Набір питань і порядок варіантів фіксуються НА СТАРТІ спроби і живуть у рядку.
Інакше кожне перезавантаження сторінки перемішувало б питання, і людина, яка
відповіла на сім із десяти, побачила б інший тест. Оскільки спроб лише три,
втрачений прогрес коштував би дорого.

Відповіді пишуться інкрементально (`submitted_answers`), тож закрита вкладка чи
втрачений зв'язок не з'їдають спробу -- учасник повертається й продовжує.

`passing_score` і `total` -- знімки на момент спроби: адмін може змінити
налаштування тесту, і вже зіграна спроба не мусить від цього переоцінюватись.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK, utcnow


class QuizAttempt(TimestampMixin, db.Model):
    __tablename__ = 'quiz_attempts'

    id = db.Column(BigIntPK, primary_key=True)
    registration_id = db.Column(
        db.BigInteger,
        db.ForeignKey('event_registrations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # Денормалізовано (як user_id у Certificate): кабінет і адмінка питають
    # спроби користувача без джойна через реєстрацію.
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    # SET NULL, а не CASCADE: видалений тест не має стирати історію складань.
    quiz_id = db.Column(
        db.BigInteger,
        db.ForeignKey('course_quizzes.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    attempt_number = db.Column(db.Integer, nullable=False)

    # Питання спроби в зафіксованому порядку: [question_id, ...].
    question_ids = db.Column(db.JSON, nullable=False, default=list)
    # Порядок варіантів на кожне питання: {"<question_id>": [3, 0, 2, 1], ...},
    # де значення -- індекси у полі answers питання. Ключі JSON -- рядки.
    answer_order = db.Column(db.JSON, nullable=False, default=dict)
    # Відповіді учасника: {"<question_id>": <позиція у перемішаному списку>}.
    submitted_answers = db.Column(db.JSON, nullable=False, default=dict)

    score = db.Column(db.Integer)
    total = db.Column(db.Integer, nullable=False)
    passing_score = db.Column(db.Integer, nullable=False)
    passed = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
    )

    started_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utcnow,
    )
    # NULL -- спроба ще в процесі (саму її і продовжуємо).
    submitted_at = db.Column(db.DateTime(timezone=True))

    registration = db.relationship(
        'EventRegistration', back_populates='quiz_attempts',
    )
    user = db.relationship('User', foreign_keys=[user_id])
    quiz = db.relationship(
        'CourseQuiz', foreign_keys=[quiz_id], back_populates='attempts',
    )

    __table_args__ = (
        db.UniqueConstraint(
            'registration_id', 'attempt_number',
            name='uq_quiz_attempts_registration_number',
        ),
        db.CheckConstraint('attempt_number >= 1', name='ck_quiz_attempts_number'),
        db.CheckConstraint(
            'score IS NULL OR score >= 0', name='ck_quiz_attempts_score',
        ),
        db.CheckConstraint('total >= 1', name='ck_quiz_attempts_total'),
    )

    @property
    def is_finished(self):
        return self.submitted_at is not None

    @property
    def answered_count(self):
        return len(self.submitted_answers or {})

    def ordered_answer_indexes(self, question_id):
        """Порядок варіантів для питання у цій спробі."""
        return (self.answer_order or {}).get(str(question_id)) or []

    def chosen_position(self, question_id):
        """Позиція, яку обрав учасник (у перемішаному списку); None -- не обрав."""
        return (self.submitted_answers or {}).get(str(question_id))

    def __repr__(self):
        state = 'finished' if self.is_finished else 'in-progress'
        return (
            f'<QuizAttempt reg={self.registration_id} '
            f'#{self.attempt_number} {state} score={self.score}>'
        )
