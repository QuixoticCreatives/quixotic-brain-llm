"""Security review 2026-11-24 F1 (PRD §8, §10: the access level counts as much as the department).
A reviewer or Knowledge Admin must not see, decide or copy a proposal whose document sits at a level their role cannot read."""
from types import SimpleNamespace
from uuid import uuid4

from backend.knowledge.service import KnowledgeService
from backend.permissions.access import Principal
from backend.permissions.roles import Role

LEVELS = {"internal": frozenset({"employee", "department_reviewer", "knowledge_admin", "system_admin", "founder_ceo"}),
          "restricted": frozenset({"system_admin", "founder_ceo"})}
D = uuid4()


def _ks(item):
    ks = KnowledgeService.__new__(KnowledgeService)
    ks.svc = SimpleNamespace(settings=SimpleNamespace(sensitivity_levels=LEVELS))
    ks.store = SimpleNamespace(get_item=lambda _id: item)
    return ks


def _p(role, can_publish=False, managed=(D,)):
    return Principal(uuid4(), "x", role, frozenset({D}), frozenset(managed), can_publish)


def test_publisher_knowledge_admin_cannot_review_a_restricted_proposal():
    ks = _ks({"department_ids": [D], "sensitivity": "restricted"})
    prop = {"item_id": uuid4(), "meta": {"department_ids": [str(D)], "sensitivity": "restricted"}}
    assert not ks.may_review_proposal(_p(Role.KNOWLEDGE_ADMIN, can_publish=True), prop)
    assert not ks.may_review_proposal(_p(Role.DEPARTMENT_REVIEWER), prop)
    assert ks.may_review_proposal(_p(Role.FOUNDER_CEO), prop)


def test_moving_a_document_up_to_restricted_hides_the_proposal_from_lower_reviewers():
    ks = _ks({"department_ids": [D], "sensitivity": "internal"})
    prop = {"item_id": uuid4(), "meta": {"department_ids": [str(D)], "sensitivity": "restricted"}}
    assert not ks.may_review_proposal(_p(Role.DEPARTMENT_REVIEWER), prop)
    prop["meta"]["sensitivity"] = "internal"
    assert ks.may_review_proposal(_p(Role.DEPARTMENT_REVIEWER), prop)


def test_unknown_level_is_denied():
    ks = _ks({"department_ids": [D], "sensitivity": "secret-new-level"})
    assert not ks.may_review_proposal(_p(Role.KNOWLEDGE_ADMIN, can_publish=True), {"item_id": uuid4(), "meta": {}})


def test_all_department_roles_still_need_the_level_to_see_an_item():
    ks = _ks(None)
    restricted = {"department_ids": [D], "sensitivity": "restricted"}
    assert not ks._may_see(_p(Role.KNOWLEDGE_ADMIN, can_publish=True), restricted)   # so it cannot propose updates to it
    assert ks._may_see(_p(Role.SYSTEM_ADMIN), restricted)
    assert ks._may_see(_p(Role.KNOWLEDGE_ADMIN), {"department_ids": [uuid4()], "sensitivity": "internal"})


def _gap_ks(proposal, gap_status="in_progress"):
    from types import SimpleNamespace as NS
    updates = []
    ks = KnowledgeService.__new__(KnowledgeService)
    gaps = NS(get=lambda _id: {"status": gap_status}, update=lambda gid, **k: updates.append(k))
    ks.store = NS(get_proposal=lambda _id: proposal, set_proposal_status=lambda *a, **k: True, set_status=lambda *a: None)
    ks.svc = NS(gaps=gaps, ops=NS(audit=lambda *a: None), settings=NS(sensitivity_levels=LEVELS))
    return ks, updates


def test_withdrawing_the_answer_to_a_missing_info_report_reopens_the_report():
    """Bug review 2026-11-24: the report stayed 'in progress' for ever once its proposal was withdrawn (PRD §9 gap loop)."""
    me = _p(Role.KNOWLEDGE_ADMIN)
    prop = {"id": uuid4(), "kind": "create", "version_id": uuid4(), "gap_id": uuid4(), "submitted_by": me.user_id}
    ks, updates = _gap_ks(prop)
    ks.withdraw(me, prop["id"])
    assert updates == [{"status": "open"}]
    ks, updates = _gap_ks(prop, gap_status="resolved")
    ks.withdraw(me, prop["id"])
    assert updates == []                                              # a report someone already closed is left alone
