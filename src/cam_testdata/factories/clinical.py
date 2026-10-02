"""Clinical area (TODO 3.4): EncounterDefinition, ActivityDefinition, Encounter,
SubjectAssertion. All assertions are `ob` Observations (Q8).

Traits on SubjectAssertionFactory:
  present=True      value_concept = [Known present]
  absent=True       value_concept = [Known absent]
  measurement=True  concept / value_number / value_unit from a measurements bundle
"""

from typing import Any

import factory
from common_access_model.datamodel.common_access_model_sqla import (
    ActivityDefinition,
    Encounter,
    EncounterDefinition,
    SubjectAssertion,
)

from cam_testdata.build import current_build
from cam_testdata.factories.base import (
    ABSENT,
    PRESENT,
    RecordFactory,
    default_handle,
    filler,
    linked,
    minted_id,
)
from cam_testdata.factories.study import StudyFactory
from cam_testdata.factories.subject import SubjectFactory


class ActivityDefinitionFactory(RecordFactory):
    class Meta:
        model = ActivityDefinition

    class Params:
        handle = default_handle("ActivityDefinition")
        scope = factory.SubFactory(StudyFactory)

    activity_definition_id = minted_id("ActivityDefinition")
    name = filler("activity_name", "activity_name")
    description = None


class EncounterDefinitionFactory(RecordFactory):
    class Meta:
        model = EncounterDefinition

    class Params:
        handle = default_handle("EncounterDefinition")
        scope = factory.SubFactory(StudyFactory)

    encounter_definition_id = minted_id("EncounterDefinition")
    name = filler("encounter_definition_name", "encounter_name")
    description = None

    activity_definition_id = linked("activity_definition_id")


class EncounterFactory(RecordFactory):
    class Meta:
        model = Encounter

    class Params:
        handle = default_handle("Encounter")
        subject = factory.SubFactory(SubjectFactory)
        scope = factory.SelfAttribute("subject")
        definition = None

    encounter_id = minted_id("Encounter")
    subject_id = factory.SelfAttribute("subject.subject_id")
    encounter_definition_id = factory.LazyAttribute(
        lambda o: o.definition.encounter_definition_id if o.definition else None
    )
    age_at_event = None


def _measurement(o: Any) -> dict[str, Any]:
    bundles = current_build().pools.bundles["measurements"]
    return dict(current_build().rng(o.handle, "measurement").choice(bundles))


def _measured_value(o: Any) -> float:
    m = o.measurement_bundle
    return round(
        current_build().rng(o.handle, "value_number").uniform(m["min"], m["max"]), 1
    )


class SubjectAssertionFactory(RecordFactory):
    class Meta:
        model = SubjectAssertion

    class Params:
        handle = default_handle("SubjectAssertion")
        subject = factory.SubFactory(SubjectFactory)
        scope = factory.SelfAttribute("subject")
        encounter = None
        id_prefix = None  # "ob" by default; the slot also allows "de" / "ms" (not simulated, Q8)
        measurement_bundle = factory.LazyAttribute(_measurement)

        present = factory.Trait(cam_default_value_concept=[PRESENT])
        absent = factory.Trait(cam_default_value_concept=[ABSENT])
        measurement = factory.Trait(
            cam_default_concept=factory.LazyAttribute(
                lambda o: [o.measurement_bundle["SubjectAssertion.concept"]]
            ),
            value_number=factory.LazyAttribute(_measured_value),
            value_unit=factory.LazyAttribute(
                lambda o: o.measurement_bundle["SubjectAssertion.value_unit"]
            ),
        )

    assertion_id = minted_id("SubjectAssertion")
    subject_id = factory.SelfAttribute("subject.subject_id")
    encounter_id = factory.LazyAttribute(
        lambda o: o.encounter.encounter_id if o.encounter else None
    )
    asserter_type = None
    assertion_source_type = None
    age_at_assertion = None
    age_at_event = None
    age_at_resolution = None
    concept_source = None
    value_number = None
    value_source = None
    value_unit = None
    value_unit_source = None

    cam_default_concept = None
    cam_default_value_concept = None
    concept = linked("concept")
    value_concept = linked("value_concept")
