"""Study area (TODO 3.1): AccessPolicy, Study, StudyMetadata, VirtualBiorepository,
DOI, Investigator, Publication.

Study <-> DOI is an FK cycle: create the Study, then the DOI, then `attach_doi()`.
The Build inserts Study with do_id NULL and sets it after the DOI (DESIGN §6.1).
"""

import re
from typing import Any

import factory
from common_access_model.datamodel.common_access_model_sqla import (
    DOI,
    AccessPolicy,
    Investigator,
    Publication,
    Study,
    StudyMetadata,
    VirtualBiorepository,
)

from cam_testdata.factories.base import (
    BaseFactory,
    RecordFactory,
    default_handle,
    filler,
    linked,
    minted_id,
)


def _key(handle: str) -> str:
    return handle.rsplit("/", 1)[-1]


class AccessPolicyFactory(BaseFactory):
    class Meta:
        model = AccessPolicy

    class Params:
        handle = default_handle("AccessPolicy")
        pinned_id = None

    access_policy_id = minted_id("AccessPolicy")
    data_use_accession = None
    data_use_permission = "DUO:0000042"  # general research use
    data_use_modifier = None
    disease_limitation = None
    access_description = filler("access_description", "access_description")
    website = None


class StudyFactory(RecordFactory):
    class Meta:
        model = Study

    class Params:
        handle = default_handle("Study")
        access_policy = factory.SubFactory(AccessPolicyFactory)
        parent = None

    study_id = minted_id("Study")
    access_policy_id = factory.SelfAttribute("access_policy.access_policy_id")
    parent_study = factory.LazyAttribute(
        lambda o: o.parent.study_id if o.parent else None
    )
    study_title = filler("study_title", "study_title")
    study_code = factory.LazyAttribute(lambda o: _key(o.handle).upper())
    study_short_name = None
    study_description = filler("study_description", "study_description")
    website = None
    acknowledgments = None
    citation_statement = None
    do_id = None  # set by attach_doi()

    program = linked("program")
    funding_source = linked("funding_source")
    principal_investigator = linked("principal_investigator")
    contact = linked("contact")
    publication = linked("publication")


def attach_doi(study: Study, doi: DOI) -> None:
    """Close the Study <-> DOI cycle (the Build defers this FK until the DOI exists)."""
    study.do_id = doi.do_id


class StudyMetadataFactory(RecordFactory):
    """One per Study (R3); shares the Study's ID."""

    class Meta:
        model = StudyMetadata

    class Params:
        handle = default_handle("StudyMetadata")
        study = factory.SubFactory(StudyFactory)
        scope = factory.SelfAttribute("study")
        vbr = None

    study_id = factory.SelfAttribute("study.study_id")
    selection_criteria = None
    vbr_id = factory.LazyAttribute(lambda o: o.vbr.vbr_id if o.vbr else None)
    expected_number_of_participants = 0
    actual_number_of_participants = (
        0  # the scenario sets it to the participant count (R8)
    )

    participant_lifespan_stage = linked("participant_lifespan_stage")
    study_design = linked("study_design")
    clinical_data_source_type = linked("clinical_data_source_type")
    data_category = linked("data_category")
    research_domain = linked("research_domain")


class VirtualBiorepositoryFactory(RecordFactory):
    class Meta:
        model = VirtualBiorepository

    class Params:
        handle = default_handle("VirtualBiorepository")
        scope = factory.SubFactory(StudyFactory)

    vbr_id = minted_id("VirtualBiorepository")
    name = filler("vbr_name", "repository_name")
    institution = filler("vbr_institution", "institution")
    website = None
    vbr_readme = None

    contact = linked("contact")


class DOIFactory(RecordFactory):
    class Meta:
        model = DOI

    class Params:
        handle = default_handle("DOI")
        scope = factory.SubFactory(StudyFactory)

    do_id = minted_id("DOI")
    bibliographic_reference = filler("doi_reference", "bibliographic_reference")


def _example_email(o: Any) -> str:
    local = re.sub(r"[^a-z]+", ".", o.name.lower()).strip(".")
    return f"{local}@example.org"  # AGENTS.md rule 10: never real addresses


class InvestigatorFactory(RecordFactory):
    class Meta:
        model = Investigator

    class Params:
        handle = default_handle("Investigator")
        scope = factory.SubFactory(StudyFactory)

    id = minted_id("Investigator")
    name = filler("investigator_name", "name")
    institution = filler("investigator_institution", "institution")
    investigator_title = None
    email = factory.LazyAttribute(_example_email)


class PublicationFactory(RecordFactory):
    class Meta:
        model = Publication

    class Params:
        handle = default_handle("Publication")
        scope = factory.SubFactory(StudyFactory)

    id = minted_id("Publication")
    bibliographic_reference = filler("publication_reference", "bibliographic_reference")
    website = None
