"""Product API routes."""

from __future__ import annotations

from django.urls import path

from apps.products.api.bindings import ProductExternalBindingUpsertView
from apps.products.api.change_sets import (
    ApproveAttributeGroupView,
    ApproveChangeSetView,
    ProductChangeSetCreateView,
    ProductChangeSetDetailView,
    ProductChangeSetDiffView,
    ProductChangeSetEditView,
    PublishChangeSetView,
    ReassignAttributeConfirmerView,
    ReturnAttributeGroupView,
    SubmitChangeSetConfirmationView,
    UpdateChangeSetScopeView,
    ValidatePublicationView,
)
from apps.products.api.drafts import ProductDraftDetailView
from apps.products.api.imports import (
    ProductImportBatchConfirmView,
    ProductImportBatchCreateView,
    ProductImportBatchDetailView,
    ProductImportItemDecideView,
    ProductImportTemplateDownloadView,
    PublishLegacyBaselineView,
)
from apps.products.api.products import ProductDetailView, ProductListView

urlpatterns = [
    path("products", ProductListView.as_view(), name="product-list"),
    path("products/<uuid:public_id>", ProductDetailView.as_view(), name="product-detail"),
    path(
        "products/<uuid:public_id>/external-bindings",
        ProductExternalBindingUpsertView.as_view(),
        name="product-external-binding-upsert",
    ),
    path(
        "products/<uuid:public_id>/change-sets",
        ProductChangeSetCreateView.as_view(),
        name="product-change-set-create",
    ),
    path(
        "product-drafts/<uuid:public_id>",
        ProductDraftDetailView.as_view(),
        name="product-draft-detail",
    ),
    path(
        "product-change-sets/<uuid:public_id>",
        ProductChangeSetDetailView.as_view(),
        name="product-change-set-detail",
    ),
    path(
        "product-change-sets/<uuid:public_id>/diff",
        ProductChangeSetDiffView.as_view(),
        name="product-change-set-diff",
    ),
    path(
        "product-change-sets/<uuid:public_id>/edit-group",
        ProductChangeSetEditView.as_view(),
        name="product-change-set-edit-group",
    ),
    path(
        "product-change-sets/<uuid:public_id>/update-scope",
        UpdateChangeSetScopeView.as_view(),
        name="product-change-set-update-scope",
    ),
    path(
        "product-change-sets/<uuid:public_id>/submit-confirmation",
        SubmitChangeSetConfirmationView.as_view(),
        name="product-change-set-submit-confirmation",
    ),
    path(
        "product-change-sets/<uuid:public_id>/approve",
        ApproveChangeSetView.as_view(),
        name="product-change-set-approve",
    ),
    path(
        "product-change-sets/<uuid:public_id>/approve-attribute-group",
        ApproveAttributeGroupView.as_view(),
        name="product-change-set-approve-attribute-group",
    ),
    path(
        "product-change-sets/<uuid:public_id>/return-attribute-group",
        ReturnAttributeGroupView.as_view(),
        name="product-change-set-return-attribute-group",
    ),
    path(
        "product-change-sets/<uuid:public_id>/reassign-confirmer",
        ReassignAttributeConfirmerView.as_view(),
        name="product-change-set-reassign-confirmer",
    ),
    path(
        "product-change-sets/<uuid:public_id>/validate-publication",
        ValidatePublicationView.as_view(),
        name="product-change-set-validate-publication",
    ),
    path(
        "product-change-sets/<uuid:public_id>/publish",
        PublishChangeSetView.as_view(),
        name="product-change-set-publish",
    ),
    path(
        "product-import-batches",
        ProductImportBatchCreateView.as_view(),
        name="product-import-batch-create",
    ),
    path(
        "product-import-template",
        ProductImportTemplateDownloadView.as_view(),
        name="product-import-template-download",
    ),
    path(
        "product-import-batches/<uuid:public_id>",
        ProductImportBatchDetailView.as_view(),
        name="product-import-batch-detail",
    ),
    path(
        "product-import-batches/<uuid:public_id>/confirm",
        ProductImportBatchConfirmView.as_view(),
        name="product-import-batch-confirm",
    ),
    path(
        "product-import-batches/<uuid:public_id>/decide-item",
        ProductImportItemDecideView.as_view(),
        name="product-import-item-decide",
    ),
    path(
        "legacy-baselines/<uuid:public_id>/publish",
        PublishLegacyBaselineView.as_view(),
        name="legacy-baseline-publish",
    ),
]
