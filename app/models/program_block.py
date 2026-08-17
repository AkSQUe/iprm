"""ProgramBlock -- блок програми навчання (заголовок + перелік пунктів).

Належить АБО офлайн-курсу (Course), АБО онлайн-курсу (OnlineCourse) -- рівно
одному з двох, що гарантує CHECK на рівні БД. Поліморфність тут свідома:
блок програми виглядає і редагується однаково для обох типів курсів, тож
дублювати сутність (або класти JSON-колонку на online_courses) означало б
два джерела правди для того самого -- і два редактори в адмінці.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, TranslatableMixin, BigIntPK


class ProgramBlock(TranslatableMixin, TimestampMixin, db.Model):
    __tablename__ = 'program_blocks'
    __translatable__ = ('heading', 'items')

    id = db.Column(BigIntPK, primary_key=True)
    course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('courses.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    online_course_id = db.Column(
        db.BigInteger,
        db.ForeignKey('online_courses.id', ondelete='CASCADE'),
        nullable=True,
        index=True,
    )
    heading = db.Column(db.String(200), nullable=False)
    items = db.Column(db.JSON, nullable=False, default=list)
    sort_order = db.Column(db.Integer, default=0)

    __table_args__ = (
        # Рівно один власник. Без цього блок-сирота мовчки випав би з обох
        # сторінок і лишився б у базі назавжди -- саме той клас помилки, який
        # шаблон не показує, а тест не ловить.
        db.CheckConstraint(
            '(course_id IS NULL) <> (online_course_id IS NULL)',
            name='ck_program_blocks_single_owner',
        ),
    )

    course = db.relationship('Course', back_populates='program_blocks')
    online_course = db.relationship('OnlineCourse', back_populates='program_blocks')

    @property
    def owner(self):
        """Курс-власник незалежно від типу -- для адмінки й редіректів."""
        return self.course or self.online_course

    def __repr__(self):
        return f'<ProgramBlock {self.heading}>'
