"""Project shell invariants."""

from __future__ import annotations

import pytest

from apps.opportunities.models import CandidateStatus
from apps.projects.models import ProjectMember, ProjectOpportunitySource, ProjectRole


@pytest.mark.django_db
def test_project_links_candidate_leader_and_sources(project, approved_candidate) -> None:
    approved_candidate.refresh_from_db()
    assert approved_candidate.status == CandidateStatus.PROJECT_CREATED
    assert project.candidate_id == approved_candidate.id
    assert project.leader_id == approved_candidate.case_owner_id
    assert ProjectMember.objects.filter(project=project, project_role=ProjectRole.LEADER).exists()
    assert ProjectOpportunitySource.objects.filter(project=project).count() >= 1
