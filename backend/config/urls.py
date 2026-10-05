"""Top-level URL configuration."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    # Django Admin is useful for inspecting users, batches, and audit logs.
    path("admin/", admin.site.urls),
    # All versioned application endpoints live under this prefix.
    path("api/v1/", include("ledger.urls")),
]
