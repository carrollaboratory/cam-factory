import subprocess
import sys

import pytest

from cam_testdata.ids import IdCollisionError, IdError, IdRegistry
from cam_testdata.settings import get_settings


@pytest.fixture
def ids() -> IdRegistry:
    return IdRegistry("test-seed", get_settings().ids)


def test_global_id_format(ids: IdRegistry) -> None:
    id_ = ids.mint_global("pt", "tiny/Subject/trio1-proband")
    settings = get_settings().ids
    prefix, _, body = id_.partition("-")
    assert prefix == "pt"
    assert len(body) == settings.length
    assert set(body) <= set(settings.alphabet)
    assert ids.is_valid_global(id_, "pt")


def test_local_and_doi_formats(ids: IdRegistry) -> None:
    local = ids.mint_local("fmb", "tiny/FamilyMembership/trio1-proband")
    assert ids.is_valid_local(local) and local.startswith("fmb-")
    doi = ids.mint_doi("tiny/DOI/s1-doi")
    assert doi.startswith("10.5072/cam-testdata.")
    assert len(doi) == len("10.5072/cam-testdata.") + get_settings().ids.doi_length


def test_same_handle_same_id(ids: IdRegistry) -> None:
    first = ids.mint_global("pt", "tiny/Subject/a")
    assert ids.mint_global("pt", "tiny/Subject/a") == first
    assert (
        IdRegistry("test-seed", get_settings().ids).mint_global("pt", "tiny/Subject/a")
        == first
    )


def test_stable_across_processes(ids: IdRegistry) -> None:
    code = (
        "from cam_testdata.ids import IdRegistry; from cam_testdata.settings import get_settings;"
        "r = IdRegistry('test-seed', get_settings().ids);"
        "print(r.mint_global('pt', 'tiny/Subject/a'), r.mint_int('Investigator', 'tiny/Investigator/pi'))"
    )
    # A fresh interpreter with a different hash seed: no dict/set order or hash() leaks.
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": "12345"},
    ).stdout.split()
    assert out == [
        ids.mint_global("pt", "tiny/Subject/a"),
        str(ids.mint_int("Investigator", "tiny/Investigator/pi")),
    ]


def test_adding_handles_does_not_change_others(ids: IdRegistry) -> None:
    alone = IdRegistry("test-seed", get_settings().ids).mint_global(
        "bs", "tiny/Sample/x"
    )
    for i in range(50):
        ids.mint_global("bs", f"tiny/Sample/other-{i}")
    assert ids.mint_global("bs", "tiny/Sample/x") == alone


def test_seed_changes_ids() -> None:
    a = IdRegistry("seed-a", get_settings().ids).mint_global("pt", "h")
    b = IdRegistry("seed-b", get_settings().ids).mint_global("pt", "h")
    assert a != b


def test_minted_collision_raises(ids: IdRegistry) -> None:
    id_ = ids.mint_global("pt", "tiny/Subject/a")
    with pytest.raises(IdCollisionError):
        ids.register_explicit(id_, "tiny/Subject/b", ("pt",))


def test_pinned_then_minted_collision_raises(ids: IdRegistry) -> None:
    minted_elsewhere = IdRegistry("test-seed", get_settings().ids).mint_global(
        "pt", "tiny/Subject/a"
    )
    ids.register_explicit(minted_elsewhere, "tiny/Subject/pinned", ("pt",))
    with pytest.raises(IdCollisionError):
        ids.mint_global("pt", "tiny/Subject/a")


def test_pinned_id_validation(ids: IdRegistry) -> None:
    assert (
        ids.register_explicit("sd-7hwpqzc2yr", "tiny/Study/s1", ("sd",))
        == "sd-7hwpqzc2yr"
    )
    with pytest.raises(IdError, match="prefix"):
        ids.register_explicit("co-ajdm9fyxxz", "tiny/Study/s2", ("sd",))
    with pytest.raises(IdError, match="valid"):
        ids.register_explicit("sd-TOOSHORT", "tiny/Study/s3", ("sd",))
    with pytest.raises(IdError, match="valid"):
        ids.register_explicit("sd-7HWPQZC2YR", "tiny/Study/s4", ("sd",))  # uppercase


def test_any_of_prefixes(ids: IdRegistry) -> None:
    ids.register_explicit(
        "ob-0123456789", "tiny/SubjectAssertion/a", ("ob", "de", "ms")
    )
    with pytest.raises(IdError):
        ids.register_explicit(
            "pt-0123456789", "tiny/SubjectAssertion/b", ("ob", "de", "ms")
        )


def test_int_ids(ids: IdRegistry) -> None:
    n = ids.mint_int("Investigator", "tiny/Investigator/pi")
    assert 1 <= n <= 2**31 - 1
    assert ids.mint_int("Investigator", "tiny/Investigator/pi") == n
    # Same number in a different table is fine; in the same table it collides.
    ids.register_explicit_int("Publication", n, "tiny/Publication/p")
    with pytest.raises(IdCollisionError):
        ids.register_explicit_int("Investigator", n, "tiny/Investigator/other")


def test_bad_prefixes(ids: IdRegistry) -> None:
    with pytest.raises(IdError):
        ids.mint_global("PT", "h")
    with pytest.raises(IdError):
        ids.mint_local("fm", "h")
