# Маршрути

## Main

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/` | Redirect 301 -> /courses/ |
| GET | `/labs` | Сторінка Лабораторії |
| GET/POST | `/contact` | Контактна форма |
| GET | `/design-system` | Дизайн-система |
| GET | `/offer` | Публічна оферта |
| GET | `/privacy` | Політика конфіденційності |
| GET | `/refund` | Політика повернення коштів |
| GET | `/disclaimer` | Медичний дисклеймер |
| GET | `/cookies` | Політика Cookie |

## Auth

| Метод | URL | Опис |
|-------|-----|------|
| GET/POST | `/auth/login` | Вхід |
| GET/POST | `/auth/register` | Реєстрація |
| POST | `/auth/logout` | Вихід |
| GET | `/auth/account` | Обліковий запис |
| GET | `/auth/settings` | Налаштування профілю |
| GET | `/auth/confirm-email/<token>` | Підтвердження email |

## Courses

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/courses` | Список курсів |
| GET | `/courses/<slug>` | Сторінка заходу за slug |
| GET | `/courses/detail` | Legacy redirect -> plazmoterapiya-v-ginekologii (301) |
| GET | `/courses/stomatology` | Legacy redirect -> plazmoterapiya-v-stomatologii (301) |
| GET | `/courses/orthopedics` | Legacy redirect -> plazmoterapiya-v-ortopedii (301) |

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

## Payments

| Метод | URL | Опис |
|-------|-----|------|
| POST | `/payments/liqpay/callback` | LiqPay server-to-server callback |
| GET | `/payments/success` | Успішна оплата (redirect від LiqPay) |
| GET | `/payments/failure` | Невдала оплата (redirect від LiqPay) |

## Admin

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/` | Dashboard (redirect на events) |
| GET | `/admin/events` | Список заходів |
| GET/POST | `/admin/events/new` | Створення заходу |
| GET/POST | `/admin/events/<id>/edit` | Редагування заходу |
| POST | `/admin/events/<id>/delete` | Видалення заходу |
| GET | `/admin/events/<id>/registrations` | Реєстрації на захід |
| GET | `/admin/trainers` | Список тренерів |
| GET/POST | `/admin/trainers/new` | Додавання тренера |
| GET/POST | `/admin/trainers/<id>/edit` | Редагування тренера |
| POST | `/admin/trainers/<id>/delete` | Видалення тренера |
| POST | `/admin/registrations/<id>/status` | Зміна статусу реєстрації |
| POST | `/admin/registrations/<id>/attendance` | Підтвердження присутності |
| GET | `/admin/registrations` | Всі реєстрації (stub) |
| GET | `/admin/payments` | Redirect на LiqPay |
| GET | `/admin/liqpay` | Дашборд LiqPay |
| GET | `/admin/users` | Список користувачів |
| GET | `/admin/certificates` | Сертифікати (stub) |
| GET | `/admin/clients` | Клієнти (stub) |
| GET | `/admin/reviews` | Відгуки (stub) |
| GET | `/admin/marketing` | Маркетинг |
| GET | `/admin/integrations` | Інтеграції |
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
