"""Підписана PDF-версія публічної оферти (WeasyPrint).

Текст береться з того самого партіала, що й веб-сторінка
(main/_offer_content.html), тому PDF не розходиться із сайтом. Верстка
повторює .docx-експорт: бланк у колонтитулі, Times New Roman 12pt,
поля 2/1/3/2 см, печатка з підписом у кінці.
"""
import logging

from flask import current_app, render_template

logger = logging.getLogger(__name__)

LOGO_PATH = 'svg/IPRM-logo-complex.svg'
SEAL_PATH = 'images/legal/seal-signature.png'
DOWNLOAD_NAME = 'ІПРМ - Публічна оферта.pdf'


class LegalPdfError(RuntimeError):
    """Не вдалося згенерувати PDF юридичного документа."""


def render_offer_pdf():
    """Повернути PDF публічної оферти у вигляді bytes."""
    try:
        from weasyprint import HTML  # ліниво: на машинах без GTK імпорт падає
    except Exception as exc:
        logger.exception('WeasyPrint unavailable for offer PDF')
        raise LegalPdfError('PDF-рендер недоступний: %s' % exc)

    from app.services.legal_docx_service import (
        DEFAULT_SIGNER_NAME, DEFAULT_SIGNER_TITLE,
    )

    try:
        html = render_template(
            'main/offer_pdf.html',
            logo_path=LOGO_PATH,
            seal_path=SEAL_PATH,
            signer_title=current_app.config.get(
                'LEGAL_DOCX_SIGNER_TITLE', DEFAULT_SIGNER_TITLE),
            signer_name=current_app.config.get(
                'LEGAL_DOCX_SIGNER_NAME', DEFAULT_SIGNER_NAME),
        )
        # base_url = static: шляхи до логотипа й печатки відносні до нього
        return HTML(string=html, base_url=current_app.static_folder).write_pdf()
    except Exception as exc:
        logger.exception('Offer PDF render failed')
        raise LegalPdfError('Помилка генерації PDF-оферти: %s' % exc)
