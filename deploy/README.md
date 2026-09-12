# deploy/ -- серверні файли продакшену

Тут лежать конфіги, які раніше існували **лише на VPS** і ніде не версіонувались.
Якщо сервер доведеться перевстановлювати, це джерело правди.

На сервері немає git-checkout: CI (`.github/workflows/deploy.yml`) робить rsync
усього репо в `/var/www/iprm/`, тож цей каталог приїжджає туди сам. Після
звичайного деплою застосувати серверні файли (ідемпотентно, робить бекап лише
коли вміст реально інший):

```bash
sudo /var/www/iprm/deploy/apply.sh
```

`apply.sh` не запускається з CI навмисно: він чіпає systemd і nginx, і робити це
мовчки на кожен push небезпечно.

| Файл | Куди ставиться |
| --- | --- |
| `nginx/iprm.conf` | `/etc/nginx/conf.d/iprm.conf` |
| `systemd/nginx.service.d-restart.conf` | `/etc/systemd/system/nginx.service.d/restart.conf` |
| `systemd/iprm-watchdog.service` | `/etc/systemd/system/iprm-watchdog.service` |
| `systemd/iprm-watchdog.timer` | `/etc/systemd/system/iprm-watchdog.timer` |
| `watchdog/iprm-healthcheck.sh` | `/usr/local/bin/iprm-healthcheck.sh` |
| `watchdog/iprm-alert.py` | `/usr/local/bin/iprm-alert.py` |

`nginx.conf` включає лише `/etc/nginx/conf.d/*.conf` -- каталоги
`sites-available`/`sites-enabled` існують, але **не** підключені.

---

## Системні пакети

Деплой через rsync ставить лише Python-залежності (`requirements.lock`).
Системні пакети на машині треба мати окремо -- ось ті, без яких код мовчки
не працює.

### postgresql-client (резервне копіювання)

**Ставить CI** -- крок у `.github/workflows/deploy.yml` перед рештою деплою:

```bash
command -v pg_dump >/dev/null || { apt-get update -qq && apt-get install -y -qq postgresql-client-16; }
```

За перевіркою наявності, тож на налаштованій машині крок безкоштовний, а
свіжа лікує себе сама. Перевірити вручну: `pg_dump --version` -> 16.x.
Сторожі над цим кроком -- `tests/test_deploy_postgresql_client.py`.

Це **клієнт, а не сервер**: лише утиліти `pg_dump`/`pg_restore`/`psql`, які
по мережі говорять із зовнішньою базою (`tnusv251.psql.tools`). Демона не
піднімає, порт не відкриває, пам'яті в спокої не їсть -- що важливо при 2 ГБ
RAM без swap. Сервер БД називався б `postgresql-16`, apt згадує його лише в
`Suggested packages`, і ставити його тут не треба й не можна.

Версія клієнта **не може бути нижчою** за версію сервера (зараз PostgreSQL
16.11 на зовнішньому хостингу): старший `pg_dump` відмовиться знімати копію
з новішої бази.

Чому це тут: `/admin/backups`, CLI-група `flask backup` і дві щоденні джоби
(автокопія о 3:00, очищення о 4:00) запускають `pg_dump`/`pg_restore` через
`subprocess`. Пакета на сервері не було з 12.06.2026 по 12.09.2026 -- копії
не створювались ані разу, і зовні це ніяк не виглядало поламаним. Тепер
сторінка показує попередження, а джоба пише в журнал один зрозумілий рядок
і надсилає лист адмінам, тож повторно це непомітним не буде.

Каталог копій створюється сам при першому запуску (`BACKUP_STORAGE_PATH`,
дефолт `/var/www/iprm/backups`) і виключений з rsync -- деплой його не чистить.

---

## Копія БД перед кожним деплоєм

Деплой робить повну копію бази **до** `flask db upgrade` -- це точка
повернення, якщо нова ревізія зробить із даними не те, що очікувалось. У
списку копій вона підписана `Перед деплоєм <7 символів коміту>`.

Порядок кроків у скрипті важливий і закріплений тестом
(`tests/test_deploy_backup_step.py`): перевірка `pg_dump` -> `pip install`
-> **копія** -> `flask db upgrade`. Копія після міграції знімала б уже
змінену схему, тобто саме той стан, від якого мала страхувати; копія до
`pip install` могла б не зробитись узагалі, якби змінились залежності.

### Збій копії зупиняє деплой

Це свідомо: деплой без точки повернення -- той самий тихий недогляд, через
який резервне копіювання простояло мертвим три місяці. `set -e` на початку
скрипта валить весь крок.

Якщо копія справді блокує потрібний деплой (скажімо, забився диск, а
виправлення саме в цьому пуші), обхід -- виконати решту кроків руками:

```bash
ssh root@<host>
cd /var/www/iprm && source venv/bin/activate
pip install -r requirements.lock --quiet
pybabel compile -d app/translations
flask db upgrade && flask rbac sync
chown -R www-data:www-data /var/www/iprm
systemctl restart iprm
```

Причину блокування видно на `/admin/backups` -- сторінка показує банер про
брак місця й про відсутні утиліти PostgreSQL.

---

## Домени

| Домен | Роль |
| --- | --- |
| `iprm.space` | основний і єдиний домен сайту |
| `www.iprm.space` | 301 на `https://iprm.space` |
| `multimed.education`, `www.` | старий домен прототипу, 301 на `https://iprm.space/` |

**`plasma-regen.com` більше не наш** (10.08.2026). Реєстрацію не продовжили
(закінчилась 04.08.2026 10:40 UTC), домен пішов на паркувальні NS
(`*.lander.d.parity.domains`) і відновлювати його не будуть. Що з цього випливає:

- server-блоки прибрано з `nginx/iprm.conf`;
- сертифікат треба видалити, інакше certbot щодня падатиме на продовженні
  (DNS уже вказує не на нас, http-01 не пройде):
  `certbot delete --cert-name plasma-regen.com`;
- вартовий пробивав сайт саме через цей хост -- `iprm-healthcheck.sh`
  переведено на `iprm.space`. Якби цього не зробити, після видалення блоків
  проба ловила б чужий server-блок, вважала сайт мертвим і перезапускала nginx
  кожні 5 хвилин;
- з блоку `iprm.space` знято `X-Robots-Tag: noindex` -- він стояв, поки домен
  був резервним дублем, і тепер тримав би основний сайт поза індексом;
- **`site_settings.website_url` у БД** треба перевірити через адмінку: з нього
  будуються посилання в листах, реферальні лінки, QR на сертифікатах і тексти
  оферти. Дефолт у моделі вже `https://iprm.space`, але рядок у БД міг лишитись
  старим. Правити тільки через адмінку -- локальна БД спільна з продом.

### Як заводити редиректний домен (на прикладі multimed.education)

DNS уже вказує на цей сервер (`A @` і `A www` -> 173.242.48.194), NS домену --
`*.srv53.*` (imena.com.ua). **Панель dnshosting.org для цього домену неактивна**:
у реєстрі стоять зовнішні NS, тож правки там ні на що не впливають.

Курка-і-яйце: блок 443 у `nginx/iprm.conf` посилається на сертифікат, якого ще
немає, а `apply.sh` робить `nginx -t` і на цьому впаде. Тому сертифікат
випускаємо **до** деплою, через тимчасовий конфіг:

```bash
mkdir -p /var/www/certbot
cat > /etc/nginx/conf.d/00-acme-multimed.conf <<'EOF'
server {
    listen 80;
    server_name multimed.education www.multimed.education;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://iprm.space/; }
}
EOF
nginx -t && systemctl reload nginx

certbot certonly --webroot -w /var/www/certbot \
    -d multimed.education -d www.multimed.education

rm /etc/nginx/conf.d/00-acme-multimed.conf   # без reload -- його зробить apply.sh
```

Далі звичайний деплой репо і `sudo /var/www/iprm/deploy/apply.sh`. Постійний
блок порту 80 містить ту саму ACME-локацію, тож автопродовження certbot працює
без ручних дій.

> **Чому `--webroot`, а не просто дати certbot розібратись.** Без окремого блоку
> `multimed.education` потрапляє в catch-all порту 80, який віддає 301 на
> `https://` -- а там для нього немає сертифіката, і перевірка http-01 гине.
> `--standalone` вимагав би зупинки nginx (і вартовий підняв би його назад).

---

## Аварія 29.07.2026 і що з неї зроблено

**Що сталося.** Security-оновлення glibc (`libc6 2.39-0ubuntu8.7 -> 8.8`) о 06:51
змусило `needrestart` перезапустити всі залежні сервіси **однією командою**:

```
systemctl restart cron.service iprm.service ... nginx.service ... systemd-resolved.service ...
```

nginx і systemd-resolved опинились в одній транзакції без залежності між собою,
тож systemd перезапустив їх одночасно. nginx стартував у ту секунду, коли DNS
був недоступний, а в конфізі GA-проксі хост був записаний буквально
(`proxy_pass https://www.googletagmanager.com/...`) -- такі хости nginx резолвить
**на старті**. Результат: `[emerg] host not found in upstream`, вихід з кодом 1,
і -- оскільки в юніті не було `Restart=` -- сервіс лишився мертвим. Сайт лежав
~13 хвилин; gunicorn при цьому працював нормально.

Це не разовий збіг: будь-яке оновлення glibc/openssl дає такий самий
перезапуск-«пачкою», тож без правок аварія повторювалася б.

**Чотири незалежні рівні захисту** (кожен ловить те, що пропустив попередній):

1. **Резолв на етапі запиту, а не старту.** Зовнішні хости винесені у змінні
   (`set $gtm_upstream ...`) + `resolver`. Тепер nginx стартує незалежно від
   стану DNS, а збій DNS дає 502 лише на `/ngx-i/`, не кладучи весь сайт.
   *Через змінну nginx не підставляє URI автоматично і не додає query-рядок --
   саме тому префікси переписані через `rewrite ... break`.*
2. **Правильний порядок у транзакції.** `After=systemd-resolved.service` --
   systemd більше не має права стартувати nginx раніше за DNS.
3. **Політика рестарту.** `Restart=on-failure`, `RestartSec=10s`,
   `StartLimitBurst=10` -- невдалий старт більше не є остаточним.
4. **Вартовий + самолікування.** `iprm-watchdog.timer` кожні 5 хвилин перевіряє
   сайт і, якщо треба, ремонтує та надсилає лист адмінам.

### Чого свідомо **не** робили

- **Не обмежували `unattended-upgrades`.** Спершу здавалося, що винні нічні
  оновлення, але в логах видно: оновлювався glibc, і це **security**-оновлення.
  Вимкнути такі -- гірше за саму аварію, а обмеження origins її б не запобігло.

---

## Вартовий (watchdog)

Кожні 5 хвилин `iprm-healthcheck.sh` пробиває сайт через nginx по loopback.

| Симптом | Дія |
| --- | --- |
| HTTP 200 | нічого (знімає прапорець збою, якщо був) |
| nginx не запущено | `systemctl start nginx` |
| nginx живий, але не відповідає (`000`) | `systemctl restart nginx` |
| 5xx | **нічого не перезапускає**, лише лист |

5xx навмисно не лікується автоматично: це означає, що nginx здоровий, а винен
застосунок, у якого вже є `Restart=always`. Автоперезапуск на 5xx лише додав би
розгойдування поверх реальної помилки.

Лист іде не частіше ніж раз на годину. За замовчуванням -- усім активним
`users.is_admin`, але серед них є нетехнічні люди (бухгалтерія), тож на цьому
хості отримувача задано явно в `/etc/iprm-watchdog.conf` (див.
`iprm-watchdog.conf.example`; файл host-specific і не версіонується):

```bash
echo 'ALERT_TO=ops@example.com' > /etc/iprm-watchdog.conf && chmod 600 /etc/iprm-watchdog.conf
```

> **Планові роботи.** Вартовий підніме nginx протягом 5 хвилин, тож перед
> навмисною зупинкою спиніть таймер:
> `systemctl stop iprm-watchdog.timer` (і `start` після робіт).

`iprm-alert.py` **навмисно не викликає `create_app()`**: той запускає
APScheduler і переписує рядки задач у спільній продакшн-БД, що неприпустимо для
процесу, який може стартувати кожні кілька хвилин. Натомість він читає
`.env` і БД напряму. Виведення ключа Fernet має лишатися синхронним з
`app/models/email_settings.py::_get_fernet`.

### Перевірка

```bash
journalctl -t iprm-watchdog -n 20          # історія перевірок
/usr/local/bin/iprm-healthcheck.sh         # прогнати вручну
echo 'test' | /usr/local/bin/iprm-alert.py 'test alert'   # перевірити пошту
```

Навчання під навантаженням (симуляція аварії): `systemctl stop nginx`, далі
`systemctl start iprm-watchdog.service` -- сайт має піднятись сам.

---

## Що лишилось поза межами сервера

**Зовнішній моніторинг.** Усе вище живе на самому VPS, тож падіння машини
цілком (мережа, диск, OOM) нікому не повідомить. Потрібен зовнішній пінгер
(UptimeRobot / Better Stack / healthchecks.io) -- реєстрація вимагає облікового
запису, тож це рішення власника.

**Swap відсутній**, RAM 2 ГБ, 1 vCPU. Пік gunicorn ~323 МБ, вільно ~1.2 ГБ --
зараз не тисне, але при сплеску OOM killer прибере воркер без права на апеляцію.
Страхувальний своп-файл (не змінює поведінку, поки пам'яті вистачає):

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl -w vm.swappiness=10 && echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
```
