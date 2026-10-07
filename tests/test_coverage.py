from sqlalchemy.orm import Session

from cam_testdata.validate.coverage import FEATURES, missing_features, run_features
from dataset import build_dataset


def test_every_feature_shows_up_in_the_valid_dataset(session: Session) -> None:
    data = build_dataset()
    data.build.write(session)
    conn = session.connection()
    assert missing_features(conn) == []
    found = run_features(conn)
    assert found["child_study"] == [data["s2"].study_id]
    assert found["non_participant_without_demographics"] == [data["sibling"].subject_id]
    assert found["deceased_subject"] == [data["s2p1"].subject_id]
    assert found["derived_sample"] == sorted(
        [data["dna"].sample_id, data["mdna"].sample_id]
    )
    assert found["unavailable_aliquot"] == [data["aliquot_off"].aliquot_id]
    assert found["file_with_two_hashes"] == [data["cram"].file_id]
    assert found["file_subjects_only"] == [data["tsv"].file_id]
    assert found["assay_links_subject_sample_file"] == [data["assay"].assay_id]
    assert (
        found["person_record"]
        == found["person_across_studies"]
        == [data["person"].person_id]
    )


def test_an_empty_database_shows_no_features(session: Session) -> None:
    assert sorted(missing_features(session.connection())) == sorted(FEATURES)
