# Деплой та сервер

## Сервер (VPS)

| Параметр | Значення |
|----------|----------|
| Хост | `173.242.58.186` |
| Користувач | `root` |
| SSH-ключ | `keys/iprm-key` |
| Шлях до проекту | `/var/www/iprm/` |
| Systemd-сервіс | `iprm` |
| WSGI-сервер | gunicorn |

### Підключення до сервера

```bash
ssh -i keys/iprm-key root@173.242.58.186
```

### Корисні команди на сервері

```bash
# Статус сервісу
systemctl status iprm

# Перезапуск
systemctl restart iprm

# Логи
journalctl -u iprm -f

# Шлях до проекту
cd /var/www/iprm
```

## CI/CD

Деплой автоматизований через GitHub Actions (`.github/workflows/deploy.yml`):

1. **Тригер:** push у гілку `main`
2. **Rsync** файлів на VPS (виключаючи `.git`, `keys/`, `.env`, `venv/`)
3. **Перезапуск** сервісу через systemd

### Необхідні секрети GitHub

| Секрет | Опис |
|--------|------|
| `VPS_HOST` | `173.242.58.186` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | Вміст `keys/iprm-key` |
