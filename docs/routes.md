# Маршрути

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/` | Головна сторінка |
| GET | `/design-system` | Дизайн-система |
| GET/POST | `/auth/login` | Вхід |
| GET/POST | `/auth/register` | Реєстрація |
| POST | `/auth/logout` | Вихід |
| GET | `/auth/account` | Обліковий запис |
| GET | `/courses` | Список курсів (динамічний з БД) |
| GET | `/courses/<slug>` | Сторінка заходу за slug (динамічна з БД) |
| GET | `/course-detail` | Legacy: гінекологія (fallback на БД або статику) |
| GET | `/course-stomatology` | Legacy: стоматологія (fallback на БД або статику) |
| GET | `/course-orthopedics` | Legacy: ортопедія (fallback на БД або статику) |
| GET | `/admin/` | Адмін-панель (dashboard) |
| GET/POST | `/admin/events/new` | Створення заходу |
| GET/POST | `/admin/events/<id>/edit` | Редагування заходу |
| POST | `/admin/events/<id>/delete` | Видалення заходу |
| GET/POST | `/admin/trainers/new` | Додавання тренера |
| GET/POST | `/admin/trainers/<id>/edit` | Редагування тренера |
| POST | `/admin/trainers/<id>/delete` | Видалення тренера |
