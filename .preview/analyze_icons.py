import re, glob, os
simple = re.compile(r'<span class="material-symbols-rounded">[a-z_]+</span>')
extra  = re.compile(r'<span class="material-symbols-rounded ([a-z_-]+)">[a-z_]+</span>')
total = simple_n = extra_n = 0
other = []
for f in glob.glob('app/templates/**/*.html', recursive=True):
    txt = open(f, encoding='utf-8').read()
    total += txt.count('material-symbols-rounded')
    for m in re.finditer(r'<span[^>]*material-symbols-rounded[^>]*>[^<]*</span>', txt):
        s = m.group(0)
        if simple.fullmatch(s):
            simple_n += 1
        elif extra.fullmatch(s):
            extra_n += 1
        else:
            other.append((f.replace(os.sep, '/'), s))
print('total tokens:', total)
print('simple:', simple_n, 'extra-class:', extra_n, 'OTHER:', len(other))
for f, s in other:
    print('  ', f, '::', s[:140])
