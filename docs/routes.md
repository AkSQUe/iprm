# Маршрути

## Main

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/` | Redirect 301 -> /courses/ |
| GET | `/labs` | Сторінка Лабораторії |
| GET/POST | `/contact` | Контактна форма |
| GET | `/design-system` | Дизайн-система |
| GET | `/offer` | Публічна оферта |
| GET | `/offer/pdf` | Підписана PDF-версія оферти (бланк, печатка, підпис) |
| GET | `/privacy` | Політика конфіденційності |
| GET | `/refund` | Політика повернення коштів |
| GET | `/disclaimer` | Медичний дисклеймер |
| GET | `/cookies` | Політика Cookie |
| GET | `/account` | Legacy redirect 301 -> `/auth/account` (посилання з уже надісланих листів про сертифікат) |

## Auth

| Метод | URL | Опис |
|-------|-----|------|
| GET/POST | `/auth/login` | Вхід |
| GET/POST | `/auth/register` | Реєстрація |
| POST | `/auth/logout` | Вихід |
| GET | `/auth/account` | Обліковий запис (курси + сертифікати) |
| GET | `/auth/account/certificates/<id>/download` | Завантажити власний сертифікат (PDF) |
| GET | `/auth/settings` | Налаштування профілю |
| GET | `/auth/confirm-email/<token>` | Підтвердження email |
| GET/POST | `/auth/account/set-password` | Встановити пароль (лише якщо його ще немає) |

### OAuth / OIDC

Мовного префікса не мають (`localize=False`): URL-и фіксовані в консолях
Google/Apple. Логіка входу спільна -- `_resolve_oauth_login()` в
[app/auth/oauth.py](../app/auth/oauth.py).

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/auth/google/start` | Старт Google-флоу (`?action=link` -- прив'язка) |
| GET | `/auth/google/callback` | Повернення з Google: вхід / прив'язка / створення |
| POST | `/auth/google/onetap` | Credential JWT від Google One Tap (JSON, CSRF-exempt, nonce з сесії, 20/год) |
| POST | `/auth/google/unlink` | Від'єднати Google |
| GET | `/auth/apple/start` | Старт Apple Sign In |
| GET/POST | `/auth/apple/callback` | Повернення з Apple (`form_post`, CSRF-exempt) |
| POST | `/auth/apple/unlink` | Від'єднати Apple |
| GET | `/auth/oauth/collision` | Пояснення "email уже зареєстровано" (контекст із сесії) |
| GET | `/auth/account/connections` | Способи входу: прив'язка/від'єднання провайдерів |

## Courses

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/courses` | Список курсів |
| GET | `/courses/<slug>` | Сторінка заходу за slug |
| GET | `/courses/detail` | Legacy redirect -> plazmoterapiya-v-ginekologii (301) |
| GET | `/courses/stomatology` | Legacy redirect -> plazmoterapiya-v-stomatologii (301) |
| GET | `/courses/orthopedics` | Legacy redirect -> plazmoterapiya-v-ortopedii (301) |

## Online courses (онлайн-курси Sintegrum)

Окремий розділ від `/courses`: там офлайн-заходи з датами й місцями, тут --
навчання, що фізично йде в Sintegrum. Каталог читається з локального дзеркала
`online_courses`, до чужого API на рендері звернень немає.

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/online-courses/` | Каталог опублікованих онлайн-курсів |
| GET | `/online-courses/<slug>` | Сторінка курсу (неопублікований -> 404) |
| GET, POST | `/online-courses/<slug>/checkout` | Оформлення покупки (потрібен логін) |
| GET | `/online-courses/access/<token>` | Тимчасове посилання -> 302 на Sintegrum |
| POST | `/online-courses/access/<id>/reissue` | Перевипуск протермінованого посилання |

`/online-courses/access/<token>` свідомо БЕЗ мовних префіксів
(`localize=False`): посилання живе в листі, і префікс лише множив би варіанти
того самого токена. Перевіряє чотири умови -- токен існує, замовлення
оплачене, термін не минув, у курсу заданий `access_url` -- і лише тоді робить
редірект. Цільова адреса не потрапляє ні в HTML сторінок помилок, ні в логи.

Пункт меню «Онлайн-курси» показується лише при
`SiteSettings.show_online_courses` -- каталог можна наповнювати, поки розділ
ще прихований.

## Trainers

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/trainers` | Список тренерів |
| GET | `/trainers/<slug>` | Сторінка тренера |

## Clinics

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/clinics` | Список клінік |
| GET | `/clinics/<slug>` | Сторінка клініки |

## Registration

| Метод | URL | Опис |
|-------|-----|------|
| GET/POST | `/registration/<event_id>/register` | Реєстрація на захід |
| GET | `/registration/<registration_id>` | Підтвердження реєстрації |
| POST | `/registration/instance/<id>/promo-check` | Перевірка промокоду (JSON, без списання) |

## Quiz (тестування учасників)

Блюпринт `quiz` -- `noindex`, `login_required`, мовні префікси `/ru`, `/en`.
Доступ лише до власної реєстрації та власної спроби; чужа й неіснуюча дають
однаковий 404. Правильні відповіді у шаблони не передаються ніколи.

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/quiz/<reg_id>` | Умови тесту, спроби, гейт із причиною |
| POST | `/quiz/<reg_id>/start` | Почати (або продовжити) спробу |
| GET | `/quiz/attempt/<id>` | Поточне питання; `?position=N` -- конкретне |
| POST | `/quiz/attempt/<id>/answer` | Зберегти відповідь, перейти далі/назад |
| GET | `/quiz/attempt/<id>/review` | Звірка перед завершенням |
| POST | `/quiz/attempt/<id>/submit` | Завершити й оцінити (лише коли всі відповіді є) |
| GET | `/quiz/attempt/<id>/result` | Бал, склав/не склав, номери незарахованих |
| GET | `/quiz/<reg_id>/done` | Привітання з посиланням на сертифікат |

## Payments

| Метод | URL | Опис |
|-------|-----|------|
| POST | `/payments/liqpay/callback` | LiqPay server-to-server callback |
| GET | `/payments/success` | Успішна оплата (redirect від LiqPay) |
| GET | `/payments/failure` | Невдала оплата (redirect від LiqPay) |

`/payments/success` і `/payments/failure` обслуговують ОБИДВА типи
замовлень і розрізняють їх за префіксом `order_id`: `REG-` -- реєстрація
на захід, `ONL-` -- купівля онлайн-курсу.

## Admin

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/` | Dashboard (redirect на events) |
| GET | `/admin/sintegrum` | Налаштування інтеграції Sintegrum |
| POST | `/admin/sintegrum/save` | Зберегти налаштування (порожній ключ не затирає) |
| POST | `/admin/sintegrum/test` | Перевірка зв'язку з API Sintegrum |
| POST | `/admin/sintegrum/sync` | Ручна синхронізація каталогу |
| GET | `/admin/online-courses` | Каталог онлайн-курсів (УВЕСЬ перелік із дзеркала) |
| GET, POST | `/admin/online-courses/<id>` | Редагування наших полів курсу |
| POST | `/admin/online-courses/<id>/publish` | Перемикач публікації |
| GET | `/admin/events` | Список заходів |
| GET/POST | `/admin/events/new` | Створення заходу |
| GET/POST | `/admin/events/<id>/edit` | Редагування заходу |
| POST | `/admin/events/<id>/delete` | Видалення заходу |
| GET | `/admin/events/<id>/registrations` | Реєстрації на захід |
| GET | `/admin/promo-codes` | Список промокодів (пошук, фільтр) |
| GET/POST | `/admin/promo-codes/new` | Створення промокоду |
| GET/POST | `/admin/promo-codes/<id>/edit` | Редагування промокоду |
| GET | `/admin/promo-codes/<id>` | Картка коду: статистика та історія застосувань |
| POST | `/admin/promo-codes/<id>/toggle` | Увімкнути/вимкнути код |
| POST | `/admin/promo-codes/<id>/recount` | Перерахувати лічильник з реєстру |
| POST | `/admin/promo-codes/<id>/delete` | Видалення промокоду |
| GET | `/admin/trainers` | Список тренерів |
| GET/POST | `/admin/trainers/new` | Додавання тренера |
| GET/POST | `/admin/trainers/<id>/edit` | Редагування тренера |
| POST | `/admin/trainers/<id>/delete` | Видалення тренера |
| POST | `/admin/registrations/<id>/status` | Зміна статусу реєстрації |
| POST | `/admin/registrations/<id>/attendance` | Підтвердження присутності |
| POST | `/admin/registrations/<id>/certificate` | Видати сертифікат (+ email) |
| POST | `/admin/registrations/<id>/certificate/resend` | Повторно надіслати сертифікат |
| GET | `/admin/registrations/<id>/certificate/download` | Завантажити сертифікат (адмін) |
| GET | `/admin/registrations` | Всі реєстрації (stub) |
| GET | `/admin/payments` | Redirect на LiqPay |
| GET | `/admin/liqpay` | Дашборд LiqPay |
| GET | `/admin/users` | Список користувачів |
| GET | `/admin/quizzes` | Реєстр тестів: банк, готовність, дані БПР |
| GET/POST | `/admin/courses/<id>/quiz` | Тест курсу (створюється при відкритті) |
| GET/POST | `/admin/instances/<id>/quiz` | Перевизначення тесту для проведення |
| POST | `/admin/quizzes/<id>/delete` | Видалити тест (результати лишаються) |
| GET | `/admin/instances/<id>/quiz-results` | Результати тестування групи |
| GET | `/admin/registrations/<id>/quiz` | Розбір по учаснику: кожна спроба, кожна відповідь, правильна поруч з обраною |
| POST | `/admin/registrations/<id>/quiz/unlock` | Додати спроби учаснику |
| POST | `/admin/registrations/<id>/quiz/reset` | Обнулити тестування учасника |
| GET | `/admin/certificates` | Сертифікати (stub) |
| GET | `/admin/clients` | Клієнти (stub) |
| GET | `/admin/reviews` | Відгуки (stub) |
| GET | `/admin/marketing` | Маркетинг |
| GET | `/admin/integrations` | Інтеграції |
| GET | `/admin/meta-pixel` | Meta Pixel -- конфігурація |
| POST | `/admin/meta-pixel/save` | Зберегти Pixel ID і прапорець |
| GET | `/admin/meta-pixel/test` | Надіслати тестову подію IPRMTestEvent |
| GET/POST | `/admin/settings` | Налаштування сайту |
| GET | `/admin/error-logs` | Журнал помилок |
| GET | `/admin/error-logs/<id>` | Деталі помилки |
| POST | `/admin/error-logs/<id>/resolve` | Позначити помилку вирішеною |
| POST | `/admin/error-logs/<id>/delete` | Видалити запис помилки |
| POST | `/admin/error-logs/bulk-action` | Масові операції з помилками |
| GET | `/admin/notifications` | Налаштування сповіщень |
| GET | `/admin/notifications/log` | Лог сповіщень |
| GET | `/admin/notifications/templates` | Шаблони листів |
| POST | `/admin/events/<id>/export` | Експорт заходу в XLSX |
| POST | `/admin/events/import` | Імпорт заходів з XLSX |
| GET | `/admin/perf` | Заміри швидкості: список прогонів + ключ приймання |
| GET | `/admin/perf/<id>` | Розбір прогону з порівнянням із попереднім |
| POST | `/admin/perf/<id>/delete` | Видалити прогін |
| POST | `/admin/perf/key/rotate` | Згенерувати новий ключ приймання замірів |
| POST | `/admin/perf/key/clear` | Вимкнути приймання замірів |

## API v1 (партнери та інструменти)

Автентифікація -- заголовок `X-API-Key`. Ключі окремі за призначенням: у
партнерських ендпоінтів `SiteSettings.partner_api_key`, у приймання замірів --
`SiteSettings.perf_api_key` (ротація на `/admin/perf`).

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/v1/events` | Список заходів для партнерів |
| GET | `/api/v1/events/<slug>` | Деталі заходу для партнерів |
| GET | `/api/v1/online-courses` | Каталог онлайн-курсів для партнерів |
| POST | `/api/v1/perf/runs` | Приймання прогону від `tools/perf/perf_check.py --push` |

## Errors

| Код | Шаблон | Опис |
|-----|--------|------|
| 400 | `errors/500.html` | Bad Request |
| 401 | `errors/401.html` | Unauthorized |
| 403 | `errors/403.html` | Forbidden |
| 404 | `errors/404.html` | Not Found |
| 405 | `errors/500.html` | Method Not Allowed |
| 429 | `errors/500.html` | Too Many Requests |
| 500 | `errors/500.html` | Internal Server Error |
| 503 | `errors/500.html` | Service Unavailable |

Всі помилки автоматично записуються в ErrorLog (з rate limiting та фільтрацією сканерів).
