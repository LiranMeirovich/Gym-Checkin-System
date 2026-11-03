"""Request and response shapes of the public API. The public React app's
TypeScript types are generated from these (through the OpenAPI spec)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.http import Answer


class Me(Answer):
    """The customer this phone is linked to: only what the page shows."""

    first_name: str


class NotLinked(Answer):
    """401: this phone has no live link (no cookie, or it was unlinked,
    went unused for a year, or its customer was deactivated). The page
    shows the link form."""

    detail: Literal["not_linked"] = "not_linked"


class LinkRequest(BaseModel):
    # Real values are far shorter; the caps only keep junk out.
    phone: str = Field(max_length=50)
    code: str = Field(max_length=20)


class LinkRefused(Answer):
    """400: the number and code don't link this phone. One answer for
    every reason, so it never says whether a number is a customer's."""

    detail: Literal["link_refused"] = "link_refused"
