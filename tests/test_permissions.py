"""Roles and permissions: the map follows the design doc's split, and
checks fail loudly on bad input."""

import re

import pytest

from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    permissions_for,
)

# The design doc's "Users and roles" table, written out again here, so a
# change to the split has to be made in two places on purpose.
INSTRUCTOR_CAN = {
    "customers.view",
    "customers.add",
    "customers.edit",
    "checkins.manual",
    "phones.link",
    "health_forms.view_status",
    "health_forms.add_doctor_note",
    "health_forms.fill_in",
    "prices.view",
}


def test_every_role_has_an_entry_in_the_map() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)


def test_the_owner_can_do_everything() -> None:
    assert ROLE_PERMISSIONS[Role.OWNER] == set(Permission)


def test_a_manager_can_do_everything_but_manage_managers() -> None:
    assert ROLE_PERMISSIONS[Role.MANAGER] == set(Permission) - {
        Permission.STAFF_MANAGE_MANAGERS
    }


def test_instructors_get_exactly_the_desk_work() -> None:
    assert ROLE_PERMISSIONS[Role.INSTRUCTOR] == INSTRUCTOR_CAN


@pytest.mark.parametrize(
    "permission",
    [
        Permission.PRICES_EDIT,
        Permission.PLANS_CHOOSE,
        Permission.PLANS_CORRECT,
        Permission.HEALTH_FORMS_VIEW_CONTENTS,
        Permission.STAFF_MANAGE,
        Permission.SETTINGS_EDIT,
    ],
)
def test_instructors_are_refused_manager_actions(permission: Permission) -> None:
    assert not has_permission(Role.INSTRUCTOR, permission)
    assert has_permission(Role.MANAGER, permission)


def test_the_stored_role_text_works_too() -> None:
    assert has_permission("instructor", Permission.CHECKINS_MANUAL)
    assert not has_permission("instructor", Permission.PRICES_EDIT)


@pytest.mark.parametrize("role", ["Owner", "Manager", "admin", ""])
def test_an_unknown_role_raises(role: str) -> None:
    with pytest.raises(ValueError):
        has_permission(role, Permission.CUSTOMERS_VIEW)


def test_the_map_cannot_be_changed_at_runtime() -> None:
    with pytest.raises(TypeError):
        ROLE_PERMISSIONS[Role.INSTRUCTOR] = frozenset(Permission)  # type: ignore[index]


def test_permission_names_are_area_dot_action() -> None:
    for permission in Permission:
        assert re.fullmatch(r"[a-z_]+\.[a-z_]+", permission.value), permission


def test_permissions_for_lists_the_roles_permissions_sorted() -> None:
    assert permissions_for(Role.INSTRUCTOR) == sorted(INSTRUCTOR_CAN)
    assert permissions_for("owner") == sorted(Permission)
    assert "staff.manage_managers" not in permissions_for("manager")
