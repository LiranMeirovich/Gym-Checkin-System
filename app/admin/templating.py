"""Jinja2 templates for the admin app's pages (decisions 0002, 0003).

Every page extends ``base.html``, which sets Hebrew and right-to-left.
Autoescaping is on for ``.html`` files (Jinja2Templates' default), so a
staff or customer name can never inject markup into a page.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
