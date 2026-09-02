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
| GET/POST | `/auth/account/refund/<kind>/<id>` | Заявка на повернення коштів. Показує суму за Політикою до заповнення; `kind` -- `registration` або `enrollment` |
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
| GET | `/courses/<slug>` | Сторінка заходу за slug (продажний макет, див. нижче) |
| POST | `/courses/<slug>/request` | Заявка з форми курсу (email, ім'я, телефон, канал зв'язку, згода) |
| GET | `/courses/detail` | Legacy redirect -> plazmoterapiya-v-ginekologii (301) |
| GET | `/courses/stomatology` | Legacy redirect -> plazmoterapiya-v-stomatologii (301) |
| GET | `/courses/orthopedics` | Legacy redirect -> plazmoterapiya-v-ortopedii (301) |

Сторінки очного й онлайн-курсу зібрані з **тих самих партіалів**
(`partials/_course_hero.html`, `_course_proof`, `_course_benefits`,
`_course_audience`, `_course_gallery`, `_course_program`, `_course_trainer`,
`_course_reviews`, `_course_lead_form`, `_course_page_nav`) і одного файлу
стилів `css/course-landing.css`. Партіали читають `course.*` напряму: нові
контентні поля названі однаково в `Course` і `OnlineCourse`. Кожна секція
умовна -- курс без заповненого контенту не показує порожню рамку. Деталі --
[план редизайну](plan-course-landing-redesign.md).

## Online courses (онлайн-курси Sintegrum)

Окремий розділ від `/courses`: там офлайн-заходи з датами й місцями, тут --
навчання, що фізично йде в Sintegrum. Каталог читається з локального дзеркала
`online_courses`, до чужого API на рендері звернень немає.

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/online-courses/` | Каталог опублікованих онлайн-курсів |
| GET | `/online-courses/<slug>` | Сторінка курсу (неопублікований -> 404) |
| GET, POST | `/online-courses/<slug>/checkout` | Оформлення покупки, промокод; аноніму -- форма покупця |
| GET, POST | `/online-courses/order/<token>` | Сторінка замовлення гостя: оплата, промокод, кабінет |
| POST | `/online-courses/order/<token>/set-password` | Створення кабінету після оплати |
| POST | `/online-courses/order/<token>/reissue` | Перевипуск протермінованого посилання гостем |
| GET | `/online-courses/order/<token>/invoice.pdf` | Рахунок для покупця без акаунта |
| GET | `/online-courses/orders/<id>/invoice.pdf` | Рахунок із кабінету |
| GET | `/online-courses/access/<token>` | Тимчасове посилання -> 302 на Sintegrum |
| POST | `/online-courses/access/<id>/reissue` | Перевипуск протермінованого посилання |

Логіну чекаут НЕ вимагає (рішення 17.08.2026, скасовує Q5 плану). Анонім
отримує форму покупця (ПІБ, email, телефон необов'язковий), після сабміту
`participant_service.resolve_user` заводить безпарольного користувача -- той
самий механізм, що в гостьовій реєстрації на захід. Далі покупець ходить за
`order_token` (30 днів), бо входу ще не має; пароль пропонується після
оплати. Токен замовлення -- це НЕ токен доступу: перший живе до оплати й
веде на наш сайт, другий видається після неї й веде в Sintegrum.

Перевипуск доступу є в обох світах: у кабінеті (`access/<id>/reissue`,
login_required) і на сторінці замовлення (`order/<token>/reissue`,
авторизація -- токен). Без другого гість із протермінованим посиланням
опинявся в глухому куті: сторінка помилки пропонує перевипуск лише власнику
акаунта.

`online.checkout`, `online.order` і `online.order_set_password` додано до
`PRIVATE_HTML_ENDPOINTS` -- решта публічного блупринта лишається придатною
для bfcache, а ці сторінки показують чужу покупку неавтентифікованому
відвідувачу й мусять мати `no-store`.

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
| GET | `/registration/transfer/<token>` | Перенесення на інший захід: підсумок і вибір учасника |
| POST | `/registration/transfer/<token>/accept` | Згода на перенесення |
| POST | `/registration/transfer/<token>/refund` | Відмова: заявка на повернення коштів |
| GET | `/registration/transfer/<token>/surcharge` | Оплата різниці тарифу (LiqPay, `SUR-<transfer_id>`) |

Чотири останні -- токен-флоу без входу, дзеркало `/registration/complete/`.
Токен живе 30 днів; сторінки відмовляють, якщо цільовий захід скасовано, а
доплата -- ще й після того, як учасник попросив повернення. Докладно --
[docs/registration-transfer.md](registration-transfer.md).

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
| GET | `/admin/online-orders` | Замовлення онлайн-курсів: хто купив і чи є доступ |
| POST | `/admin/online-orders/<id>/payment` | Ручна зміна статусу оплати |
| POST | `/admin/online-orders/<id>/reissue` | Видати/перевидати доступ негайно |
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
| GET | `/admin/registrations/<id>/transfer/options` | JSON для модалки перенесення: придатні заходи, тарифи, різниці, блокери |
| POST | `/admin/registrations/<id>/transfer` | Перенести реєстрацію на інше проведення |
| GET | `/admin/payments` | Redirect на LiqPay |
| GET | `/admin/liqpay` | Дашборд LiqPay |
| POST | `/admin/liqpay/save-keys` | Зберегти ключі (з валідацією перед збереженням) |
| POST | `/admin/liqpay/test` | Перевірити з'єднання з LiqPay API |
| GET/POST | `/admin/refunds/<kind>/<id>` | Повернення коштів: сума за Політикою, підстава, виняток п. 5.1. `kind` -- `registration` або `enrollment`. `?request=<id>` підставляє суму із заявки й закриває її після проведення |
| GET | `/admin/refund-requests` | Черга заявок учасників на повернення (найстаріші відкриті зверху) |
| POST | `/admin/refund-requests/<id>/reject` | Відхилити заявку з поясненням (їде в лист учаснику) |
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
| GET | `/admin/users/<id>` | Картка людини: історія заявок з Meta, реєстрації, платежі |
| GET | `/admin/meta-leads` | Реєстр заявок з Meta Lead Ads (фільтри, годинник очікування) |
| GET | `/admin/meta-leads/export` | Експорт реєстру в XLSX |
| GET/POST | `/admin/meta-leads/<id>` | Картка заявки; перехід у «В роботі» ставить час першої реакції |
| POST | `/admin/meta-leads/<id>/delete` | М'яко видалити заявку |
| POST | `/admin/meta-leads/<id>/restore` | Відновити видалену |
| POST | `/admin/meta-leads/delete-test` | Пакетно прибрати тестові заявки |
| GET | `/admin/meta-leads/events` | Сира черга подій leadgen |
| GET | `/admin/meta-leads/events/export` | Експорт черги подій у XLSX |
| POST | `/admin/meta-leads/events/<id>/retry` | Повернути подію в чергу |
| GET | `/admin/meta-leads/settings` | Стан токена, остання заявка, помилки, діагностика |
| POST | `/admin/meta-leads/settings/save` | Зберегти App ID / App Secret / verify token / ID Сторінки |
| POST | `/admin/meta-leads/settings/test-mode` | Увімкнути або вимкнути режим тестування |
| POST | `/admin/meta-leads/settings/check-token` | `debug_token`: чинність, термін, дозволи |
| POST | `/admin/meta-leads/settings/exchange-token` | Обміняти User token на безстроковий Page token |
| POST | `/admin/meta-leads/settings/subscribe` | Підписати Сторінку на подію `leadgen` |
| POST | `/admin/meta-leads/settings/reconcile` | Звірити з Meta негайно |
| POST | `/admin/meta-leads/settings/test-event` | Надіслати собі підписану тестову подію |

## API v1 (партнери та інструменти)

Автентифікація -- заголовок `X-API-Key`. Ключі окремі за призначенням: у
партнерських ендпоінтів `SiteSettings.partner_api_key`, у приймання замірів --
`SiteSettings.perf_api_key` (ротація на `/admin/perf`).

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/v1/events` | Список заходів для партнерів |
| GET | `/api/v1/events/<slug>` | Деталі заходу для партнерів |
| GET | `/api/v1/online-courses` | Каталог онлайн-курсів для партнерів |
| GET | `/api/v1/online-enrollments` | Покупки онлайн-курсів (хто, що, чи оплачено) |
| POST | `/api/v1/perf/runs` | Приймання прогону від `tools/perf/perf_check.py --push` |

## Вебхуки від зовнішніх систем

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/webhooks/meta/leads` | Верифікація підписки Meta (`hub.challenge`) |
| POST | `/api/webhooks/meta/leads` | Приймання подій `leadgen`. Підпис `X-Hub-Signature-256` по СИРОМУ тілу; 200 віддається ДО будь-якого походу в Graph API |
| POST | `/api/partner/mm-medic/...` | Стан резервувань матеріалів від MM Medic |

Обидва блюпринти виведені з-під CSRF: підписувач -- зовнішня система, а не
браузер. Ендпоінт Meta навмисно НЕ гейтиться на прапорці інтеграції:
відкинути валідно підписаний запит означало б втратити заявку назавжди --
у Meta вони живуть 90 днів.

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
