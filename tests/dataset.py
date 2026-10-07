"""A small valid dataset for validation tests: passes R1-R12 and shows every coverage feature.

A cut-down cousin of the tiny scenario, built directly with factories.
"""

from dataclasses import dataclass, field
from typing import Any

from cam_testdata.build import Build
from cam_testdata.factories.base import link
from cam_testdata.factories.biospecimen import (
    AliquotFactory,
    BiospecimenCollectionFactory,
    SampleFactory,
)
from cam_testdata.factories.clinical import (
    ActivityDefinitionFactory,
    EncounterDefinitionFactory,
    EncounterFactory,
    SubjectAssertionFactory,
)
from cam_testdata.factories.family import (
    FamilyMembershipFactory,
    FamilyRelationshipFactory,
    make_family,
)
from cam_testdata.factories.files import AssayFactory, DatasetFactory, FileFactory
from cam_testdata.factories.study import (
    AccessPolicyFactory,
    DOIFactory,
    InvestigatorFactory,
    PublicationFactory,
    StudyFactory,
    StudyMetadataFactory,
    VirtualBiorepositoryFactory,
    attach_doi,
)
from cam_testdata.factories.subject import (
    NON_PARTICIPANT,
    DemographicsFactory,
    PersonFactory,
    SubjectFactory,
)

INCLUDE = "https://www.nih.gov/include-project"


@dataclass
class Dataset:
    build: Build
    objects: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.objects[key]


def _metadata(study: Any, handle: str, participants: int, **extra: Any) -> Any:
    return StudyMetadataFactory(
        handle=handle,
        study=study,
        expected_number_of_participants=participants,
        actual_number_of_participants=participants,
        participant_lifespan_stage=["NCIT:C89345"],
        study_design=["mesh:D015331"],
        clinical_data_source_type=["CAMO:0000014"],
        data_category=["edam:topic_3673"],
        research_domain=["mesh:D006330"],
        **extra,
    )


def build_dataset(profile: str = "test") -> Dataset:
    b = Build(profile)
    h = b.handle
    d = Dataset(b)
    o = d.objects
    with b.active():
        o["ap"] = ap = AccessPolicyFactory(
            handle=h("AccessPolicy", "controlled"), data_use_permission="DUO:0000007"
        )
        o["ap2"] = ap2 = AccessPolicyFactory(handle=h("AccessPolicy", "open"))
        o["s1"] = s1 = StudyFactory(
            handle=h("Study", "s1"), access_policy=ap, program=[INCLUDE]
        )
        pi = InvestigatorFactory(handle=h("Investigator", "pi"), scope=s1)
        s1_contact = InvestigatorFactory(handle=h("Investigator", "contact"), scope=s1)
        pub = PublicationFactory(handle=h("Publication", "pub"), scope=s1)
        # set the many-valued links after the investigators exist
        link(s1, "principal_investigator", [pi])
        link(s1, "contact", [s1_contact])
        link(s1, "publication", [pub])
        o["doi"] = doi = DOIFactory(handle=h("DOI", "s1"), scope=s1)
        attach_doi(s1, doi)
        vbr = VirtualBiorepositoryFactory(
            handle=h("VirtualBiorepository", "vbr"), scope=s1, contact=[s1_contact]
        )

        # trio + a non-participant sibling
        unit = make_family("trio", s1, "trio1", race=["CDCREC:2054-5", "CDCREC:2106-3"])
        o.update(
            proband=unit.proband,
            mother=unit.mother,
            father=unit.father,
            family=unit.family,
        )
        o["sibling"] = sib = SubjectFactory(
            handle=h("Subject", "trio1-sibling"), scope=s1, subject_type=NON_PARTICIPANT
        )
        FamilyMembershipFactory(
            handle=h("FamilyMembership", "trio1-sibling"),
            family=unit.family,
            subject=sib,
            family_role="KIN:007",
        )
        FamilyRelationshipFactory(
            handle=h("FamilyRelationship", "sib"),
            member=sib,
            subject=unit.proband,
            relation="KIN:007",
        )
        _metadata(s1, h("StudyMetadata", "s1"), 3, vbr=vbr)

        # child study with one deceased participant of unknown sex
        o["s2"] = s2 = StudyFactory(
            handle=h("Study", "s2"), access_policy=ap2, parent=s1, program=[INCLUDE]
        )
        # Investigators are Records scoped to one study (R1), so S2 gets its own row
        s2_pi = InvestigatorFactory(handle=h("Investigator", "s2-pi"), scope=s2)
        link(s2, "principal_investigator", [s2_pi])
        link(s2, "contact", [s2_pi])
        o["s2p1"] = s2p1 = SubjectFactory(handle=h("Subject", "s2-p1"), scope=s2)
        DemographicsFactory(
            handle=h("Demographics", "s2-p1"),
            subject=s2p1,
            vital_status="snomedct:419099009",
            age_at_last_vital_status=25550,
        )
        _metadata(s2, h("StudyMetadata", "s2"), 1)

        # the umbrella Farm and a Person spanning S1 and S2
        farm = StudyFactory(
            handle=h("Study", "farm"), access_policy=ap2, program=[INCLUDE]
        )
        link(farm, "principal_investigator", [pi])
        link(farm, "contact", [s1_contact])
        _metadata(farm, h("StudyMetadata", "farm"), 0)
        o["person"] = PersonFactory(
            handle=h("Person", "p1"), scope=farm, subject_id=[unit.proband, s2p1]
        )

        # clinical
        wgs = ActivityDefinitionFactory(handle=h("ActivityDefinition", "wgs"), scope=s1)
        base = EncounterDefinitionFactory(
            handle=h("EncounterDefinition", "baseline"),
            scope=s1,
            activity_definition_id=[wgs],
        )
        o["enc"] = enc = EncounterFactory(
            handle=h("Encounter", "p-base"),
            subject=unit.proband,
            definition=base,
            age_at_event=1826,
        )
        menc = EncounterFactory(
            handle=h("Encounter", "m-base"),
            subject=unit.mother,
            definition=base,
            age_at_event=12410,
        )
        o["s2enc"] = EncounterFactory(
            handle=h("Encounter", "s2-visit"), subject=s2p1, age_at_event=25000
        )
        o["present"] = SubjectAssertionFactory(
            handle=h("SubjectAssertion", "ds"),
            subject=unit.proband,
            encounter=enc,
            present=True,
            concept=["MONDO:0008608"],
            age_at_event=0,
        )
        SubjectAssertionFactory(
            handle=h("SubjectAssertion", "hypo"),
            subject=unit.proband,
            encounter=enc,
            absent=True,
            concept=["HP:0000821"],
        )
        SubjectAssertionFactory(
            handle=h("SubjectAssertion", "height"),
            subject=unit.proband,
            encounter=enc,
            concept=["loinc:8302-2"],
            value_number=109.2,
            value_unit="ucum:cm",
        )
        SubjectAssertionFactory(
            handle=h("SubjectAssertion", "m-hypo"),
            subject=unit.mother,
            present=True,
            concept=["HP:0000821"],
            age_at_event=9125,
        )  # no encounter
        SubjectAssertionFactory(
            handle=h("SubjectAssertion", "murmur"),
            subject=s2p1,
            encounter=o["s2enc"],
            present=True,
            concept=["HP:0030148"],
            age_at_event=18250,
            age_at_resolution=20075,
        )

        # biospecimens
        o["coll"] = coll = BiospecimenCollectionFactory(
            handle=h("BiospecimenCollection", "p-draw"),
            encounter=enc,
            method="snomedct:82078001",
        )
        mcoll = BiospecimenCollectionFactory(
            handle=h("BiospecimenCollection", "m-draw"), encounter=menc
        )
        o["blood"] = blood = SampleFactory(
            handle=h("Sample", "p-blood"),
            collection=coll,
            storage_method=["OBI:0000819"],
        )
        o["dna"] = dna = SampleFactory(
            handle=h("Sample", "p-dna"), parent=blood, processing=["OBI:0000257"]
        )
        o["mdna"] = mdna = SampleFactory(
            handle=h("Sample", "m-dna"),
            parent=SampleFactory(handle=h("Sample", "m-blood"), collection=mcoll),
        )
        AliquotFactory(
            handle=h("Aliquot", "p-dna-1"),
            sample=dna,
            concentration_number=52.5,
            concentration_unit="ucum:ng/uL",
        )
        o["aliquot_off"] = AliquotFactory(
            handle=h("Aliquot", "p-blood-1"),
            sample=blood,
            availability_status="snomedct:103329007",
        )

        # files, assay, dataset
        kinds = b.pools.bundles["file_kinds"]
        o["cram"] = cram = FileFactory(
            handle=h("File", "p-cram"),
            scope=s1,
            kind=dict(kinds[0]),
            subject_id=[unit.proband],
            sample_id=[dna],
            hash=["MS:1000568", "MS:1000569"],
        )
        o["vcf"] = vcf = FileFactory(
            handle=h("File", "joint-vcf"),
            scope=s1,
            kind=dict(kinds[1]),
            subject_id=[unit.proband, unit.mother],
            sample_id=[dna, mdna],
        )
        o["tsv"] = tsv = FileFactory(
            handle=h("File", "clinical"),
            scope=s1,
            kind=dict(kinds[3]),
            subject_id=[unit.proband, unit.mother, unit.father],
        )
        o["assay"] = AssayFactory(
            handle=h("Assay", "p-wgs"),
            scope=s1,
            activity=wgs,
            subject_id=[unit.proband],
            sample_id=[dna],
            file_id=[cram],
        )
        DatasetFactory(
            handle=h("Dataset", "release1"),
            scope=s1,
            doi=doi,
            file_id=[cram, vcf, tsv],
            publication=[pub],
        )
    return d
