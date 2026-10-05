"""Filter definitions used by transaction and discrepancy endpoints."""

import django_filters
from django.db.models import Q, Subquery

from .models import BatchRow, Discrepancy, ReconciliationRun, Transaction


class TransactionFilter(django_filters.FilterSet):
    date_from = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lte")
    batch_id = django_filters.UUIDFilter(method="filter_batch")
    run_id = django_filters.UUIDFilter(method="filter_run")
    search = django_filters.CharFilter(method="filter_search")

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(transaction_reference__icontains=value) | Q(counterparty__icontains=value)
        )

    def filter_batch(self, queryset, name, value):
        ids = BatchRow.objects.filter(batch_id=value).values("transaction_id")
        return queryset.filter(id__in=Subquery(ids))

    def filter_run(self, queryset, name, value):
        run = ReconciliationRun.objects.filter(
            id=value, organization=self.request.user.organization,
        ).first()
        if not run:
            return queryset.none()
        ids = BatchRow.objects.filter(
            batch_id__in=[run.ledger_batch_id, run.external_batch_id],
        ).values("transaction_id")
        return queryset.filter(id__in=Subquery(ids))

    class Meta:
        model = Transaction
        fields = ["batch_id", "status", "source_type", "date_from", "date_to", "search"]


class DiscrepancyFilter(django_filters.FilterSet):
    run_id = django_filters.UUIDFilter(field_name="reconciliation_run_id")
    date_from = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="gte")
    date_to = django_filters.IsoDateTimeFilter(field_name="created_at", lookup_expr="lte")

    class Meta:
        model = Discrepancy
        fields = ["status", "discrepancy_type", "run_id", "date_from", "date_to"]
