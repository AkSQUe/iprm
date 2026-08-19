"""Ліди з Meta Lead Ads: сира черга подій, розібрані заявки, налаштування

Revision ID: meta_leads_20260819
Revises: refund_requests_20260819
Create Date: 2026-08-19 12:00:00.000000

Дві таблиці, а не одна. `meta_lead_events` -- те, що прийшло вебхуком або
знайшлось звіркою: Meta приносить ЛИШЕ ідентифікатор ліда, тож рядок тут
означає «треба сходити в Graph API». `meta_leads` -- результат розбору:
нормалізовані поля, зв'язок із контактом, стан обробки менеджером. Строки
життя різні: заявку менеджер може видалити (тестова, вимога людини), сиру
подію -- ніколи, бо саме вона тримає ідемпотентність. Одна таблиця на
двох означала б CHECK із двох взаємовиключних форм і рядок, який
одночасно і «ще не забрано», і «вже закрито менеджером».

UNIQUE на `leadgen_id` в ОБОХ таблицях -- не оздоба, а єдина реальна
перешкода дублям: Meta повторює доставку при будь-якому сумніві
(таймаут, 5xx, подеколи й після успішної відповіді), а звірка навмисно
перечитує ті самі 48 годин. Без унікальності кожен такий повтор давав би
другу картку того самого клієнта.

FK на `users` скрізь ondelete='SET NULL', а не CASCADE: видалення контакту
не має стирати факт, що реклама привела заявку -- інакше зникає підстава
для звірки витрат на кампанію. Заявка лишається, лише втрачає прив'язку.

`meta_leads.created_time` NOT NULL, бо від нього рахується час очікування,
а лід, який неможливо пріоритезувати, у цьому списку не має сенсу.

Розширення двох CHECK -- `email_logs.trigger` і
`notification_rules.event_type` -- новим значенням 'meta_lead'. У проєкті
є прецедент протилежного рішення (B2B-заявка перевикористовує
'course_request'), але тут семантично близького типу немає, а головне --
моніторинг лідів мусить вмикатись окремо: адмін, який вимкнув шум про
запити на курси, разом із ним вимкнув би й сигнал «реклама третій день
ллє в порожнечу». PostgreSQL не вміє ALTER CONSTRAINT для CHECK, тож
DROP + ADD, як у notif_materials_20260708 і email_referral_trigger_20260714.

Колонки `meta_*` у `site_settings`: App Secret, verify token і Page Access
Token лежать Fernet-зашифрованими (звідси 500 і 2000 символів на короткі
за змістом значення) -- це секрети з доступом до персональних даних чужих
людей. У env їх тримати не можна: ротація вимагала б деплою і рестарту, а
критерій приймання N8 вимагає протилежного.

Батько -- `refund_requests_20260819`, а не `refunds_20260819`, як
планувалось: черга незакомічених міграцій повернень доросла ще на одну.
Помилка тут дає два alembic head-и і падіння `flask db upgrade`.
"""
from alembic import op
import sqlalchemy as sa


revision = 'meta_leads_20260819'
down_revision = 'refund_requests_20260819'
branch_labels = None
depends_on = None


# Перелік значень CHECK до і після цієї міграції. Тримаємо повними
# літералами, а не конкатенацією зі старого: так у diff видно точний стан
# констрейнта на кожній ревізії, і downgrade не залежить від того, що
# хтось прочитав правильний файл.
_TRIGGERS_OLD = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', 'test')"
)
_TRIGGERS_NEW = (
    "trigger IN ('registration', 'payment', 'reminder', 'status_change', "
    "'email_confirm', 'course_request', 'certificate', 'blog_comment', "
    "'password_reset', 'backup_failure', 'materials', 'referral', "
    "'meta_lead', 'test')"
)

_EVENT_TYPES_OLD = (
    "event_type IN ('registration', 'payment', 'course_request', "
    "'status_change', 'materials')"
)
_EVENT_TYPES_NEW = (
    "event_type IN ('registration', 'payment', 'course_request', "
    "'status_change', 'materials', 'meta_lead')"
)


def upgrade():
    # --- розібрані заявки ---
    # Створюється першою: на неї посилається lead_id у черзі подій.
    op.create_table(
        'meta_leads',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),

        # Ідентифікатори Meta -- рядки, а не числа: вони 64-бітні й іноді
        # приходять із провідними нулями, тож int їх мовчки псує.
        sa.Column('leadgen_id', sa.String(length=64), nullable=False),
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=False),

        sa.Column('page_id', sa.String(length=64), nullable=True),
        sa.Column('form_id', sa.String(length=64), nullable=True),
        sa.Column('form_name', sa.String(length=255), nullable=True),
        sa.Column('campaign_id', sa.String(length=64), nullable=True),
        sa.Column('campaign_name', sa.String(length=255), nullable=True),
        sa.Column('adset_id', sa.String(length=64), nullable=True),
        sa.Column('adset_name', sa.String(length=255), nullable=True),
        sa.Column('ad_id', sa.String(length=64), nullable=True),
        sa.Column('ad_name', sa.String(length=255), nullable=True),
        sa.Column('platform', sa.String(length=10), nullable=True),
        sa.Column('is_organic', sa.Boolean(), nullable=False,
                  server_default=sa.false()),

        # Відповіді як їх віддала Meta. Набір питань змінюється щокампанії,
        # тож окремі колонки під кожне питання застаріли б раніше, ніж
        # доїхала б міграція.
        sa.Column('field_data', sa.JSON(), nullable=False),
        sa.Column('raw_lead', sa.JSON(), nullable=True),

        sa.Column('first_name', sa.String(length=120), nullable=True),
        sa.Column('last_name', sa.String(length=120), nullable=True),
        sa.Column('full_name', sa.String(length=255), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone_raw', sa.String(length=50), nullable=True),
        # Канонічна форма для зіставлення. NULL = номер не розпізнано.
        sa.Column('phone_e164', sa.String(length=16), nullable=True),

        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('match_method', sa.String(length=20), nullable=False,
                  server_default='none'),

        sa.Column('needs_attention', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('attention_reason', sa.Text(), nullable=True),
        sa.Column('conflict_user_id', sa.BigInteger(), nullable=True),
        # Пошта з ліда, що не збіглася з поштою контакту. Не перезаписує
        # users.email -- це логін і унікальний ключ.
        sa.Column('alt_email', sa.String(length=255), nullable=True),

        sa.Column('is_repeat', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('is_test', sa.Boolean(), nullable=False,
                  server_default=sa.false()),

        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='new'),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('first_touch_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_touch_by', sa.BigInteger(), nullable=True),

        # М'яке видалення: тестові заявки прибирають одним кліком, з undo.
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['conflict_user_id'], ['users.id'],
                                ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['first_touch_by'], ['users.id'],
                                ondelete='SET NULL'),
        sa.CheckConstraint("status IN ('new', 'in_work', 'closed', 'dismissed')",
                           name='ck_meta_leads_status'),
        sa.CheckConstraint(
            "match_method IN ('phone', 'email', 'created', 'none')",
            name='ck_meta_leads_match_method'),
    )
    op.create_index('ix_meta_leads_leadgen_id', 'meta_leads', ['leadgen_id'],
                    unique=True)
    op.create_index('ix_meta_leads_created_time', 'meta_leads', ['created_time'])
    op.create_index('ix_meta_leads_form_id', 'meta_leads', ['form_id'])
    op.create_index('ix_meta_leads_campaign_id', 'meta_leads', ['campaign_id'])
    op.create_index('ix_meta_leads_email', 'meta_leads', ['email'])
    op.create_index('ix_meta_leads_phone_e164', 'meta_leads', ['phone_e164'])
    op.create_index('ix_meta_leads_user_id', 'meta_leads', ['user_id'])
    op.create_index('ix_meta_leads_needs_attention', 'meta_leads',
                    ['needs_attention'])
    op.create_index('ix_meta_leads_is_repeat', 'meta_leads', ['is_repeat'])
    op.create_index('ix_meta_leads_is_test', 'meta_leads', ['is_test'])
    op.create_index('ix_meta_leads_status', 'meta_leads', ['status'])
    op.create_index('ix_meta_leads_deleted_at', 'meta_leads', ['deleted_at'])
    # Головний запит адмінки: нові заявки за спаданням часу подання.
    op.create_index('ix_meta_leads_status_created', 'meta_leads',
                    ['status', 'created_time'])

    # --- сира черга подій ---
    op.create_table(
        'meta_lead_events',
        sa.Column('id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'),
                  primary_key=True),

        sa.Column('leadgen_id', sa.String(length=64), nullable=False),
        sa.Column('page_id', sa.String(length=64), nullable=True),
        sa.Column('form_id', sa.String(length=64), nullable=True),
        sa.Column('ad_id', sa.String(length=64), nullable=True),

        # Час створення ліда за версією Meta -- не час прийому вебхука.
        sa.Column('created_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),

        # Повний value з changes[]. Саме він -- страховка на випадок
        # помилки в логіці розбору: переграти можна лише з оригіналу.
        sa.Column('raw_payload', sa.JSON(), nullable=False),

        sa.Column('source', sa.String(length=20), nullable=False,
                  server_default='webhook'),
        sa.Column('status', sa.String(length=20), nullable=False,
                  server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),

        # SET NULL, а не CASCADE: видалення заявки не сміє знести подію --
        # без неї повторна доставка того самого leadgen_id воскресила б
        # щойно видалену картку.
        sa.Column('lead_id', sa.BigInteger(), nullable=True),

        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(['lead_id'], ['meta_leads.id'],
                                ondelete='SET NULL'),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'retrying', 'done', "
            "'skipped', 'failed')",
            name='ck_meta_lead_events_status'),
        sa.CheckConstraint("source IN ('webhook', 'reconcile', 'manual')",
                           name='ck_meta_lead_events_source'),
        sa.CheckConstraint('attempts >= 0', name='ck_meta_lead_events_attempts'),
    )
    op.create_index('ix_meta_lead_events_leadgen_id', 'meta_lead_events',
                    ['leadgen_id'], unique=True)
    op.create_index('ix_meta_lead_events_page_id', 'meta_lead_events', ['page_id'])
    op.create_index('ix_meta_lead_events_form_id', 'meta_lead_events', ['form_id'])
    op.create_index('ix_meta_lead_events_created_time', 'meta_lead_events',
                    ['created_time'])
    op.create_index('ix_meta_lead_events_source', 'meta_lead_events', ['source'])
    op.create_index('ix_meta_lead_events_status', 'meta_lead_events', ['status'])
    op.create_index('ix_meta_lead_events_next_retry_at', 'meta_lead_events',
                    ['next_retry_at'])
    op.create_index('ix_meta_lead_events_lead_id', 'meta_lead_events', ['lead_id'])
    # Вибірка воркера: що зараз готове до спроби.
    op.create_index('ix_meta_lead_events_status_retry', 'meta_lead_events',
                    ['status', 'next_retry_at'])

    # --- налаштування інтеграції ---
    with op.batch_alter_table('site_settings') as batch:
        batch.add_column(sa.Column(
            'meta_leads_enabled', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            'meta_app_id', sa.String(length=50), nullable=False,
            server_default='',
        ))
        # Fernet-шифротекст, звідси 500 символів на 32-символьний секрет.
        batch.add_column(sa.Column(
            'meta_app_secret', sa.String(length=500), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_app_secret_set_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_verify_token', sa.String(length=500), nullable=True,
            server_default='',
        ))
        # Page token довший за решту секретів навіть до шифрування.
        batch.add_column(sa.Column(
            'meta_page_token', sa.String(length=2000), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_page_token_set_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_page_id', sa.String(length=64), nullable=False,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_page_name', sa.String(length=255), nullable=False,
            server_default='',
        ))
        # Версія Graph API у налаштуваннях, а не в константі: Meta виводить
        # версії з ужитку за розкладом, і підняти її треба вміти без релізу.
        batch.add_column(sa.Column(
            'meta_graph_version', sa.String(length=10), nullable=False,
            server_default='v21.0',
        ))
        # 48 годин глибини звірки -- запас на вихідні: збій у п'ятницю
        # ввечері помічають у понеділок, а Meta тримає ліди 90 днів.
        batch.add_column(sa.Column(
            'meta_reconcile_interval_minutes', sa.Integer(), nullable=False,
            server_default='30',
        ))
        batch.add_column(sa.Column(
            'meta_reconcile_lookback_hours', sa.Integer(), nullable=False,
            server_default='48',
        ))
        batch.add_column(sa.Column(
            'meta_silence_alert_hours', sa.Integer(), nullable=False,
            server_default='24',
        ))
        batch.add_column(sa.Column(
            'meta_error_alert_threshold', sa.Integer(), nullable=False,
            server_default='5',
        ))
        # Режим тестування: Graph API не віддає прапорця «це тест», тож
        # позначку ставимо самі -- усе, що прийшло при увімкненому режимі.
        batch.add_column(sa.Column(
            'meta_test_mode', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column(
            'meta_test_mode_since', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_last_lead_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_last_webhook_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_last_reconcile_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_last_reconcile_status', sa.String(length=20), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_last_reconcile_error', sa.Text(), nullable=True,
            server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_token_checked_at', sa.DateTime(timezone=True), nullable=True,
        ))
        # NULL = ще не перевіряли; False = токен відкликаний чи протух.
        batch.add_column(sa.Column(
            'meta_token_valid', sa.Boolean(), nullable=True,
        ))
        # NULL = безстроковий (Meta віддає expires_at=0 для page token).
        batch.add_column(sa.Column(
            'meta_token_expires_at', sa.DateTime(timezone=True), nullable=True,
        ))
        batch.add_column(sa.Column(
            'meta_token_error', sa.Text(), nullable=True, server_default='',
        ))
        batch.add_column(sa.Column(
            'meta_alert_sent_at', sa.DateTime(timezone=True), nullable=True,
        ))

    # --- новий тип події для листів моніторингу ---
    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs',
                               _TRIGGERS_NEW)

    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _EVENT_TYPES_NEW)


def downgrade():
    # Перед звуженням CHECK прибираємо рядки з новим значенням, інакше
    # констрейнт не створиться. Для email_logs журнал листа лишається --
    # обнуляємо лише тип; правило сповіщень зникає цілком.
    op.drop_constraint('ck_notification_rules_event_type', 'notification_rules',
                       type_='check')
    op.execute("DELETE FROM notification_rules WHERE event_type = 'meta_lead'")
    op.create_check_constraint('ck_notification_rules_event_type',
                               'notification_rules', _EVENT_TYPES_OLD)

    op.drop_constraint('ck_email_logs_trigger', 'email_logs', type_='check')
    op.execute("UPDATE email_logs SET trigger = NULL WHERE trigger = 'meta_lead'")
    op.create_check_constraint('ck_email_logs_trigger', 'email_logs',
                               _TRIGGERS_OLD)

    with op.batch_alter_table('site_settings') as batch:
        for column in (
            'meta_alert_sent_at',
            'meta_token_error',
            'meta_token_expires_at',
            'meta_token_valid',
            'meta_token_checked_at',
            'meta_last_reconcile_error',
            'meta_last_reconcile_status',
            'meta_last_reconcile_at',
            'meta_last_webhook_at',
            'meta_last_lead_at',
            'meta_test_mode_since',
            'meta_test_mode',
            'meta_error_alert_threshold',
            'meta_silence_alert_hours',
            'meta_reconcile_lookback_hours',
            'meta_reconcile_interval_minutes',
            'meta_graph_version',
            'meta_page_name',
            'meta_page_id',
            'meta_page_token_set_at',
            'meta_page_token',
            'meta_verify_token',
            'meta_app_secret_set_at',
            'meta_app_secret',
            'meta_app_id',
            'meta_leads_enabled',
        ):
            batch.drop_column(column)

    # Черга йде першою: у ній FK на meta_leads.
    op.drop_index('ix_meta_lead_events_status_retry', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_lead_id', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_next_retry_at', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_status', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_source', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_created_time', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_form_id', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_page_id', table_name='meta_lead_events')
    op.drop_index('ix_meta_lead_events_leadgen_id', table_name='meta_lead_events')
    op.drop_table('meta_lead_events')

    op.drop_index('ix_meta_leads_status_created', table_name='meta_leads')
    op.drop_index('ix_meta_leads_deleted_at', table_name='meta_leads')
    op.drop_index('ix_meta_leads_status', table_name='meta_leads')
    op.drop_index('ix_meta_leads_is_test', table_name='meta_leads')
    op.drop_index('ix_meta_leads_is_repeat', table_name='meta_leads')
    op.drop_index('ix_meta_leads_needs_attention', table_name='meta_leads')
    op.drop_index('ix_meta_leads_user_id', table_name='meta_leads')
    op.drop_index('ix_meta_leads_phone_e164', table_name='meta_leads')
    op.drop_index('ix_meta_leads_email', table_name='meta_leads')
    op.drop_index('ix_meta_leads_campaign_id', table_name='meta_leads')
    op.drop_index('ix_meta_leads_form_id', table_name='meta_leads')
    op.drop_index('ix_meta_leads_created_time', table_name='meta_leads')
    op.drop_index('ix_meta_leads_leadgen_id', table_name='meta_leads')
    op.drop_table('meta_leads')
