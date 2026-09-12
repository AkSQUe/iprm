import re, glob, os

LABELS = {
    'edit': 'Редагувати',
    'delete': 'Видалити',
    'info': 'Деталі',
    'chevron_left': 'Попередня сторінка',
    'chevron_right': 'Наступна сторінка',
}

# Інтерактивний елемент, єдиний контент якого -- icon('name') без label/name.
PAT = re.compile(
    r"(<(a|button|summary|label)\b(?![^>]*aria-label)(?![^>]*title=)[^>]*>\s*)"
    r"\{\{ icon\('([a-z0-9_]+)'\) \}\}"
    r"(\s*</\2>)",
    re.DOTALL,
)

total = 0
for f in glob.glob('app/templates/**/*.html', recursive=True):
    txt = open(f, encoding='utf-8').read()
    cnt = [0]
    def repl(m):
        icon = m.group(3)
        if icon not in LABELS:
            return m.group(0)
        cnt[0] += 1
        return "%s{{ icon('%s', label='%s') }}%s" % (
            m.group(1), icon, LABELS[icon], m.group(4))
    new = PAT.sub(repl, txt)
    if new != txt:
        open(f, 'w', encoding='utf-8').write(new)
        print('%2d  %s' % (cnt[0], f.replace(os.sep, '/').split('templates/')[-1]))
        total += cnt[0]
print('TOTAL labels added:', total)
