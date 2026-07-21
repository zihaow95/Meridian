"""Operations API routes."""

from __future__ import annotations

from django.urls import path

from apps.operations.api.data_sources import (
    OperatingDataSourceListCreateView,
    OperatingDataSourcePublishView,
)
from apps.operations.api.exports import OperatingDataExportView
from apps.operations.api.ingestion import (
    OperatingIngestionBatchConfirmView,
    OperatingIngestionBatchCreateView,
    OperatingIngestionBatchDetailView,
    OperatingIngestionBatchRetryView,
    OperatingIngestionBatchValidateView,
    OperatingUnmappedRowsView,
)
from apps.operations.api.issues import (
    OperatingIssueDecisionView,
    OperatingIssueIterationProposalView,
    OperatingIssueListCreateView,
)
from apps.operations.api.metrics import (
    OperatingMetricListCreateView,
    OperatingMetricPublishView,
    OperatingMetricRecalculateView,
)
from apps.operations.api.retirement import (
    RetirementPlanCreateView,
    RetirementPlanExecuteView,
    RetirementPlanSubmitView,
    RetirementPlanValidateView,
)
from apps.operations.api.risk_rules import (
    RiskRuleEvaluateView,
    RiskRuleListCreateView,
    RiskRulePublishView,
)
from apps.operations.api.risk_signals import (
    RiskSignalCloseView,
    RiskSignalEscalateView,
    RiskSignalListView,
    RiskSignalViewView,
)
from apps.operations.api.snapshots import OperatingDataSnapshotCreateView
from apps.operations.api.summaries import (
    ProductOperatingSummaryView,
    SkuOperatingSummaryView,
)
from apps.operations.api.values import (
    OperatingValueOverrideCreateView,
    OperatingValueOverrideRevokeView,
)

urlpatterns = [
    path(
        "operating-data-sources",
        OperatingDataSourceListCreateView.as_view(),
        name="operating-data-sources",
    ),
    path(
        "operating-data-sources/<uuid:public_id>/publish",
        OperatingDataSourcePublishView.as_view(),
        name="operating-data-sources-publish",
    ),
    path(
        "operating-metrics",
        OperatingMetricListCreateView.as_view(),
        name="operating-metrics",
    ),
    path(
        "operating-metrics/recalculate",
        OperatingMetricRecalculateView.as_view(),
        name="operating-metrics-recalculate",
    ),
    path(
        "operating-metrics/<uuid:public_id>/publish",
        OperatingMetricPublishView.as_view(),
        name="operating-metrics-publish",
    ),
    path("risk-rules", RiskRuleListCreateView.as_view(), name="risk-rules"),
    path(
        "risk-rules/<uuid:public_id>/publish",
        RiskRulePublishView.as_view(),
        name="risk-rules-publish",
    ),
    path(
        "risk-rules/<uuid:public_id>/evaluate",
        RiskRuleEvaluateView.as_view(),
        name="risk-rules-evaluate",
    ),
    path(
        "operating-data/batches",
        OperatingIngestionBatchCreateView.as_view(),
        name="operating-data-batches-create",
    ),
    path(
        "operating-data/batches/<uuid:public_id>",
        OperatingIngestionBatchDetailView.as_view(),
        name="operating-data-batches-detail",
    ),
    path(
        "operating-data/batches/<uuid:public_id>/validate",
        OperatingIngestionBatchValidateView.as_view(),
        name="operating-data-batches-validate",
    ),
    path(
        "operating-data/batches/<uuid:public_id>/confirm",
        OperatingIngestionBatchConfirmView.as_view(),
        name="operating-data-batches-confirm",
    ),
    path(
        "operating-data/batches/<uuid:public_id>/retry",
        OperatingIngestionBatchRetryView.as_view(),
        name="operating-data-batches-retry",
    ),
    path(
        "operating-data/unmapped",
        OperatingUnmappedRowsView.as_view(),
        name="operating-data-unmapped",
    ),
    path(
        "operating-data/snapshots",
        OperatingDataSnapshotCreateView.as_view(),
        name="operating-data-snapshots-create",
    ),
    path(
        "operating-values/overrides",
        OperatingValueOverrideCreateView.as_view(),
        name="operating-values-overrides-create",
    ),
    path(
        "operating-values/overrides/<uuid:public_id>/revoke",
        OperatingValueOverrideRevokeView.as_view(),
        name="operating-values-overrides-revoke",
    ),
    path(
        "products/<uuid:public_id>/operating-summary",
        ProductOperatingSummaryView.as_view(),
        name="products-operating-summary",
    ),
    path(
        "skus/<uuid:public_id>/operating-summary",
        SkuOperatingSummaryView.as_view(),
        name="skus-operating-summary",
    ),
    path("risk-signals", RiskSignalListView.as_view(), name="risk-signals"),
    path(
        "risk-signals/<uuid:public_id>/view",
        RiskSignalViewView.as_view(),
        name="risk-signals-view",
    ),
    path(
        "risk-signals/<uuid:public_id>/close",
        RiskSignalCloseView.as_view(),
        name="risk-signals-close",
    ),
    path(
        "risk-signals/<uuid:public_id>/escalate",
        RiskSignalEscalateView.as_view(),
        name="risk-signals-escalate",
    ),
    path(
        "operating-issues",
        OperatingIssueListCreateView.as_view(),
        name="operating-issues",
    ),
    path(
        "operating-issues/<uuid:public_id>/decisions",
        OperatingIssueDecisionView.as_view(),
        name="operating-issues-decisions",
    ),
    path(
        "operating-issues/<uuid:public_id>/iteration-proposal",
        OperatingIssueIterationProposalView.as_view(),
        name="operating-issues-iteration-proposal",
    ),
    path(
        "retirement-plans",
        RetirementPlanCreateView.as_view(),
        name="retirement-plans-create",
    ),
    path(
        "retirement-plans/<uuid:public_id>/validate",
        RetirementPlanValidateView.as_view(),
        name="retirement-plans-validate",
    ),
    path(
        "retirement-plans/<uuid:public_id>/submit",
        RetirementPlanSubmitView.as_view(),
        name="retirement-plans-submit",
    ),
    path(
        "retirement-plans/<uuid:public_id>/execute",
        RetirementPlanExecuteView.as_view(),
        name="retirement-plans-execute",
    ),
    path(
        "operating-data/exports",
        OperatingDataExportView.as_view(),
        name="operating-data-exports",
    ),
]
