"""Subject area (TODO 3.2): Subject, Demographics (+ Demographics_race via `race=[...]`)."""

import factory
from common_access_model.datamodel.common_access_model_sqla import Demographics, Subject

from cam_testdata.factories.base import RecordFactory, default_handle, linked, minted_id
from cam_testdata.factories.study import StudyFactory

PARTICIPANT = "CAMO:0000024"
NON_PARTICIPANT = "CAMO:0000025"
UNKNOWN = "snomedct:261665006"


class SubjectFactory(RecordFactory):
    class Meta:
        model = Subject

    class Params:
        handle = default_handle("Subject")
        scope = factory.SubFactory(StudyFactory)

    subject_id = minted_id("Subject")
    subject_type = PARTICIPANT
    organism_type = None


class DemographicsFactory(RecordFactory):
    """One per Participant subject (R3); shares the Subject's ID."""

    class Meta:
        model = Demographics

    class Params:
        handle = default_handle("Demographics")
        subject = factory.SubFactory(SubjectFactory)
        scope = factory.SelfAttribute("subject")

    subject_id = factory.SelfAttribute("subject.subject_id")
    sex = UNKNOWN
    ethnicity = UNKNOWN
    age_at_last_vital_status = None
    vital_status = None
    age_at_first_engagement = None

    cam_default_race = (UNKNOWN,)  # race is required and multivalued (R2)
    race = linked("race")
