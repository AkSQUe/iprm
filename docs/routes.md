# Маршрути

## Публічні сторінки

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/` | Головна сторінка |
| GET | `/design-system` | Дизайн-система |
| GET | `/offer` | Публічна оферта |
| GET | `/privacy` | Політика конфіденційності |
| GET | `/refund` | Повернення коштів |
| GET | `/disclaimer` | Дисклеймер |

## Авторизація

| Метод | URL | Опис |
|-------|-----|------|
| GET/POST | `/auth/login` | Вхід |
| GET/POST | `/auth/register` | Реєстрація |
| POST | `/auth/logout` | Вихід |
| GET | `/auth/account` | Обліковий запис |

## Курси

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/courses/` | Список курсів (з БД) |
| GET | `/courses/<slug>` | Сторінка заходу за slug (з БД) |
| GET | `/courses/detail` | Legacy redirect -> slug |
| GET | `/courses/stomatology` | Legacy redirect -> slug |
| GET | `/courses/orthopedics` | Legacy redirect -> slug |

## Тренери

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/trainers/` | Список тренерів |
| GET | `/trainers/<slug>` | Сторінка тренера |

## Реєстрація на заходи

| Метод | URL | Опис |
|-------|-----|------|
| GET/POST | `/registration/<event_id>/register` | Форма реєстрації на захід |
| GET | `/registration/<registration_id>` | Сторінка підтвердження реєстрації |

## Платежі (LiqPay)

| Метод | URL | Опис |
|-------|-----|------|
| POST | `/payments/liqpay/callback` | Webhook від LiqPay (CSRF-exempt, rate-limited) |
| GET | `/payments/success` | Сторінка успішної оплати (server-side верифікація) |
| GET | `/payments/failure` | Сторінка помилки оплати |

## Адмін-панель

### Контент

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/` | Redirect на `/admin/events` |
| GET | `/admin/events` | Список заходів |
| GET/POST | `/admin/events/new` | Створення заходу |
| GET/POST | `/admin/events/<id>/edit` | Редагування заходу |
| POST | `/admin/events/<id>/delete` | Видалення заходу |
| GET | `/admin/trainers` | Список тренерів |
| GET/POST | `/admin/trainers/new` | Додавання тренера |
| GET/POST | `/admin/trainers/<id>/edit` | Редагування тренера |
| POST | `/admin/trainers/<id>/delete` | Видалення тренера |

### Продажі

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/registrations` | Всі реєстрації |
| GET | `/admin/events/<id>/registrations` | Реєстрації на захід |
| POST | `/admin/registrations/<id>/status` | Зміна статусу реєстрації |
| POST | `/admin/registrations/<id>/attendance` | Підтвердження присутності |
| GET | `/admin/payments` | Redirect на LiqPay |
| GET | `/admin/liqpay` | LiqPay dashboard (статистика, конфігурація, платежі) |
| GET | `/admin/certificates` | Сертифікати (stub) |

### Аудиторія

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/clients` | Клієнти (stub) |
| GET | `/admin/reviews` | Відгуки (stub) |

### Система

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/admin/marketing` | Маркетинг (TODO-план) |
| GET | `/admin/integrations` | Інтеграції (LiqPay, Google, reCAPTCHA, Apple, Clarity, Facebook) |
| GET | `/admin/settings` | Налаштування (stub) |
