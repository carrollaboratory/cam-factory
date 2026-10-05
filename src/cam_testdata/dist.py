"""Release archives (DESIGN §9, TODO 6.2a): dist/cam-testdata-<profile>-<model version>.tar.gz.

Reproducible: entries sorted, fixed mode/owner/mtime, gzip header mtime 0, so
the same output directory always gives the same archive bytes.
"""

import gzip
import io
import json
import tarfile
from pathlib import Path

from cam_testdata.settings import PROJECT_ROOT

DIST_DIR = PROJECT_ROOT / "dist"


class DistError(RuntimeError):
    pass


def archive_name(profile: str, out_dir: Path) -> str:
    manifest = out_dir / "manifest.json"
    if not manifest.exists():
        raise DistError(f"{manifest} not found; build the profile first")
    version = json.loads(manifest.read_text())["model"]["common_access_model"]
    return f"cam-testdata-{profile}-{version}"


def make_dist(
    profile: str, out_dir: Path | None = None, dist_dir: Path = DIST_DIR
) -> Path:
    out_dir = out_dir or PROJECT_ROOT / "output" / profile
    name = archive_name(profile, out_dir)
    dist_dir.mkdir(parents=True, exist_ok=True)
    target = dist_dir / f"{name}.tar.gz"

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path in sorted(p for p in out_dir.rglob("*") if p.is_file()):
            info = tarfile.TarInfo(f"{name}/{path.relative_to(out_dir).as_posix()}")
            data = path.read_bytes()
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    with (
        target.open("wb") as fh,
        gzip.GzipFile(filename="", mode="wb", fileobj=fh, mtime=0) as gz,
    ):
        gz.write(buf.getvalue())
    return target
