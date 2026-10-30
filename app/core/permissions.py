"""Staff roles and named permissions, and the one map between them (design
doc: "Users and roles"; decisions 0017, 0018).

Code checks a named permission (``Permission.PRICES_EDIT``), never a role,
so moving an action from one role to the other is a one-line change in
``ROLE_PERMISSIONS``. Every check happens on the server; hiding a button is
never the only protection.

The split below is the design doc's proposed one; the manager still has to
confirm it (design doc: "Open questions").
"""

from enum import StrEnum
from types import MappingProxyType


class Role(StrEnum):
    """A staff member's role. The values are what ``staff_users.role``
    stores."""

    MANAGER = "manager"
    INSTRUCTOR = "instructor"


class Permission(StrEnum):
    """Everything a role can be allowed to do, named ``<area>.<action>``."""

    # Dashboard, today's check-ins, the customer list and customer pages.
    CUSTOMERS_VIEW = "customers.view"
    CUSTOMERS_ADD = "customers.add"
    # Name, phone and notes.
    CUSTOMERS_EDIT = "customers.edit"
    # Sets the under-18 price.
    CUSTOMERS_EDIT_BIRTH_DATE = "customers.edit_birth_date"
    # The only way to remove a customer: nothing is deleted, the data and
    # the activity log stay (decision 0021).
    CUSTOMERS_ARCHIVE = "customers.archive"

    CHECKINS_MANUAL = "checkins.manual"
    # Link or unlink a customer's phone.
    PHONES_LINK = "phones.link"

    # Pick a plan for a month that has none. Instructors don't get it: their
    # manual check-in records single entry instead (design doc: "The
    # monthly choice"). That rule lives in the check-in logic, not here.
    PLANS_CHOOSE = "plans.choose"
    # Change or clear a plan already chosen.
    PLANS_CORRECT = "plans.correct"
    PLANS_FREEZE = "plans.freeze"

    # Valid or not, and when it expires.
    HEALTH_FORMS_VIEW_STATUS = "health_forms.view_status"
    HEALTH_FORMS_VIEW_CONTENTS = "health_forms.view_contents"
    HEALTH_FORMS_UPLOAD_PAPER = "health_forms.upload_paper"

    # The price table, upcoming changes and the history.
    PRICES_VIEW = "prices.view"
    PRICES_EDIT = "prices.edit"
    # View, regenerate, approve and send.
    REPORTS_MANAGE = "reports.manage"
    SETTINGS_EDIT = "settings.edit"
    # Backups and restore.
    BACKUPS_MANAGE = "backups.manage"
    # Create staff accounts, reset PINs, change roles, deactivate.
    STAFF_MANAGE = "staff.manage"
    ACTIVITY_LOG_VIEW = "activity_log.view"


_INSTRUCTOR = frozenset(
    {
        Permission.CUSTOMERS_VIEW,
        Permission.CUSTOMERS_ADD,
        Permission.CUSTOMERS_EDIT,
        Permission.CHECKINS_MANUAL,
        Permission.PHONES_LINK,
        Permission.HEALTH_FORMS_VIEW_STATUS,
        Permission.HEALTH_FORMS_UPLOAD_PAPER,
        Permission.PRICES_VIEW,
    }
)

# The one place permissions are given to roles. Read-only, so nothing can
# grant a permission at runtime.
ROLE_PERMISSIONS: MappingProxyType[Role, frozenset[Permission]] = MappingProxyType(
    {
        Role.MANAGER: frozenset(Permission),
        Role.INSTRUCTOR: _INSTRUCTOR,
    }
)


def has_permission(role: Role | str, permission: Permission) -> bool:
    """Whether ``role`` may do ``permission``.

    ``role`` may be the stored text ("manager"). A role that doesn't exist
    raises ``ValueError`` instead of quietly allowing nothing, so bad data
    is noticed.
    """
    return permission in ROLE_PERMISSIONS[Role(role)]
