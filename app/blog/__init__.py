from app.i18n import LocalizedBlueprint

blog_bp = LocalizedBlueprint('blog', __name__, url_prefix='/blog')

from app.blog import routes  # noqa: F401,E402
from app.blog import routes_comments  # noqa: F401,E402
