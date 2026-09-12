import re, glob, os

extra = re.compile(r'<span class="material-symbols-rounded ([a-z_-]+)">([a-z_]+)</span>')
aria  = re.compile(r'<span class="material-symbols-rounded" aria-hidden="true">([a-z_]+)</span>')
simple = re.compile(r'<span class="material-symbols-rounded">([a-z_]+)</span>')

total = 0
per_file = {}
for f in glob.glob('app/templates/**/*.html', recursive=True):
    txt = open(f, encoding='utf-8').read()
    orig = txt
    n = 0
    def sub_extra(m):
        global n; n += 1
        return "{{ icon('%s', cls='%s') }}" % (m.group(2), m.group(1))
    def sub_aria(m):
        global n; n += 1
        return "{{ icon('%s') }}" % m.group(1)
    def sub_simple(m):
        global n; n += 1
        return "{{ icon('%s') }}" % m.group(1)
    txt = extra.sub(sub_extra, txt)
    txt = aria.sub(sub_aria, txt)
    txt = simple.sub(sub_simple, txt)
    if txt != orig:
        open(f, 'w', encoding='utf-8').write(txt)
        per_file[f.replace(os.sep, '/')] = n
        total += n

for f, n in sorted(per_file.items()):
    print('%3d  %s' % (n, f))
print('TOTAL migrated:', total, 'in', len(per_file), 'files')
