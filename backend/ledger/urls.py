"""Application URL routes."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    BatchListView, BatchStatusView, BatchUploadView, DiscrepancyListView,
    HealthView, LedgerTokenView, MeView, ResolveDiscrepancyView, RuleView, RunView,
    RetryBatchView, RetryRunView, SummaryView, TransactionListView,
)


urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("auth/token/", LedgerTokenView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("batches/", BatchListView.as_view(), name="batch-list"),
    path("batches/upload/", BatchUploadView.as_view(), name="batch-upload"),
    path("batches/<uuid:batch_id>/status/", BatchStatusView.as_view(), name="batch-status"),
    path("batches/<uuid:batch_id>/retry/", RetryBatchView.as_view(), name="batch-retry"),
    path("transactions/", TransactionListView.as_view(), name="transaction-list"),
    path("discrepancies/", DiscrepancyListView.as_view(), name="discrepancy-list"),
    path("discrepancies/<uuid:discrepancy_id>/resolve/", ResolveDiscrepancyView.as_view(), name="discrepancy-resolve"),
    path("reconciliation/runs/", RunView.as_view(), name="reconciliation-start"),
    path("reconciliation/runs/<uuid:run_id>/retry/", RetryRunView.as_view(), name="reconciliation-retry"),
    path("rules/", RuleView.as_view(), name="rules"),
    path("summary/", SummaryView.as_view(), name="summary"),
]
