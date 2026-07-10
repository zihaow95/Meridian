"""Product API routes."""

from __future__ import annotations

from django.urls import path

from apps.products.api.change_sets import (
    ProductChangeSetDetailView,
    ProductChangeSetDiffView,
    ProductChangeSetEditView,
    PublishChangeSetView,
    ValidatePublicationView,
)
from apps.products.api.drafts import ProductDraftDetailView
from apps.products.api.products import ProductDetailView, ProductListView

urlpatterns = [
    path("products", ProductListView.as_view(), name="product-list"),
    path("products/<uuid:public_id>", ProductDetailView.as_view(), name="product-detail"),
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
        "product-change-sets/<uuid:public_id>/validate-publication",
        ValidatePublicationView.as_view(),
        name="product-change-set-validate-publication",
    ),
    path(
        "product-change-sets/<uuid:public_id>/publish",
        PublishChangeSetView.as_view(),
        name="product-change-set-publish",
    ),
]
