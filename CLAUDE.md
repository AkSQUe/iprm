# CLAUDE.md -- IPRM

Уточнення до глобального `~/.claude/CLAUDE.md` для цього репозиторію. Усе,
чого тут немає, діє за глобальним файлом.

## Інструменти дизайн-системи

Глобальний файл посилається на `1-instruments/design-system/` і
`1-instruments/hygiene-ci/thresholds.json`. Цей каталог є в site-mm-medic
і site-santehpoliv, а в IPRM **його немає**. Тут ті самі перевірки робить:

| Глобальний файл | У цьому репозиторії |
|---|---|
| `layer_check.py` (компонентний чи посторінковий, `page-*`) | `python tools/ds/ds_audit.py` -- `classify_css`, `naming_mismatch` |
| `shadowed_rules.py` (клас, оголошений двічі) | `python tools/ds/ds_audit.py` -- `duplicate_classes` |
| `atom-audit.cjs` | окремого інструмента немає; перестилізовані компоненти в `page-*` показує той самий `ds_audit.py` |
| `snapshot.cjs` (до і після) | `python tools/ds/html_snapshot.py` (розмітка) і `python tools/ds/computed_snapshot.py` (обчислені стилі) |
| `hygiene-ci/thresholds.json` | базові лінії `tests/test_design_system/*_baseline.json` |

* Сторожі: `pytest tests/test_design_system/`.
* Процедури проходу: `/ds-consolidate` і `/ds-unify` (`.claude/commands/`).
* Опис інструментів і заміряні числа: `tools/ds/README.md`.
