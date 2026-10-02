"""Biospecimen area (TODO 3.5): BiospecimenCollection, Sample, Aliquot.

- A collection always has an encounter (R4); age_at_collection is the
  encounter's age converted from days to years (R7).
- A primary Sample comes from a collection; a derived Sample (`parent=`) shares
  its parent's collection and subject (R4). Sample.subject_id must match the
  collection's encounter subject (R6).
"""

from typing import Any

import factory
from common_access_model.datamodel.common_access_model_sqla import (
    Aliquot,
    BiospecimenCollection,
    Sample,
)

from cam_testdata.factories.base import RecordFactory, default_handle, linked, minted_id
from cam_testdata.factories.clinical import EncounterFactory

BLOOD = "UBERON:0000178"
DNA_EXTRACT = "OBI:0001051"
DAYS_PER_YEAR = 365.25


def days_to_years(days: int | None) -> float | None:
    """The single conversion used for age_at_collection (R7)."""
    return None if days is None else round(days / DAYS_PER_YEAR, 2)


class BiospecimenCollectionFactory(RecordFactory):
    class Meta:
        model = BiospecimenCollection

    class Params:
        handle = default_handle("BiospecimenCollection")
        encounter = factory.SubFactory(EncounterFactory)
        scope = factory.SelfAttribute("encounter")

    biospecimen_collection_id = minted_id("BiospecimenCollection")
    age_at_collection = factory.LazyAttribute(
        lambda o: days_to_years(o.encounter.age_at_event)
    )
    method = None
    site = None
    spatial_qualifier = None
    laterality = None
    encounter_id = factory.SelfAttribute("encounter.encounter_id")
    # remembered on the object so Samples can take their subject from the collection
    cam_subject_id = factory.SelfAttribute("encounter.subject_id")


def _collection_id(o: Any) -> Any:
    if o.parent is not None:
        return o.parent.biospecimen_collection_id
    return o.collection.biospecimen_collection_id if o.collection is not None else None


def _subject_id(o: Any) -> Any:
    if o.parent is not None:
        return o.parent.subject_id
    return (
        getattr(o.collection, "_cam_subject_id", None)
        if o.collection is not None
        else None
    )


class SampleFactory(RecordFactory):
    class Meta:
        model = Sample

    class Params:
        handle = default_handle("Sample")
        parent = None
        collection = factory.Maybe(
            "parent",
            yes_declaration=None,
            no_declaration=factory.SubFactory(BiospecimenCollectionFactory),
        )
        scope = factory.LazyAttribute(
            lambda o: o.parent if o.parent is not None else o.collection
        )

    sample_id = minted_id("Sample")
    biospecimen_collection_id = factory.LazyAttribute(_collection_id)
    parent_sample_id = factory.LazyAttribute(
        lambda o: o.parent.sample_id if o.parent else None
    )
    sample_type = factory.LazyAttribute(lambda o: DNA_EXTRACT if o.parent else BLOOD)
    subject_id = factory.LazyAttribute(_subject_id)
    availability_status = None
    quantity_number = None
    quantity_unit = None

    processing = linked("processing")
    storage_method = linked("storage_method")


class AliquotFactory(RecordFactory):
    class Meta:
        model = Aliquot

    class Params:
        handle = default_handle("Aliquot")
        sample = factory.SubFactory(SampleFactory)
        scope = factory.SelfAttribute("sample")

    aliquot_id = minted_id("Aliquot")
    sample_id = factory.SelfAttribute("sample.sample_id")
    availability_status = None
    quantity_number = None
    quantity_unit = None
    concentration_number = None
    concentration_unit = None
