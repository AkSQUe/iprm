"""Тести підписаної PDF-версії оферти (/offer/pdf)."""
import pytest

from app.services.legal_pdf_service import DOWNLOAD_NAME


def _weasyprint_available():
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


requires_weasyprint = pytest.mark.skipif(
    not _weasyprint_available(), reason='WeasyPrint недоступний (немає GTK)')


class TestOfferPage:
    def test_page_shows_download_button(self, client):
        response = client.get('/offer')
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert '/offer/pdf' in html
        assert 'legal-page__download' in html

    def test_pdf_version_has_no_button(self, app):
        """Кнопка -- елемент сайту, у документі її бути не повинно."""
        from flask import render_template

        with app.test_request_context('/'):
            html = render_template('main/offer_pdf.html', logo_path='',
                                   seal_path='', signer_title='Ректор',
                                   signer_name='Тест')
        assert 'legal-page__download' not in html
        assert 'Публічна оферта про надання' in html


@requires_weasyprint
class TestOfferPdfRoute:
    def test_returns_pdf_attachment(self, client):
        response = client.get('/offer/pdf')
        assert response.status_code == 200
        assert response.mimetype == 'application/pdf'
        assert response.data.startswith(b'%PDF')

        disposition = response.headers['Content-Disposition']
        assert disposition.startswith('attachment')
        # не-ASCII ім'я передається через filename* (RFC 6266)
        assert 'filename*=UTF-8' in disposition

    def test_document_is_multipage_and_signed(self, app):
        from app.services.legal_pdf_service import render_offer_pdf

        with app.test_request_context('/'):
            pdf = render_offer_pdf()
        assert pdf.startswith(b'%PDF')
        # печатка -- єдине растрове зображення документа
        assert b'/Image' in pdf

    def test_download_name_is_readable(self):
        assert DOWNLOAD_NAME.endswith('.pdf')
        assert 'оферта' in DOWNLOAD_NAME.lower()
