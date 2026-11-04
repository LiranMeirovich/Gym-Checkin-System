"""The public app's JSON API, under ``/api`` (decision 0020): what a
customer's phone talks to.

Routes stay thin: they find the phone's device session from the
``gym_device`` cookie where they need one, validate the request with its
Pydantic schema (``schemas``), call ``app.core`` and return the result.
Errors are codes, never Hebrew text: the React app holds the wording.
Nothing here is admin code, and nothing here imports any.

A customer only ever sees their own first name (more in later features:
their plan and visits), never anyone else's data.
"""
