# Підтвердження оплати з банківської виписки (ІПРМ) -- план

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ІПРМ приймає від mm-medic підписаний запит «цю реєстрацію оплачено переказом» і підтверджує її так само, як оплату карткою; рахунок ІПРМ отримує призначення платежу з номером і платіжний QR НБУ.

**Architecture:** Спільне ядро підтвердження -- наявні `PaymentOps.update_payment_status` / `update_enrollment_status`, розширені двома необов'язковими параметрами (момент оплати й посилання журналу). Новий сервіс `bank_payment.py` вирішує «чи можна оплатити» і ідемпотентність; новий endpoint поруч із `mm_status.py` використовує ту саму HMAC-перевірку, винесену в спільний помічник. Призначення платежу -- одна функція на всі формати; QR -- перенесений з mm-medic `payment_qr.py`.

**Tech Stack:** Flask 3, SQLAlchemy, Alembic (Flask-Migrate), WeasyPrint, openpyxl, `segno==1.6.6` (нова залежність, та сама версія, що в mm-medic), pytest на SQLite.

**Spec:** `D:\site-mm-medic\docs\superpowers\specs\2026-10-31-iprm-bank-payments-design.md` (розділи «1. ІПРМ: рахунок, призначення, QR» і «2. ІПРМ: прийом підтвердження оплати»). Парний план для mm-medic: `D:\site-mm-medic\docs\superpowers\plans\2026-10-31-iprm-bank-payments.md` -- він кличе endpoint із Задачі 2 і читає `paid_via` із Задачі 3, тому цей план деплоїться ПЕРШИМ.

## Global Constraints

- Робота в `main`, коміти фазами (одна задача -- один коміт), `git commit --only -- <шляхи>`, повідомлення українською без згадок інструмента чи моделі; пуш -- лише за прямою командою.
- Тести: `./venv/Scripts/python.exe -m pytest <шлях> -q` у `d:\site-iprm` (власний venv ІПРМ, див. README). Лінт своїх файлів: `./venv/Scripts/python.exe -m flake8 --extend-ignore=F401 --max-line-length=100 <файли>`.
- Номер у документах: `REG-<id>` для реєстрацій, `ONL-<id>` для онлайн-курсів (`OnlineEnrollment.order_id`). Розбір номера -- наявний `payment_ops.parse_order_id`.
- Призначення платежу (точний текст): `Оплата згідно рахунку № {номер} від {дд.мм.рррр} за {Прізвище Ім'я По батькові}`. Без gettext. Якщо ПІБ немає -- без суфікса « за …».
- QR: формат НБУ v002 зі старим хостом `https://bank.gov.ua/qr/`, отримувач обрізається до 38 символів, призначення -- до 140; сума = `payment_amount`. Некоректні реквізити -- QR не друкується, рахунок друкується.
- Підтвердження з виписки поводиться як оплата карткою: `status='confirmed'`, номер місця, лист `payment_confirmed`, реферали, промокоди, скасування відкладеного підтвердження, перевірка переповнення.
- Журнал: `PaymentTransaction.source='bank'`, мітка «Банківська виписка».
- Ідемпотентність за посиланням банківської транзакції mm-medic: повтор -- той самий результат, другого листа немає.
- HTTP: бізнес-відмова -- 200 з `status='refused'` і кодом причини; 4xx/5xx -- лише для підпису, формату й вимкненої інтеграції (як `mm_status.py`).

## Review Focus

1. Повтор того самого запиту після успіху (mm-medic не отримав відповіді й надіслав ще раз) -- `duplicate`, лист не дублюється (Задача 1, `test_repeat_is_duplicate_without_second_email`).
2. Платіж на реєстрацію, яку менеджер уже позначив «Оплачено» вручну, -- `refused/already_paid`, статус і `paid_at` не змінюються (Задача 1, `test_already_paid_is_refused_untouched`).
3. Скасована реєстрація (`status='cancelled'`) з `payment_status='unpaid'` -- `refused/cancelled`, а не оплата (Задача 1, `test_cancelled_registration_refused`).
4. Сума з копійками й рядком `"1500.00"` проти `Decimal('1500')` -- збіг; `1499.99` -- `amount_mismatch` (Задача 1, `test_amount_tolerance`).
5. Довгий ПІБ і назва ТОВ понад ліміти v002 -- QR усе одно будується в межах 140/38 символів, PDF рендериться (Задача 4, `test_qr_payload_respects_v002_limits`).

---

### Task 1: Ядро підтвердження з виписки

**Files:**
- Create: `app/services/bank_payment.py`
- Create: `migrations/versions/payment_txn_bank_source_20261031.py`
- Modify: `app/models/payment_transaction.py` (CHECK `ck_payment_transactions_source` + `SOURCES`)
- Modify: `app/services/payment_ops.py` (`update_payment_status`, `update_enrollment_status`, `_log_transaction`)
- Test: `tests/test_services/test_bank_payment.py`

**Interfaces:**
- Produces:
  - `PaymentOps.update_payment_status(self, reg, new_status, payment_id=None, amount=None, source='manual', liqpay_status=None, raw_payload=None, paid_at=None, txn_ref=None)` -- `paid_at: tuple[datetime, str] | None` замінює `liqpay_paid_moment(raw_payload)`; `txn_ref: str | None` пишеться в `PaymentTransaction.payment_id` журналу, НЕ в `reg.payment_id`. Те саме для `update_enrollment_status`.
  - `bank_payment.BankPaymentResult` -- frozen dataclass: `status: str` (`'paid' | 'duplicate' | 'refused'`), `reason: str | None` (`'bad_ref' | 'not_found' | 'already_paid' | 'cancelled' | 'refunded' | 'amount_mismatch' | 'db_error'`), `order_ref: str`.
  - `bank_payment.confirm_bank_payment(order_ref: str, amount: Decimal, transacted_at: datetime, bank_tx_ref: str, actor: str | None = None) -> BankPaymentResult`.
  - Константа `bank_payment.SOURCE_BANK = 'bank'`.

- [ ] **Step 1: Write the failing tests** у `tests/test_services/test_bank_payment.py` (фікстури реєстрації/онлайн-запису -- як у `tests/test_services/test_payment_ops.py`; `EmailService.send_payment_confirmation` -- через `monkeypatch`, лічильник викликів):

```python
def test_confirms_unpaid_registration_like_card(app, reg_unpaid_1500, sent):
    r = confirm_bank_payment(f'REG-{reg_unpaid_1500.id}', Decimal('1500.00'),
                             datetime(2026, 10, 30, 9, 15, tzinfo=timezone.utc), 'bt-77')
    assert (r.status, r.reason) == ('paid', None)
    db.session.refresh(reg_unpaid_1500)
    assert reg_unpaid_1500.payment_status == 'paid'
    assert reg_unpaid_1500.status == 'confirmed'
    assert reg_unpaid_1500.place_number is not None
    assert reg_unpaid_1500.paid_at == datetime(2026, 10, 30, 9, 15, tzinfo=timezone.utc)
    assert reg_unpaid_1500.paid_at_precision == 'datetime'
    assert reg_unpaid_1500.payment_id is None
    txn = PaymentTransaction.query.filter_by(registration_id=reg_unpaid_1500.id, source='bank').one()
    assert txn.payment_id == 'bt-77' and txn.mapped_status == 'paid'
    assert sent.count == 1

def test_repeat_is_duplicate_without_second_email(...):   # той самий bank_tx_ref двічі
    # другий виклик: status 'duplicate', sent.count == 1, один рядок журналу source='bank'

def test_already_paid_is_refused_untouched(...):          # paid вручну 28.10
    # ('refused', 'already_paid'); paid_at і журнал без змін

def test_cancelled_registration_refused(...):             # status='cancelled', payment_status='unpaid'
    # ('refused', 'cancelled')

def test_refunded_registration_refused(...):              # ('refused', 'refunded')

def test_amount_tolerance(...):
    # Decimal('1500') проти payment_amount 1500.00 -> paid; Decimal('1499.99') -> ('refused', 'amount_mismatch')

def test_unknown_and_bad_refs(...):
    # 'REG-999999' -> ('refused', 'not_found'); 'SUR-5' і 'abc' -> ('refused', 'bad_ref')

def test_confirms_online_enrollment(...):                  # 'ONL-<id>' -> paid, журнал з enrollment_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_bank_payment.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.bank_payment`)

- [ ] **Step 3: Migration and model.** `payment_txn_bank_source_20261031.py`: `down_revision` = поточна голова (`flask db heads`); перестворити `ck_payment_transactions_source` з `'bank'` (на PostgreSQL -- `DROP CONSTRAINT IF EXISTS` + `ADD ... NOT VALID`, на SQLite -- `batch_alter_table`). У моделі -- той самий CHECK і `('bank', 'Банківська виписка')` у `SOURCES`.

- [ ] **Step 4: Extend `update_payment_status` / `update_enrollment_status` / `_log_transaction`** параметрами `paid_at=None, txn_ref=None` (сигнатури -- в Interfaces). `paid_at` задано -> `reg.set_paid_at(*paid_at)` замість `liqpay_paid_moment(raw_payload)`; `txn_ref` -> `payment_id` рядка журналу (якщо `payment_id` не задано). Поведінка для всіх наявних викликів не змінюється -- `tests/test_services/test_payment_ops.py` мусить лишитись зеленим.

- [ ] **Step 5: Implement `confirm_bank_payment`** у `app/services/bank_payment.py`. Порядок перевірок: `parse_order_id` (не `registration`/`enrollment` -> `bad_ref`) -> запис (`not_found`) -> рядок журналу `source='bank', payment_id=bank_tx_ref` уже є (`duplicate`) -> `refunded` -> `status == 'cancelled'` або `cancelled_at` (`cancelled`) -> `payment_status == 'paid'` (`already_paid`) -> виклик `PaymentOps(None).update_payment_status(reg, 'paid', amount=amount, source='bank', raw_payload={'bank_tx_ref': ..., 'transacted_at': ..., 'actor': actor}, paid_at=(transacted_at, PAID_AT_DATETIME), txn_ref=bank_tx_ref)`; повідомлення `amount mismatch` -> `amount_mismatch`, інша відмова -> `db_error`. Якщо `PaymentOps` вимагає LiqPay-сервіс у конструкторі для цього шляху -- передати `None` безпечно (метод його не чіпає); інакше -- взяти фабрику, якою користується `routes_payments.py`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_services/test_bank_payment.py tests/test_services/test_payment_ops.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -- app/services/bank_payment.py migrations/versions/payment_txn_bank_source_20261031.py app/models/payment_transaction.py app/services/payment_ops.py tests/test_services/test_bank_payment.py
git commit --only -m "Оплата переказом підтверджується з банківської виписки так само, як карткою: реєстрація стає підтвердженою, отримує місце, учасник отримує лист «оплату отримано». Повтор того самого платежу нічого не дублює; оплачену, скасовану чи повернену реєстрацію платіж не чіпає. У журналі оплат з'явилось джерело «Банківська виписка»." -- app/services/bank_payment.py migrations/versions/payment_txn_bank_source_20261031.py app/models/payment_transaction.py app/services/payment_ops.py tests/test_services/test_bank_payment.py
```

### Task 2: Endpoint `POST /api/partner/mm-medic/bank-payment`

**Files:**
- Create: `app/api/mm_signature.py`
- Create: `app/api/mm_bank_payment.py`
- Modify: `app/api/mm_status.py` (перевірка підпису -> `mm_signature.verify_signed_request`)
- Modify: `app/__init__.py:248-250` (реєстрація blueprint, `csrf.exempt`)
- Test: `tests/test_routes/test_mm_bank_payment.py`

**Interfaces:**
- Consumes: `confirm_bank_payment`, `BankPaymentResult` (Task 1).
- Produces:
  - `mm_signature.verify_signed_request() -> tuple[dict | None, tuple[Response, int] | None]` -- перевіряє `mm_medic_integration_enabled`, секрет, `X-IPRM-Signature`/`X-IPRM-Timestamp` (вікно 300 с), JSON-об'єкт; повертає `(payload, None)` або `(None, відповідь)` з тими самими статусами, що зараз у `reservation_status` (`disabled` 404, `misconfigured` 503, `missing_headers`/`bad_timestamp`/`malformed` 400, `stale`/`invalid_signature` 401).
  - Запит (JSON): `{"order_ref": "REG-1234", "amount": "1500.00", "transacted_at": "2026-10-30T09:15:00+00:00", "bank_tx_ref": "mm-bt-8812", "actor": "manager@mm-medic.com" | null}`.
  - Відповідь 200: `{"status": "paid" | "duplicate" | "refused", "reason": <код або null>, "order_ref": "REG-1234"}`. Поле бракує чи не парситься -> 400 `{"status": "malformed", "field": "<ім'я>"}`.

- [ ] **Step 1: Write the failing tests** (підпис -- тим самим способом, що в наявних тестах `mm_status`):

```python
def test_valid_request_confirms(client, signed, reg_unpaid_1500):
    resp = signed('/api/partner/mm-medic/bank-payment', {...REG..., 'amount': '1500.00'})
    assert resp.status_code == 200
    assert resp.get_json() == {'status': 'paid', 'reason': None, 'order_ref': f'REG-{reg_unpaid_1500.id}'}

def test_business_refusal_is_200(...):     # already paid -> 200, status 'refused', reason 'already_paid'
def test_bad_signature_401(...):           # 'invalid_signature', реєстрація не змінилась
def test_stale_timestamp_401(...):         # ts - 301 с -> 'stale'
def test_missing_field_400(...):           # без bank_tx_ref -> {'status': 'malformed', 'field': 'bank_tx_ref'}
def test_integration_disabled_404(...):
def test_reservation_status_still_verifies(...):  # регрес mm_status після виносу перевірки
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_routes/test_mm_bank_payment.py -q`
Expected: FAIL (404 на маршруті)

- [ ] **Step 3: Implement** `mm_signature.verify_signed_request`, переведи на нього `reservation_status`, створи `mm_bank_payment_bp` (`url_prefix='/api/partner/mm-medic'`, `@limiter.limit('120 per minute')`), розбір `amount` -> `Decimal`, `transacted_at` -> aware UTC (наявний `_parse_dt`-підхід), виклик `confirm_bank_payment`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_routes/test_mm_bank_payment.py tests/test_mm_medic_materials.py -q`
Expected: PASS

- [ ] **Step 5: Commit** (`--only` з п'ятьма шляхами вище) -- «MM Medic може повідомити ІПРМ, що реєстрацію оплачено переказом: підписаний запит тим самим секретом, що й статуси резервів; відмова приходить із причиною, а не помилкою.»

### Task 3: `paid_via` в API реєстрацій і онлайн-записів

**Files:**
- Modify: `app/api/v1/clients.py` (`list_registrations`, `list_online_enrollments`)
- Create або Modify: помічник у `app/services/bank_payment.py` -- `paid_via_map(kind: str, ids: list[int]) -> dict[int, str]`
- Test: `tests/test_routes/test_api_v1_clients.py`

**Interfaces:**
- Produces: поле `paid_via` у кожному рядку `/api/v1/registrations` і `/api/v1/online-enrollments`: `'liqpay'` (останній перехід у paid мав `source` `callback` або `status_check`), `'manual'`, `'bank'`, або `null` (не оплачено чи журналу немає). Один запит на сторінку (≤200 id), без N+1.

- [ ] **Step 1: Write the failing tests:** реєстрація, оплачена callback-ом -> `'liqpay'`; через `apply_manual_payment_status` -> `'manual'`; через `confirm_bank_payment` -> `'bank'`; неоплачена -> `None`; оплачена вручну, а потім `status_check` LiqPay оновив дату -> `'liqpay'` (останній рядок журналу з `mapped_status='paid'` за `id`). Окремо: кількість SQL-запитів сторінки з 50 реєстрацій не залежить від кількості (лічильник подій engine, як у наявних perf-тестах API, якщо такі є; інакше -- `len(queries) <= базові + 1`).

- [ ] **Step 2: Run** `./venv/Scripts/python.exe -m pytest tests/test_routes/test_api_v1_clients.py -q` -- FAIL (`KeyError: 'paid_via'`).

- [ ] **Step 3: Implement** `paid_via_map` (одна вибірка `PaymentTransaction` з `mapped_status='paid'` по `registration_id IN (...)` / `enrollment_id IN (...)`, останній за `id`) і поле в обох серіалізаторах.

- [ ] **Step 4: Run** -- PASS.

- [ ] **Step 5: Commit** -- «API реєстрацій і онлайн-записів каже, як саме оплату підтверджено: карткою, вручну чи з банківської виписки.»

### Task 4: Призначення платежу і QR у рахунку

**Files:**
- Create: `app/services/payment_purpose.py`
- Create: `app/services/payment_qr.py` (перенесення з `D:\site-mm-medic\app\services\documents\payment_qr.py`: `_clean`, `_format_amount`, `build_nbu_qr_data_v002`, `_pick_v002_encoding`, `build_nbu_qr_url`, `build_nbu_qr_payload`; SVG -- через `segno` напряму, `error='m'`, `border=4`, `light='#fff'`)
- Modify: `requirements.txt` і `requirements.lock` (`segno==1.6.6`)
- Modify: `app/services/invoice_service.py` (`_invoice_context`, `_enrollment_invoice_context`, `_invoice_template_ctx`, `build_invoice_xlsx`)
- Modify: `app/templates/invoices/invoice.html` (рядок «Призначення платежу» + блок QR з підписом «Скануйте в застосунку банку»)
- Modify: `app/templates/registration/partials/_bank_requisites.html` (призначення з кнопкою копіювання, якщо в ДС ІПРМ є така; текст «вкажіть призначення без змін»)
- Test: `tests/test_services/test_payment_purpose.py`, `tests/test_services/test_payment_qr.py`, `tests/test_routes/test_registration_invoice.py`

**Interfaces:**
- Produces:
  - `payment_purpose.order_ref(order) -> str` -- `REG-<id>` або `enrollment.order_id`.
  - `payment_purpose.build_payment_purpose(order) -> str` -- текст із Global Constraints; дата -- `created_at` за Києвом.
  - `payment_qr.build_nbu_qr_payload(recipient_name, iban, amount, purpose, recipient_code) -> str` (URL); `payment_qr.qr_svg_data_uri(payload: str) -> str`.
  - Контекст шаблона рахунка отримує `purpose: str`, `qr_data_uri: str | None`, `number: str` (тепер `REG-…`/`ONL-…`).

- [ ] **Step 1: Write the failing tests:**

```python
def test_purpose_registration(reg_1234_created_2026_10_31_kyiv):
    assert build_payment_purpose(reg) == "Оплата згідно рахунку № REG-1234 від 31.10.2026 за Береза Олена Іванівна"

def test_purpose_without_name_has_no_suffix(...):   # user без імені -> "Оплата згідно рахунку № REG-… від …"
def test_purpose_enrollment_uses_order_id(...):     # "… № ONL-56 від …"
def test_qr_payload_respects_v002_limits():         # ПІБ 120 символів, ТОВ 60 символів -> decoded: рядок 6 ≤ 38, рядок 12 ≤ 140, рядок 8 'UAH1500'
def test_qr_skipped_on_bad_iban(...):               # iban 'UA12' -> qr_data_uri None, PDF рендериться
def test_invoice_pdf_contains_purpose_and_number(client, ...):  # HTML-контекст: 'REG-1234' і повне призначення; PDF > 0 байт
def test_invoice_xlsx_has_purpose_row(...):
```

Декодування payload у тесті: Base64URL-частина після `https://bank.gov.ua/qr/` -> `split('\n')`.

- [ ] **Step 2: Run** `./venv/Scripts/python.exe -m pytest tests/test_services/test_payment_purpose.py tests/test_services/test_payment_qr.py tests/test_routes/test_registration_invoice.py -q` -- FAIL.

- [ ] **Step 3: Install** `./venv/Scripts/python.exe -m pip install segno==1.6.6` і додай рядок у обидва файли залежностей.

- [ ] **Step 4: Implement** модулі й правки рахунка/шаблонів. Номер рахунка в PDF/XLSX і в імені файлу -- `order_ref`. Стилі блоку QR -- у CSS рахунка/ДС ІПРМ, без inline.

- [ ] **Step 5: Run** -- PASS; плюс `./venv/Scripts/python.exe -m pytest tests/test_services/test_registration_invoice_email.py -q`.

- [ ] **Step 6: Visual check:** згенерувати PDF реєстрації й онлайн-запису, відкрити, переконатися, що призначення й QR видно; відсканувати QR застосунком Приват24 (або декодувати) -- реквізити, сума, призначення збігаються. Знімок сторінки «оплата за реквізитами» на 375 px і desktop.

- [ ] **Step 7: Commit** -- «У рахунку ІПРМ з'явились призначення платежу з номером REG-/ONL- і ПІБ учасника та платіжний QR: застосунок банку заповнює реквізити, суму й призначення сам. Номер рахунку тепер збігається з номером оплати й не перетинається між навчаннями та онлайн-курсами.»

---

## Self-review (виконано)

- Покриття спеки: §1 -> Task 4; §2 (endpoint, ідемпотентність, поведінка як картка, журнал `bank`, відмови з причиною) -> Tasks 1-2; `paid_via` для «другого ешелону» (§4 спеки) -> Task 3. `SUR-` -> `bad_ref` (поза проєктом за спекою).
- Типи: `BankPaymentResult.reason` -- ті самі коди в Task 1, 2 і в парному плані mm-medic.
