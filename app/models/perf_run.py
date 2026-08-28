"""Заміри швидкості завантаження сторінок (інструмент tools/perf/perf_check.py).

Заміри виконуються ПОЗА продом і надсилаються сюди по API. Причина: прод-VPS
має 1 ядро і 2 ГБ RAM без swap, тож headless-браузер конкурував би за CPU з
gunicorn -- сайт гальмував би для відвідувачів, а самі метрики міряли б
перевантажений сервер, а не сторінку. Адмінка -- лише переглядач історії.

PerfRun -- один прогін інструменту (набір сторінок x профілі).
PerfPageMetric -- метрики однієї сторінки в одному профілі всередині прогону.

Пороги бюджетів зберігаються В САМОМУ прогоні (PerfRun.budgets), а не в коді
застосунку: єдиним джерелом істини лишається інструмент (він же за ними
повертає код виходу в CI), а UI показує рівно ті межі, за якими рахувався
вердикт цього прогону.
"""
from app.extensions import db
from app.models.mixins import TimestampMixin, BigIntPK


VERDICT_OK = 'OK'
VERDICT_WARN = 'WARN'
VERDICT_FAIL = 'FAIL'
VERDICTS = (VERDICT_OK, VERDICT_WARN, VERDICT_FAIL)

# Порядок від найгіршого: використовується для зведення вердикту прогону.
_VERDICT_RANK = {VERDICT_FAIL: 2, VERDICT_WARN: 1, VERDICT_OK: 0}


def worst_verdict(verdicts):
    """Найгірший вердикт із набору. Порожній набір -> OK."""
    return max(verdicts, key=lambda v: _VERDICT_RANK.get(v, 0), default=VERDICT_OK)


# Вердикт малюється двома різними компонентами -- плашкою в таблиці й
# карткою-зрізом угорі, -- і кожен із них розкладався тернарником просто в
# розмітці: двічі в реєстрі прогонів, двічі в деталях. Четвертий вердикт
# з'явився б на екрані плашкою «OK».
VERDICT_BADGES = {
    VERDICT_OK: 'success',
    VERDICT_WARN: 'warning',
    VERDICT_FAIL: 'danger',
}

# Картка-зріз має ВЛАСНУ шкалу: `.admin-stat-card--warning` у цій системі
# синя (бере токен бейджа «Опубліковано»), а бурштинове «потребує уваги» --
# це `--alert`. Тому WARN тут не той самий модифікатор, що в плашці.
VERDICT_CARDS = {
    VERDICT_OK: 'success',
    VERDICT_WARN: 'alert',
    VERDICT_FAIL: 'danger',
}


class VerdictVisualsMixin:
    """Спільне для прогону й окремої сторінки: обидва мають колонку verdict."""

    @property
    def verdict_badge(self):
        """Модифікатор `.badge--*` під вердикт."""
        return VERDICT_BADGES.get(self.verdict, 'draft')

    @property
    def verdict_card(self):
        """Модифікатор `.admin-stat-card--*` під вердикт (див. VERDICT_CARDS)."""
        return VERDICT_CARDS.get(self.verdict, 'success')


class PerfRun(VerdictVisualsMixin, TimestampMixin, db.Model):
    __tablename__ = 'perf_runs'

    id = db.Column(BigIntPK, primary_key=True)
    # Час заміру за годинником вимірювальної машини (created_at -- час приймання).
    measured_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    base_url = db.Column(db.String(255), nullable=False, default='')
    # Мітка джерела: ім'я машини, "local", "ci" тощо -- щоб не плутати прогони
    # з різних каналів, бо абсолютні числа між ними непорівнянні.
    source = db.Column(db.String(100), nullable=False, default='')
    note = db.Column(db.String(255), nullable=False, default='')
    runs_per_page = db.Column(db.Integer, nullable=False, default=0)
    tool_version = db.Column(db.String(20), nullable=False, default='')

    verdict = db.Column(db.String(10), nullable=False, default=VERDICT_OK)
    pages_total = db.Column(db.Integer, nullable=False, default=0)
    pages_warn = db.Column(db.Integer, nullable=False, default=0)
    pages_fail = db.Column(db.Integer, nullable=False, default=0)

    # {"mobile": {"lcp": [2500, 4000], ...}, "desktop": {...}} -- межі WARN/FAIL.
    budgets = db.Column(db.JSON, nullable=False, default=dict)

    # lazy='select', а не 'selectin': список прогонів показує лише лічильники
    # (pages_total/warn/fail), тож selectin тягнув би сотні рядків метрик з
    # JSON-деталями на кожен перегляд списку. Там, де метрики потрібні
    # (сторінка деталей), вони довантажуються явним selectinload.
    pages = db.relationship(
        'PerfPageMetric',
        back_populates='run',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='PerfPageMetric.id',
    )

    __table_args__ = (
        db.CheckConstraint(
            "verdict IN ('OK', 'WARN', 'FAIL')", name='ck_perf_runs_verdict',
        ),
    )

    def __repr__(self):
        return f'<PerfRun {self.id} {self.base_url} {self.verdict}>'

    @property
    def profiles(self):
        """Профілі прогону в сталому порядку (desktop перед mobile)."""
        found = {p.profile for p in self.pages}
        ordered = [p for p in ('desktop', 'mobile') if p in found]
        return ordered + sorted(found - set(ordered))

    def pages_for(self, profile):
        return [p for p in self.pages if p.profile == profile]

    @property
    def worst_page(self):
        """Сторінка з найбільшим LCP -- з неї починають розбір."""
        scored = [p for p in self.pages if p.lcp is not None]
        return max(scored, key=lambda p: p.lcp) if scored else None

    def budget_for(self, profile, metric):
        """(WARN, FAIL) для метрики або None, якщо прогін меж не передав."""
        limits = (self.budgets or {}).get(profile, {}).get(metric)
        if isinstance(limits, (list, tuple)) and len(limits) == 2:
            return limits[0], limits[1]
        return None


class PerfPageMetric(VerdictVisualsMixin, TimestampMixin, db.Model):
    __tablename__ = 'perf_page_metrics'

    id = db.Column(BigIntPK, primary_key=True)
    run_id = db.Column(
        db.BigInteger, db.ForeignKey('perf_runs.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    profile = db.Column(db.String(20), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    url = db.Column(db.String(500), nullable=False, default='')
    status = db.Column(db.Integer)

    # Тайминги в мілісекундах; None -- метрику не вдалося зняти.
    ttfb = db.Column(db.Integer)
    fcp = db.Column(db.Integer)
    lcp = db.Column(db.Integer)
    tbt = db.Column(db.Integer)
    load_ms = db.Column(db.Integer)
    cls = db.Column(db.Float)

    total_transfer = db.Column(db.BigInteger, default=0)
    req_count = db.Column(db.Integer, default=0)
    doc_transfer = db.Column(db.BigInteger, default=0)
    doc_decoded = db.Column(db.BigInteger, default=0)

    verdict = db.Column(db.String(10), nullable=False, default=VERDICT_OK)
    # Вердикт по кожній метриці: {"lcp": "WARN", "tbt": "OK", ...}
    budget = db.Column(db.JSON, nullable=False, default=dict)
    # Ресурсний зріз: by_type, heaviest, uncompressed, headers.
    details = db.Column(db.JSON, nullable=False, default=dict)
    # Заповнюється, якщо сторінку не вдалося виміряти.
    error = db.Column(db.String(255), nullable=False, default='')

    run = db.relationship('PerfRun', back_populates='pages')

    __table_args__ = (
        db.CheckConstraint(
            "verdict IN ('OK', 'WARN', 'FAIL')", name='ck_perf_page_metrics_verdict',
        ),
    )

    def __repr__(self):
        return f'<PerfPageMetric {self.profile}:{self.path} {self.verdict}>'

    @property
    def key(self):
        return f'{self.profile}:{self.path}'

    @property
    def is_measured(self):
        return not self.error

    @property
    def headers(self):
        return (self.details or {}).get('headers', {})

    @property
    def heaviest(self):
        return (self.details or {}).get('heaviest', [])

    @property
    def uncompressed(self):
        return (self.details or {}).get('uncompressed', [])

    @property
    def by_type_sorted(self):
        """[(тип, {count, transfer}), ...] за спаданням ваги."""
        by_type = (self.details or {}).get('by_type', {}) or {}
        return sorted(by_type.items(), key=lambda kv: -(kv[1] or {}).get('transfer', 0))
