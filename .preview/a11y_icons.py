import re, glob, os

# Інтерактивний елемент, у якому ЄДИНИЙ контент -- icon(...) і немає тексту.
PAT = re.compile(
    r"<(a|button|summary|label)\b([^>]*)>\s*\{\{ icon\('([a-z0-9_]+)'[^}]*\}\}\s*</\1>",
    re.DOTALL,
)
missing = []
for f in glob.glob('app/templates/**/*.html', recursive=True):
    txt = open(f, encoding='utf-8').read()
    for m in PAT.finditer(txt):
        tag, attrs, icon = m.group(1), m.group(2), m.group(3)
        has_name = ('aria-label' in attrs) or ('title=' in attrs)
        # icon(...) з label= теж дає назву
        call = m.group(0)
        has_icon_label = 'label=' in call
        if not has_name and not has_icon_label:
            missing.append((f.replace(os.sep, '/'), tag, icon, attrs.strip()[:70]))

print('icon-only elements WITHOUT accessible name:', len(missing))
for f, tag, icon, attrs in missing:
    print('  %-46s <%s> icon=%-16s %s' % (f.split('templates/')[-1], tag, icon, attrs))
