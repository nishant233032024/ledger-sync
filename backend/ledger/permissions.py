"""Small, explicit role permissions used by API views."""

from django.conf import settings
from rest_framework.permissions import BasePermission, SAFE_METHODS

from .models import User


class IsTenantMember(BasePermission):
    """A valid JWT alone is insufficient without active tenant membership."""

    message = "An active organization membership is required."

    def has_permission(self, request, view):
        if settings.LEDGERSYNC_PUBLIC_DEMO and request.method not in SAFE_METHODS:
            self.message = "The public interview demo is read-only."
            return False
        return bool(
            request.user.is_authenticated
            and request.user.organization_id
            and request.user.organization.is_active
        )


class IsFinanceManagerOrAdmin(BasePermission):
    message = "Finance Managers and Administrators may perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role in {
                User.Role.ADMIN,
                User.Role.FINANCE_MANAGER,
            }
        )


class IsAdmin(BasePermission):
    message = "Only Administrators may perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == User.Role.ADMIN
        )
