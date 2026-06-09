"""Тести санітизації: контент блогу та регалії тренера."""
from app.services import blog_service as bs
from app.services import trainer_service as ts


class TestBlogSanitize:
    def test_drops_script_and_keeps_safe_html(self):
        out = bs.sanitize_content([
            {'type': 'paragraph', 'data': {'html': 'Текст <b>жирн</b> <script>x</script>'}},
        ])
        assert len(out) == 1
        assert '<script>' not in out[0]['data']['html']
        assert '<b>' in out[0]['data']['html']

    def test_drops_javascript_link(self):
        out = bs.sanitize_content([
            {'type': 'paragraph', 'data': {'html': '<a href="javascript:evil()">x</a>'}},
        ])
        # посилання лишається без небезпечного href
        assert 'javascript:' not in out[0]['data']['html']

    def test_youtube_id_extracted_and_validated(self):
        ok = bs.sanitize_content([{'type': 'youtube', 'data': {'url': 'https://youtu.be/dQw4w9WgXcQ'}}])
        assert ok[0]['data']['video_id'] == 'dQw4w9WgXcQ'
        bad = bs.sanitize_content([{'type': 'youtube', 'data': {'video_id': 'nope'}}])
        assert bad == []

    def test_image_local_only(self):
        good = bs.sanitize_content([{'type': 'image', 'data': {
            'url': '/static/images/blog/p/a.webp', 'thumb': '/static/images/blog/p/a_thumb.webp'}}])
        assert len(good) == 1
        assert bs.sanitize_content([{'type': 'image', 'data': {'url': 'https://evil.com/x.webp'}}]) == []
        assert bs.sanitize_content([{'type': 'image', 'data': {'url': '/static/images/blog/../x.webp'}}]) == []

    def test_unknown_block_dropped(self):
        assert bs.sanitize_content([{'type': 'evil', 'data': {}}]) == []

    def test_slugify_transliterates(self):
        assert bs.slugify('Підсумки заходу 2026!') == 'pidsumky-zakhodu-2026'


class TestTrainerSanitize:
    def test_links_scheme_and_label(self):
        out = ts.sanitize_links([
            {'label': '<b>Патент</b>', 'url': 'https://ok.com/1'},
            {'label': 'x', 'url': 'javascript:alert(1)'},
            {'label': '', 'url': 'https://ok.com/2'},
        ])
        assert len(out) == 2
        assert out[0]['label'] == 'Патент'  # HTML вирізано
        assert out[1]['label'] == 'https://ok.com/2'  # порожній label -> url

    def test_certificates_local_only(self):
        out = ts.sanitize_certificates([
            {'url': '/static/images/trainers/x/certificates/a.webp'},
            {'url': 'https://evil.com/a.webp'},
            {'url': '/static/images/trainers/x/../../e.webp'},
        ])
        assert len(out) == 1

    def test_research_lines(self):
        out = ts.sanitize_research('Пункт А\n\n  \n<script>y</script>Пункт Б')
        assert out[0] == 'Пункт А'
        assert all('<script>' not in x for x in out)
        assert len(out) == 2
