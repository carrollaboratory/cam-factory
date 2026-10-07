"""Config-driven scenarios for the scaled profiles (TODO 6.1).

Reads config/profiles/<profile>.yaml. Handles carry index numbers
(`small/Subject/s01-f0003-proband`), and every random decision uses a Random
seeded by the deciding record's handle (Build.rng), so raising a count adds
records without changing any existing ones.
"""

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from cam_testdata.build import Build
from cam_testdata.factories.base import ABSENT, PRESENT, link
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
    FamilyUnit,
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
    UNKNOWN,
    DemographicsFactory,
    PersonFactory,
    SubjectFactory,
)
from cam_testdata.settings import PROJECT_ROOT

PROFILES_DIR = PROJECT_ROOT / "config" / "profiles"
INCLUDE = "https://www.nih.gov/include-project"
DEAD, ALIVE = "snomedct:419099009", "snomedct:438949009"
FEMALE, MALE = "snomedct:248152002", "snomedct:248153007"
SIBLING = "KIN:007"  # isBiologicalSiblingOf
BLOOD_DRAW = "snomedct:82078001"
UNAVAILABLE, AVAILABLE = "snomedct:103329007", "snomedct:103328004"
ANTICOAGULANT, FREEZING, DNA_EXTRACTION = "OBI:0000819", "OBI:0000915", "OBI:0000257"
WGS_ASSAY = "OBI:0002117"
FORMATS = {
    "cram": "edam:format_3462",
    "vcf": "edam:format_3016",
    "tsv": "edam:format_3475",
}


def profile_path(profile: str) -> Path:
    return PROFILES_DIR / f"{profile}.yaml"


def load_profile(profile: str) -> dict[str, Any]:
    with profile_path(profile).open() as fh:
        data: dict[str, Any] = YAML(typ="safe").load(fh) or {}
    return data


def poisson(rng: random.Random, mean: float) -> int:
    """Knuth's method; fine for the small means used here."""
    limit, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


@dataclass
class StudyContext:
    key: str
    study: Any
    activities: dict[str, Any]
    baseline: Any
    follow_up: Any
    doi: Any
    publication: Any
    metadata: Any
    pi: Any = None
    contact: Any = None
    participants: list[Any] = field(default_factory=list)
    probands: list[tuple[str, Any, dict[str, Any]]] = field(default_factory=list)
    files: list[Any] = field(default_factory=list)


class ScaledScenario:
    def __init__(self, build: Build, config: dict[str, Any]) -> None:
        self.b = build
        self.c = config
        self.pools = build.pools.pools
        self.races = sorted(build.model.enum_values("EnumRace"))
        self.ethnicities = sorted(build.model.enum_values("EnumEthnicity"))

    # ----- helpers -------------------------------------------------------------

    def h(self, cls: str, key: str) -> str:
        return self.b.handle(cls, key)

    def rng(self, cls: str, key: str, label: str) -> random.Random:
        return self.b.rng(self.h(cls, key), label)

    def chance(self, cls: str, key: str, label: str, p: float) -> bool:
        return self.rng(cls, key, label).random() < p

    def pick(self, cls: str, key: str, pool: str, k: int = 1) -> list[str]:
        values = self.pools[pool]
        return sorted(self.rng(cls, key, pool).sample(values, min(k, len(values))))

    def kind_bundle(self, fmt: str) -> dict[str, Any]:
        return next(
            dict(k)
            for k in self.b.pools.bundles["file_kinds"]
            if k.get("File.format") == fmt
        )

    # ----- generation ------------------------------------------------------------

    def generate(self) -> None:
        studies: list[StudyContext] = []
        n = int(self.c["studies"])
        for i in range(1, n + 1):
            parent = (
                studies[0].study
                if studies and i > n - int(self.c.get("child_studies", 0))
                else None
            )
            studies.append(
                self.study(f"s{i:02d}", controlled=i % 2 == 1, parent=parent)
            )
        for ctx in studies:
            for f in range(1, int(self.c["families_per_study"]) + 1):
                self.family(ctx, f"{ctx.key}-f{f:04d}")
        self.farm_and_persons(
            studies
        )  # before files: returning participants count in their new study
        for ctx in studies:
            self.study_files(ctx)

    def study(self, key: str, controlled: bool, parent: Any) -> StudyContext:
        if controlled:
            ap = AccessPolicyFactory(
                handle=self.h("AccessPolicy", f"ap-{key}"),
                data_use_permission="DUO:0000007",
                disease_limitation="mesh:D012919",
                data_use_modifier="DUO:0000021",
            )
        else:
            ap = AccessPolicyFactory(
                handle=self.h("AccessPolicy", f"ap-{key}"),
                data_use_permission="DUO:0000042",
                data_use_modifier="DUO:0000045",
            )
        study = StudyFactory(
            handle=self.h("Study", key),
            access_policy=ap,
            parent=parent,
            program=[INCLUDE],
            funding_source=["Fictional Foundation for Test Data"],
        )
        pi = InvestigatorFactory(
            handle=self.h("Investigator", f"{key}-pi"),
            scope=study,
            investigator_title="Principal Investigator",
        )
        contact = InvestigatorFactory(
            handle=self.h("Investigator", f"{key}-contact"),
            scope=study,
            investigator_title="Study Coordinator",
        )
        pub = PublicationFactory(
            handle=self.h("Publication", f"{key}-pub1"), scope=study
        )
        link(study, "principal_investigator", [pi])
        link(study, "contact", [contact])
        link(study, "publication", [pub])
        doi = DOIFactory(handle=self.h("DOI", key), scope=study)
        attach_doi(study, doi)
        vbr = VirtualBiorepositoryFactory(
            handle=self.h("VirtualBiorepository", f"{key}-vbr"),
            scope=study,
            contact=[contact],
        )
        meta = StudyMetadataFactory(
            handle=self.h("StudyMetadata", key),
            study=study,
            vbr=vbr,
            participant_lifespan_stage=self.pick(
                "StudyMetadata", key, "StudyMetadata.participant_lifespan_stage", 2
            ),
            study_design=self.pick(
                "StudyMetadata", key, "StudyMetadata.study_design", 2
            ),
            clinical_data_source_type=self.pick(
                "StudyMetadata", key, "StudyMetadata.clinical_data_source_type", 2
            ),
            data_category=self.pick(
                "StudyMetadata", key, "StudyMetadata.data_category", 2
            ),
            research_domain=self.pick(
                "StudyMetadata", key, "StudyMetadata.research_domain", 1
            ),
        )
        activities = {
            name: ActivityDefinitionFactory(
                handle=self.h("ActivityDefinition", f"{key}-{name}"),
                scope=study,
                name=label,
            )
            for name, label in (
                ("clinical", "Clinical assessment"),
                ("blood", "Blood draw"),
                ("wgs", "Whole genome sequencing"),
            )
        }
        baseline = EncounterDefinitionFactory(
            handle=self.h("EncounterDefinition", f"{key}-baseline"),
            scope=study,
            name="Baseline visit",
            activity_definition_id=[activities["clinical"], activities["blood"]],
        )
        follow_up = EncounterDefinitionFactory(
            handle=self.h("EncounterDefinition", f"{key}-follow-up"),
            scope=study,
            name="Follow-up visit",
            activity_definition_id=[activities["clinical"]],
        )
        return StudyContext(
            key,
            study,
            activities,
            baseline,
            follow_up,
            doi,
            pub,
            meta,
            pi=pi,
            contact=contact,
        )

    def family(self, ctx: StudyContext, key: str) -> None:
        mix = self.c["family_mix"]
        kinds = sorted(mix)
        kind = self.rng("Family", key, "kind").choices(
            kinds, weights=[mix[k] for k in kinds]
        )[0]
        demographics = {
            role: self.demographics(f"{key}-{role}", draw_sex=role == "proband")
            for role in ("proband", "mother", "father")
        }
        unit: FamilyUnit = make_family(
            kind, ctx.study, key, member_demographics=demographics
        )
        ctx.probands.append((f"{key}-proband", unit.proband, demographics["proband"]))
        if self.chance(
            "Family", key, "sibling", float(self.c.get("non_participant_sibling", 0))
        ):
            sib = SubjectFactory(
                handle=self.h("Subject", f"{key}-sibling"),
                scope=ctx.study,
                subject_type=NON_PARTICIPANT,
            )
            FamilyMembershipFactory(
                handle=self.h("FamilyMembership", f"{key}-sibling"),
                family=unit.family,
                subject=sib,
                family_role=SIBLING,
            )
            FamilyRelationshipFactory(
                handle=self.h("FamilyRelationship", f"{key}-sibling-of-proband"),
                member=sib,
                subject=unit.proband,
                relation=SIBLING,
            )
        dna_samples: list[tuple[Any, Any]] = []
        for role, subject in unit.members.items():
            dna = self.participant(
                ctx,
                f"{key}-{role}",
                subject,
                unit.demographics[role],
                child=role == "proband",
            )
            ctx.participants.append(subject)
            if dna is not None:
                dna_samples.append((subject, dna))
        if len(dna_samples) >= 2 and self.chance(
            "Family", key, "vcf", float(self.c["files"]["family_vcf"])
        ):
            vcf = FileFactory(
                handle=self.h("File", f"{key}-joint-vcf"),
                scope=ctx.study,
                kind=self.kind_bundle(FORMATS["vcf"]),
                subject_id=[s for s, _ in dna_samples],
                sample_id=[d for _, d in dna_samples],
            )
            ctx.files.append(vcf)

    # ----- subjects ------------------------------------------------------------------

    def demographics(self, key: str, draw_sex: bool) -> dict[str, Any]:
        """Race and ethnicity for anyone; sex only for probands (parents' comes from their role)."""
        s = self.c["subject"]
        r = self.rng("Demographics", key, "demographics")
        out: dict[str, Any] = {}
        if draw_sex:
            out["sex"] = (
                UNKNOWN if r.random() < s["unknown_sex"] else r.choice([FEMALE, MALE])
            )
        k = 2 if r.random() < s["two_races"] else 1
        out["race"] = sorted(r.sample(self.races, k))
        out["ethnicity"] = (
            UNKNOWN
            if r.random() < s["unknown_ethnicity"]
            else r.choice(self.ethnicities)
        )
        return out

    def participant(
        self, ctx: StudyContext, key: str, subject: Any, demo: Any, child: bool
    ) -> Any:
        s = self.c["subject"]
        r = self.rng("Subject", key, "clinical")
        base_age = r.randint(365, 6570) if child else r.randint(7300, 18250)
        encounters = [
            EncounterFactory(
                handle=self.h("Encounter", f"{key}-e1"),
                subject=subject,
                definition=ctx.baseline,
                age_at_event=base_age,
            )
        ]
        age = base_age
        for e in range(2, 2 + poisson(r, s["encounters_mean"])):
            age += r.randint(90, 720)
            encounters.append(
                EncounterFactory(
                    handle=self.h("Encounter", f"{key}-e{e}"),
                    subject=subject,
                    definition=ctx.follow_up,
                    age_at_event=age,
                )
            )
        last_age = age
        demo.age_at_first_engagement = base_age
        if r.random() < s["deceased"]:
            demo.vital_status, demo.age_at_last_vital_status = (
                DEAD,
                last_age + r.randint(30, 900),
            )
        else:
            demo.vital_status, demo.age_at_last_vital_status = ALIVE, last_age

        for a in range(1, 1 + poisson(r, s["assertions_mean"])):
            self.assertion(f"{key}-a{a}", subject, encounters)
        return self.biospecimens(ctx, key, subject, encounters[0])

    def assertion(self, key: str, subject: Any, encounters: list[Any]) -> None:
        s = self.c["subject"]
        r = self.rng("SubjectAssertion", key, "assertion")
        encounter = (
            None if r.random() < s["without_encounter"] else r.choice(encounters)
        )
        age = encounter.age_at_event if encounter else encounters[0].age_at_event
        handle = self.h("SubjectAssertion", key)
        common = {
            "handle": handle,
            "subject": subject,
            "encounter": encounter,
            "asserter_type": r.choice(self.pools["SubjectAssertion.asserter_type"]),
            "assertion_source_type": r.choice(
                self.pools["SubjectAssertion.assertion_source_type"]
            ),
        }
        if r.random() < s["measurement"]:
            SubjectAssertionFactory(measurement=True, age_at_event=age, **common)
            return
        concept = r.choice(self.pools["SubjectAssertion.concept"])
        if r.random() < s["absent"]:
            SubjectAssertionFactory(
                concept=[concept],
                value_concept=[ABSENT],
                age_at_assertion=age,
                **common,
            )
            return
        onset = r.randint(0, age)
        resolution = r.randint(onset, age) if r.random() < s["resolved"] else None
        SubjectAssertionFactory(
            concept=[concept],
            value_concept=[PRESENT],
            age_at_event=onset,
            age_at_resolution=resolution,
            age_at_assertion=age,
            **common,
        )

    # ----- biospecimens and files ----------------------------------------------------------

    def biospecimens(
        self, ctx: StudyContext, key: str, subject: Any, baseline: Any
    ) -> Any:
        bio = self.c["biospecimen"]
        r = self.rng("Sample", key, "biospecimens")
        if r.random() >= bio["blood_draw"]:
            return None
        coll = BiospecimenCollectionFactory(
            handle=self.h("BiospecimenCollection", f"{key}-blood-draw"),
            encounter=baseline,
            method=BLOOD_DRAW,
        )
        blood = SampleFactory(
            handle=self.h("Sample", f"{key}-blood"),
            collection=coll,
            availability_status=AVAILABLE,
            storage_method=[ANTICOAGULANT] if r.random() < 0.5 else [],
            quantity_number=round(r.uniform(2, 10), 1),
            quantity_unit="ucum:ml",
        )
        self.aliquots(f"{key}-blood", blood, dna=False)
        if r.random() >= bio["dna"]:
            return None
        dna = SampleFactory(
            handle=self.h("Sample", f"{key}-dna"),
            parent=blood,
            processing=[DNA_EXTRACTION],
            storage_method=[FREEZING],
        )
        self.aliquots(f"{key}-dna", dna, dna=True)
        if r.random() < self.c["files"]["cram_per_dna"]:
            cram = FileFactory(
                handle=self.h("File", f"{key}-cram"),
                scope=ctx.study,
                kind=self.kind_bundle(FORMATS["cram"]),
                subject_id=[subject],
                sample_id=[dna],
                hash=["MS:1000568", "MS:1000569"]
                if r.random() < 0.3
                else ["MS:1000568"],
            )
            AssayFactory(
                handle=self.h("Assay", f"{key}-wgs"),
                scope=ctx.study,
                activity=ctx.activities["wgs"],
                assay_type=WGS_ASSAY,
                subject_id=[subject],
                sample_id=[dna],
                file_id=[cram],
            )
            ctx.files.append(cram)
        return dna

    def aliquots(self, key: str, sample: Any, dna: bool) -> None:
        bio = self.c["biospecimen"]
        r = self.rng("Aliquot", key, "aliquots")
        for n in range(
            1,
            2 + poisson(r, bio["aliquots_mean"] - 1 if bio["aliquots_mean"] > 1 else 0),
        ):
            extra: dict[str, Any] = (
                {
                    "quantity_number": 0.1,
                    "quantity_unit": "ucum:ml",
                    "concentration_number": round(r.uniform(10, 120), 1),
                    "concentration_unit": "ucum:ng/uL",
                }
                if dna
                else {
                    "quantity_number": round(r.uniform(0.5, 2), 1),
                    "quantity_unit": "ucum:ml",
                }
            )
            status = (
                UNAVAILABLE if r.random() < bio["unavailable_aliquot"] else AVAILABLE
            )
            AliquotFactory(
                handle=self.h("Aliquot", f"{key}-a{n}"),
                sample=sample,
                availability_status=status,
                **extra,
            )

    def farm_and_persons(self, studies: list[StudyContext]) -> None:
        """The umbrella Farm study and Person records (MODEL_ISSUES #25).

        A Person links Subjects known to be the same individual. Some s01 probands
        get a single-subject Person (a later study isn't ingested yet); others are
        returning participants, with a new Subject in a later study.
        """
        persons = self.c.get("persons")
        if not persons:
            return
        first, others = studies[0], studies[1:]
        ap = AccessPolicyFactory(
            handle=self.h("AccessPolicy", "ap-farm"), data_use_permission="DUO:0000042"
        )
        farm = StudyFactory(
            handle=self.h("Study", "farm"),
            access_policy=ap,
            program=[INCLUDE],
            study_title="Old MacDonald's Farm",
            study_code="FARM",
            study_description="Umbrella record for Person links across the farm's studies. Holds no subjects of its own.",
            principal_investigator=[first.pi],
            contact=[first.contact],
        )
        StudyMetadataFactory(
            handle=self.h("StudyMetadata", "farm"),
            study=farm,
            expected_number_of_participants=0,
            actual_number_of_participants=0,
            participant_lifespan_stage=self.pick(
                "StudyMetadata", "farm", "StudyMetadata.participant_lifespan_stage"
            ),
            study_design=self.pick(
                "StudyMetadata", "farm", "StudyMetadata.study_design"
            ),
            clinical_data_source_type=self.pick(
                "StudyMetadata", "farm", "StudyMetadata.clinical_data_source_type"
            ),
            data_category=self.pick(
                "StudyMetadata", "farm", "StudyMetadata.data_category"
            ),
            research_domain=self.pick(
                "StudyMetadata", "farm", "StudyMetadata.research_domain"
            ),
        )
        returning, single = (
            float(persons.get("returning", 0)),
            float(persons.get("single", 0)),
        )
        for key, subject, demo in first.probands:
            r = self.rng("Person", key, "person")
            roll = r.random()
            if others and roll < returning:
                other = r.choice(others)
                new_key = f"{other.key}-returning-{key}"
                again = SubjectFactory(
                    handle=self.h("Subject", new_key), scope=other.study
                )
                demographics = DemographicsFactory(
                    handle=self.h("Demographics", new_key), subject=again, **demo
                )
                self.participant(other, new_key, again, demographics, child=True)
                other.participants.append(again)
                PersonFactory(
                    handle=self.h("Person", key),
                    scope=farm,
                    subject_id=[subject, again],
                )
            elif roll < returning + single:
                PersonFactory(
                    handle=self.h("Person", key), scope=farm, subject_id=[subject]
                )

    def study_files(self, ctx: StudyContext) -> None:
        files = list(ctx.files)
        if self.c["files"].get("clinical_table") and ctx.participants:
            tsv = FileFactory(
                handle=self.h("File", f"{ctx.key}-clinical"),
                scope=ctx.study,
                kind=self.kind_bundle(FORMATS["tsv"]),
                subject_id=list(ctx.participants),
            )
            files.append(tsv)
        DatasetFactory(
            handle=self.h("Dataset", f"{ctx.key}-release-1"),
            scope=ctx.study,
            doi=ctx.doi,
            file_id=files,
            publication=[ctx.publication],
        )
        # R8: actual participants (expected: what the study planned, a bit more)
        meta = ctx.metadata
        meta.actual_number_of_participants = len(ctx.participants)
        meta.expected_number_of_participants = len(ctx.participants) + self.rng(
            "StudyMetadata", ctx.key, "expected"
        ).randint(0, 10)


def generate(build: Build, profile: str) -> dict[str, Any]:
    config = load_profile(profile)
    with build.active():
        ScaledScenario(build, config).generate()
    return config
