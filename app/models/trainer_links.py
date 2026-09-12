"""Таблиці звʼязку «захід -- тренери» з позицією.

Окремий модуль, а не всередині course.py чи course_instance.py: обидві
таблиці потрібні обом моделям, і оголошення в будь-якій із них дало б
циклічний імпорт.

Складений PK замість сурогатного id дає унікальність пари даром: одного
тренера двічі в один захід не додати. ON DELETE CASCADE, а не SET NULL:
рядок «у заходу є тренер, і це ніхто» сенсу не має.

position без UNIQUE(захід, position) -- обмеження заважало б перестановці
(проміжний стан завжди має дублікат), а нумерує позиції одна функція,
set_trainers, з нуля й без пропусків.
"""
from app.extensions import db

course_trainers = db.Table(
    'course_trainers',
    db.Column('course_id', db.BigInteger,
              db.ForeignKey('courses.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('trainer_id', db.BigInteger,
              db.ForeignKey('trainers.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('position', db.Integer, nullable=False),
    # Окремий індекс на тренера -- для запиту у зворотному напрямку
    # («заходи цього тренера»); складений PK для нього не годиться.
    db.Index('ix_course_trainers_trainer_id', 'trainer_id'),
)

course_instance_trainers = db.Table(
    'course_instance_trainers',
    db.Column('instance_id', db.BigInteger,
              db.ForeignKey('course_instances.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('trainer_id', db.BigInteger,
              db.ForeignKey('trainers.id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('position', db.Integer, nullable=False),
    db.Index('ix_course_instance_trainers_trainer_id', 'trainer_id'),
)
