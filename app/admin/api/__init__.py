"""The admin app's JSON API, under ``/api`` (decision 0020).

Routes stay thin: they check the login (``CurrentStaff`` or
``require_permission``), validate the request with its Pydantic schema
(``schemas``), call ``app.core`` and return the result. Errors are codes,
never Hebrew text: the React app holds the wording.

This module imports none of its route modules, so ``security`` can use
``schemas`` without an import cycle; ``main`` mounts the routers.
"""
