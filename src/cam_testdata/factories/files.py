"""Files area (TODO 3.6): HashDigest, File, Assay, Dataset.

Hash values are real digests of a deterministic string (seed + file handle),
so they look right and never change between builds.
"""

import hashlib
from typing import Any

import factory
from common_access_model.datamodel.common_access_model_sqla import (
    Assay,
    Dataset,
    File,
    HashDigest,
)

from cam_testdata.build import current_build
from cam_testdata.factories.base import (
    BaseFactory,
    RecordFactory,
    default_handle,
    filler,
    link,
    linked,
    minted_id,
)
from cam_testdata.factories.study import StudyFactory

MD5 = "MS:1000568"
# EnumFileHashType -> hashlib algorithm. ETag (CAMO:0000022) is an S3-style MD5.
HASH_ALGORITHMS = {
    "MS:1000568": "md5",
    "MS:1000569": "sha1",
    "MS:1003151": "sha256",
    "CAMO:0000022": "md5",
}


def _digest(o: Any) -> str:
    algorithm = HASH_ALGORITHMS[o.hash_type]
    return hashlib.new(
        algorithm, f"{current_build().seed}|{o.source}".encode()
    ).hexdigest()


class HashDigestFactory(BaseFactory):
    class Meta:
        model = HashDigest

    class Params:
        handle = default_handle("HashDigest")
        pinned_id = None
        source = factory.SelfAttribute("handle")  # the string that gets hashed

    id = minted_id("HashDigest")
    hash_type = MD5
    hash_value = factory.LazyAttribute(_digest)


def _file_kind(o: Any) -> dict[str, Any]:
    kinds = current_build().pools.bundles["file_kinds"]
    return dict(current_build().rng(o.handle, "file_kind").choice(kinds))


def _hashes(obj: Any, create: bool, extracted: Any, **_: Any) -> None:
    """`hash=[...]`: hash types (or {hash_type: ...} dicts) -> HashDigest rows + File_hash links."""
    if not create:
        return
    values = extracted if extracted is not None else obj._cam_default_hash
    digests = []
    for value in values or []:
        hash_type = value["hash_type"] if isinstance(value, dict) else value
        digests.append(
            HashDigestFactory(
                handle=f"{obj._cam_handle}#{hash_type}",
                source=obj._cam_handle,
                hash_type=hash_type,
            )
        )
    if digests:
        link(obj, "hash", digests)


class FileFactory(RecordFactory):
    class Meta:
        model = File

    class Params:
        handle = default_handle("File")
        scope = factory.SubFactory(StudyFactory)
        kind = factory.LazyAttribute(_file_kind)  # a file_kinds bundle

    file_id = minted_id("File")
    filename = factory.LazyAttribute(
        lambda o: o.handle.rsplit("/", 1)[-1] + o.kind["File.file_extension"]
    )
    file_extension = factory.LazyAttribute(lambda o: o.kind["File.file_extension"])
    data_category = factory.LazyAttribute(lambda o: o.kind.get("File.data_category"))
    data_type = factory.LazyAttribute(lambda o: o.kind.get("File.data_type"))
    format = factory.LazyAttribute(lambda o: o.kind.get("File.format"))
    # File.size is a 32-bit INTEGER in the DDL (MODEL_ISSUES #23), so stay under 2**31.
    size = factory.LazyAttribute(
        lambda o: current_build().rng(o.handle, "size").randint(10**3, 2**31 - 1)
    )
    internal_uri = None
    release_uri = None
    drs_uri = None
    storage_class = None
    availability = None

    subject_id = linked("subject_id")
    sample_id = linked("sample_id")
    cam_default_hash = (MD5,)  # every file has an MD5
    hash = factory.PostGeneration(_hashes)


class AssayFactory(RecordFactory):
    class Meta:
        model = Assay

    class Params:
        handle = default_handle("Assay")
        scope = factory.SubFactory(StudyFactory)
        activity = None

    assay_id = minted_id("Assay")
    assay_type = "OBI:0002117"  # whole genome sequencing assay
    assay_source = None
    activity_definition_id = factory.LazyAttribute(
        lambda o: o.activity.activity_definition_id if o.activity else None
    )

    subject_id = linked("subject_id")
    sample_id = linked("sample_id")
    file_id = linked("file_id")


class DatasetFactory(RecordFactory):
    class Meta:
        model = Dataset

    class Params:
        handle = default_handle("Dataset")
        scope = factory.SubFactory(StudyFactory)
        doi = None

    dataset_id = minted_id("Dataset")
    name = filler("dataset_name", "dataset_name")
    description = None
    do_id = factory.LazyAttribute(lambda o: o.doi.do_id if o.doi else None)
    data_collection_start = None
    data_collection_end = None

    file_id = linked("file_id")
    publication = linked("publication")
