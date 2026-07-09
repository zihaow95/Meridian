"""Product API routes."""

from __future__ import annotations

from django.urls import path

from apps.products.api.drafts import ProductDraftDetailView

urlpatterns = [
    path(
        "product-drafts/<uuid:public_id>",
        ProductDraftDetailView.as_view(),
        name="product-draft-detail",
    ),
]
