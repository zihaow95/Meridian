"""Operator entry point for confirmation todos an earlier build left stranded.

History repair is an explicit operations decision, not a side effect of seeding or
of serving a request: it moves business facts (todos close, notices close) for work
the running process did not create. The command reports candidates by default and
only repairs when asked to.
"""

from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.convergence import converge_pending_events
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.platform.outbox.tasks import LocalOutboxPublisher
from apps.products.services.material_confirmation_repair import (
    ReissueSettlementForDecidedConfirmations,
    stranded_settlement_candidates,
)


class Command(BaseCommand):
    help = (
        "Report, and optionally repair, decided material confirmations whose "
        "confirmation todo is still open in one organization."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--actor-login-key",
            type=str,
            required=True,
            help="login_key of the operator answering for this repair (required).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Reissue settlements for the reported candidates. Reports only when omitted.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        login_key = options["actor_login_key"]
        actor = User.objects.filter(login_key=login_key, status=UserStatus.ACTIVE).first()
        if actor is None:
            raise CommandError(f"Active operator with login_key={login_key!r} not found.")

        candidates = stranded_settlement_candidates(organization_id=actor.organization_id)
        for confirmation_id in candidates:
            self.stdout.write(f"stranded confirmation {confirmation_id}")
        if not candidates:
            self.stdout.write(self.style.SUCCESS("No stranded confirmation todos found."))
            return
        if not options["apply"]:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(candidates)} candidate(s) reported. Re-run with --apply to repair."
                )
            )
            return

        try:
            reissued = ReissueSettlementForDecidedConfirmations(
                context=CommandContext.for_actor(actor),
                confirmation_public_ids=candidates,
            ).execute()
        except PermissionDeniedError as exc:
            raise CommandError("Repair denied: operator lacks product_material.manage.") from exc

        report = converge_pending_events(
            publisher=LocalOutboxPublisher(),
            event_ids=self._reissued_event_ids(reissued),
        )
        for undelivered in report.undelivered:
            self.stdout.write(self.style.ERROR(undelivered.describe()))
        self.stdout.write(
            self.style.SUCCESS(
                f"reissued={len(reissued)} dispatched={report.dispatched} "
                f"undelivered={len(report.undelivered)}"
            )
        )

    def _reissued_event_ids(self, reissued: Collection[UUID]) -> list[int]:
        return list(
            OutboxEvent.objects.filter(
                event_type="material_confirmation.decided",
                aggregate_id__in=list(reissued),
                status=OutboxStatus.PENDING,
            ).values_list("pk", flat=True)
        )
