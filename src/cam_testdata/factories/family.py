"""Family area (TODO 3.3): Family, FamilyMembership, FamilyRelationship, make_family().

FamilyRelationship reads: family_member_id <relation> subject_id,
e.g. mother KIN:027 (isBiologicalMotherOf) proband.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

import factory
from common_access_model.datamodel.common_access_model_sqla import (
    Family,
    FamilyMembership,
    FamilyRelationship,
    Subject,
)

from cam_testdata.build import current_build
from cam_testdata.factories.base import RecordFactory, default_handle, minted_id
from cam_testdata.factories.study import StudyFactory
from cam_testdata.factories.subject import DemographicsFactory, SubjectFactory

PROBAND = "snomedct:85900004"
MOTHER_ROLE = "KIN:027"  # isBiologicalMotherOf
FATHER_ROLE = "KIN:028"  # isBiologicalFatherOf
FEMALE = "snomedct:248152002"
MALE = "snomedct:248153007"
FAMILY_TYPES = {
    "trio": "CAMO:0000004",
    "duo": "CAMO:0000003",
    "singleton": "CAMO:0000007",
}


class FamilyFactory(RecordFactory):
    class Meta:
        model = Family

    class Params:
        handle = default_handle("Family")
        scope = factory.SubFactory(StudyFactory)

    family_id = minted_id("Family")
    family_type = None
    family_description = None
    consanguinity = None
    family_study_focus = None


class FamilyMembershipFactory(RecordFactory):
    class Meta:
        model = FamilyMembership

    class Params:
        handle = default_handle("FamilyMembership")
        family = factory.SubFactory(FamilyFactory)
        subject = factory.SubFactory(
            SubjectFactory, scope=factory.SelfAttribute("..family")
        )
        scope = factory.SelfAttribute("family")

    family_membership_id = minted_id("FamilyMembership")
    family_id = factory.SelfAttribute("family.family_id")
    subject_id = factory.SelfAttribute("subject.subject_id")
    family_role = None


class FamilyRelationshipFactory(RecordFactory):
    class Meta:
        model = FamilyRelationship

    class Params:
        handle = default_handle("FamilyRelationship")
        member = factory.SubFactory(SubjectFactory)
        subject = factory.SubFactory(
            SubjectFactory, scope=factory.SelfAttribute("..member")
        )
        scope = factory.SelfAttribute("subject")

    family_relationship_id = minted_id("FamilyRelationship")
    family_member_id = factory.SelfAttribute("member.subject_id")
    relation = "KIN:001"  # isRelativeOf
    subject_id = factory.SelfAttribute("subject.subject_id")


@dataclass
class FamilyUnit:
    family: Family
    proband: Subject
    mother: Subject | None = None
    father: Subject | None = None
    members: dict[str, Subject] = field(default_factory=dict)
    demographics: dict[str, Any] = field(default_factory=dict)  # role -> Demographics


def make_family(
    kind: Literal["trio", "duo", "singleton"],
    study: Any,
    key: str,
    member_demographics: dict[str, dict[str, Any]] | None = None,
    **proband_demographics: Any,
) -> FamilyUnit:
    """A family with Participant subjects, Demographics, memberships and relationships.

    Handles: <profile>/<Class>/<key>-proband (-mother, -father). A duo is proband + mother.
    `member_demographics` maps a role to Demographics fields; keyword arguments
    are shorthand for the proband's.
    """
    member_demographics = dict(member_demographics or {})
    if proband_demographics:
        member_demographics["proband"] = {
            **member_demographics.get("proband", {}),
            **proband_demographics,
        }
    build = current_build()
    family = FamilyFactory(
        handle=build.handle("Family", key), scope=study, family_type=FAMILY_TYPES[kind]
    )
    roles: dict[str, tuple[str, str | None]] = {"proband": (PROBAND, None)}
    if kind in ("trio", "duo"):
        roles["mother"] = (MOTHER_ROLE, FEMALE)
    if kind == "trio":
        roles["father"] = (FATHER_ROLE, MALE)

    members: dict[str, Subject] = {}
    demographics_by_role: dict[str, Any] = {}
    for name, (role, sex) in roles.items():
        member_key = f"{key}-{name}"
        subject = SubjectFactory(
            handle=build.handle("Subject", member_key), scope=study
        )
        demographics: dict[str, Any] = dict(member_demographics.get(name, {}))
        if sex is not None:
            demographics.setdefault("sex", sex)
        demographics_by_role[name] = DemographicsFactory(
            handle=build.handle("Demographics", member_key),
            subject=subject,
            **demographics,
        )
        FamilyMembershipFactory(
            handle=build.handle("FamilyMembership", member_key),
            family=family,
            subject=subject,
            family_role=role,
        )
        members[name] = subject
    unit = FamilyUnit(
        family=family,
        proband=members["proband"],
        mother=members.get("mother"),
        father=members.get("father"),
        members=members,
        demographics=demographics_by_role,
    )

    for name, relation in (("mother", MOTHER_ROLE), ("father", FATHER_ROLE)):
        parent = unit.members.get(name)
        if parent is not None:
            FamilyRelationshipFactory(
                handle=build.handle("FamilyRelationship", f"{key}-{name}-of-proband"),
                member=parent,
                subject=unit.proband,
                relation=relation,
            )
    return unit
