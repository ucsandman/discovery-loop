"""MIPLIB 2017 best-known objectives (official .solu file) and instance download."""

import glob
import gzip
import os
import re
import shutil
import urllib.request
from decimal import Decimal

SITE = "https://miplib.zib.de"
HERE = os.path.dirname(os.path.abspath(__file__))
INSTANCES = os.path.join(HERE, "instances")


def _version(path):
    return int(re.search(r"-v(\d+)\.solu$", path).group(1))


def _parse(path):
    """{instance: best known objective or None}. =opt= and =best= carry a value; =unkn= / =inf= do not."""
    rec = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 2 and p[0].startswith("="):
            rec[p[1]] = float(p[2]) if len(p) > 2 and p[0] in ("=opt=", "=best=") else None
    return rec


def reference(name):
    """Return official status, value, and decimal half-ULP from the source ``.solu`` text."""
    path = solu_path()
    if path is None:
        fetch()
        path = solu_path()
    for line in open(path):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == name:
            status = parts[0].strip("=")
            if len(parts) < 3 or parts[0] not in ("=opt=", "=best="):
                return {"status": status, "value": None, "uncertainty": None}
            printed = Decimal(parts[2])
            last_place = printed.adjusted() - len(printed.as_tuple().digits) + 1
            return {
                "status": status,
                "value": float(printed),
                "uncertainty": float(Decimal("0.5") * (Decimal(10) ** last_place)),
            }
    raise KeyError(f"{name} is absent from {path}")


def solu_path():
    files = sorted(glob.glob(os.path.join(HERE, "miplib2017-v*.solu")), key=_version)
    return files[-1] if files else None


def fetch():
    """Download the newest solu file listed on the MIPLIB download page (if newer than what we have)."""
    page = urllib.request.urlopen(SITE + "/download.html", timeout=30).read().decode()
    v = max(int(x) for x in re.findall(r"miplib2017-v(\d+)\.solu", page))
    path = os.path.join(HERE, f"miplib2017-v{v}.solu")
    if not os.path.exists(path):
        urllib.request.urlretrieve(f"{SITE}/downloads/miplib2017-v{v}.solu", path)
    return _parse(path)


def load():
    p = solu_path()
    return _parse(p) if p else fetch()


def instance_path(name):
    """Local .mps for an instance, downloading + unzipping from MIPLIB on first use."""
    mps = os.path.join(INSTANCES, name + ".mps")
    if not os.path.exists(mps):
        os.makedirs(INSTANCES, exist_ok=True)
        gz = mps + ".gz"
        urllib.request.urlretrieve(f"{SITE}/WebData/instances/{name}.mps.gz", gz)
        with gzip.open(gz, "rb") as f, open(mps, "wb") as g:
            shutil.copyfileobj(f, g)
    return mps


if __name__ == "__main__":
    rec = fetch()
    print(
        f"{os.path.basename(solu_path())}: {len(rec)} instances, {sum(v is None for v in rec.values())} without a known value"
    )
