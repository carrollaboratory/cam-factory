from cam_testdata.build import Build
from cam_testdata.text import ANIMALS


def test_filler_is_deterministic_and_themed_per_record() -> None:
    a, b = Build("test"), Build("test")
    h = a.handle("Study", "s1")
    title = a.fake(h, "study_title").study_title()
    description = a.fake(h, "study_description").study_description()
    assert title == b.fake(h, "study_title").study_title()
    # title and description name the same animal
    animal = next(
        name
        for name, (_, sound, _, _) in ANIMALS.items()
        if title.startswith(sound * 2)
    )
    assert f" {ANIMALS[animal][0]} " in description


def test_references_look_like_citations() -> None:
    ref = Build("test").fake("test/Publication/p1", "r").bibliographic_reference()
    assert ref.endswith(".") and ";" in ref and "(" in ref
