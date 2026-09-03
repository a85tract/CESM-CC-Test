"""Input adapters shared by the two comparators. Not a command-line tool.

`compare_runpair.py` and `compare_stats.py` both have to turn a run directory
into named variables. This module is that layer, and nothing else lives here:
no acceptance logic, no exit codes, no manifest shapes.

Two backends, and which one ran is recorded
-------------------------------------------
The numeric digest of an output file is only comparable against a digest taken
the same way, which is why the schema carries `dump_tool` beside `dump_format`
rather than assuming them. So this module does not silently substitute one
dumper for another — it picks a backend for the whole comparison, names it, and
the comparator echoes that name into its JSON:

  ``ncks``   the original path, ported from PyCAM5's ``compare_cesm_runpair.py``:
             ``ncks -C -H -s FORMAT -v <all numeric vars>`` for one digest per
             file, ``ncdump -v`` per character variable. Needs NCO on PATH and
             only reads ``.nc``. Produces digests comparable with every manifest
             filed to date, and gives no access to the values themselves.

  ``numpy``  in-process. Reads ``.npy``, ``.npz``, whitespace/comma text tables,
             and — only if ``netCDF4`` or ``xarray`` is importable — ``.nc``.
             Dumps every numeric variable through the same format string with a
             ``# name dtype shape`` header per variable, so a changed shape
             changes the digest. Because the header makes the byte stream differ
             from NCO's, this backend reports ``dump_tool: numpy``; a digest from
             one backend must never be compared with a digest from the other.
             In exchange it holds the arrays, so per-field max abs / max rel are
             available.

It also loads the JSON/YAML documents the tools read (benchmark files and bare
acceptance blocks), for the same reason: one place that fails loudly when the
document cannot be read.

Failure is loud
---------------
Every unreadable input raises `DataError`, which the comparators turn into
status ERROR and exit 2. A file this module cannot read is never reported as a
file that compared equal. In particular, ``.nc`` with neither NCO nor a NetCDF
Python library present raises with a message naming all three ways out.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence

DUMP_FORMAT = "%+.17g"
INCLUDE_PREFIXES = ("h0.", "r.", "rh0.", "rs.")

NETCDF_SUFFIXES = (".nc",)
ARRAY_SUFFIXES = (".npy", ".npz")
TABLE_SUFFIXES = (".txt", ".csv", ".tab", ".dat")
SUPPORTED_SUFFIXES = NETCDF_SUFFIXES + ARRAY_SUFFIXES + TABLE_SUFFIXES

# ncks -m type names, as the PyCAM5 script classified them.
NCKS_NUMERIC_TYPES = {
    "double", "float", "int", "short", "byte", "ubyte", "ushort", "uint",
    "int64", "uint64",
}
NCKS_CHAR_TYPES = {"char", "string"}

# numpy dtype kinds. Anything outside these two sets is refused rather than
# guessed at.
NUMPY_NUMERIC_KINDS = "biuf"
NUMPY_CHAR_KINDS = "SUO"


class DataError(Exception):
    """An input could not be read. Always becomes ERROR / exit 2, never a PASS."""


def _numpy():
    try:
        import numpy
    except ImportError as exc:  # pragma: no cover - exercised only without numpy
        raise DataError(
            "numpy is required for the in-process backend; install numpy, or "
            "install NCO (ncks/ncdump) to use the ncks backend on .nc input"
        ) from exc
    return numpy


# --------------------------------------------------------------------------
# run directory scanning


def cam_key(path: Path) -> Optional[str]:
    """Output identity with the case name stripped: the part after '.cam.'.

    Returns None for a name that carries no '.cam.' marker, which is how a
    non-output file in a run directory is skipped.
    """
    marker = ".cam."
    idx = path.name.find(marker)
    if idx < 0:
        return None
    return path.name[idx + len(marker):]


def collect_run_files(
    run_dir: Path, prefixes: Sequence[str] = INCLUDE_PREFIXES
) -> Dict[str, Path]:
    """Map key -> path for the outputs in scope, exactly as the PyCAM5 script did.

    In scope: `*.cam.*` whose stripped key starts with one of `prefixes` and
    whose suffix this module can read. The suffix set is wider than `.nc` so the
    tools are exercisable without NetCDF; the key rule is unchanged.
    """
    if not run_dir.is_dir():
        raise DataError("not a directory: %s" % run_dir)
    out: Dict[str, Path] = {}
    for path in sorted(run_dir.glob("*.cam.*")):
        if path.suffix not in SUPPORTED_SUFFIXES or not path.is_file():
            continue
        key = cam_key(path)
        if key is None or not key.startswith(tuple(prefixes)):
            continue
        if key in out:
            raise DataError(
                "two files in %s share the key %r: %s and %s"
                % (run_dir, key, out[key].name, path.name)
            )
        out[key] = path
    return out


# --------------------------------------------------------------------------
# backends


def have_nco() -> bool:
    return bool(shutil.which("ncks")) and bool(shutil.which("ncdump"))


def choose_backend(paths: Sequence[Path], requested: str = "auto") -> str:
    """Pick one backend for the whole comparison and say which it is.

    One backend for every file, never a mix: digests taken with different
    dumpers are not comparable, so a comparison that used both would report a
    difference it cannot attribute.
    """
    suffixes = {p.suffix for p in paths}
    if requested == "ncks":
        if suffixes - set(NETCDF_SUFFIXES):
            raise DataError(
                "the ncks backend reads .nc only; in scope: %s"
                % ", ".join(sorted(suffixes))
            )
        if not have_nco():
            raise DataError("--dump-tool ncks was requested but ncks/ncdump are not on PATH")
        return "ncks"
    if requested == "numpy":
        return "numpy"
    if requested != "auto":
        raise DataError("unknown backend: %s" % requested)
    if suffixes and not (suffixes - set(NETCDF_SUFFIXES)) and have_nco():
        return "ncks"
    return "numpy"


class Reader:
    """One opened output file, as a set of named numeric and character variables."""

    backend = "?"

    def numeric_names(self) -> List[str]:
        raise NotImplementedError

    def char_names(self) -> List[str]:
        raise NotImplementedError

    def numeric_digest(self, names: Sequence[str]) -> Optional[str]:
        """One md5 over a fixed-format dump of `names`. None when `names` is empty."""
        raise NotImplementedError

    def char_digest(self, name: str) -> str:
        raise NotImplementedError

    def numeric_array(self, name: str):
        """The values, or None when the backend has digests only (ncks)."""
        return None


class NcksReader(Reader):
    backend = "ncks"

    def __init__(self, path: Path, dump_format: str = DUMP_FORMAT) -> None:
        self.path = path
        self.dump_format = dump_format
        self._numeric: List[str] = []
        self._char: List[str] = []
        self._scan()

    def _scan(self) -> None:
        text = self._run_text(["ncks", "-m", str(self.path)])
        for line in text.splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            dtype = parts[0]
            name = parts[1].split("(", 1)[0]
            if dtype in NCKS_NUMERIC_TYPES:
                self._numeric.append(name)
            elif dtype in NCKS_CHAR_TYPES:
                self._char.append(name)

    def _run_text(self, cmd: List[str]) -> str:
        try:
            return subprocess.check_output(cmd, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise DataError("%s failed on %s: %s" % (cmd[0], self.path.name, exc)) from exc

    def _run_bytes(self, cmd: List[str]) -> bytes:
        try:
            return subprocess.check_output(cmd)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise DataError("%s failed on %s: %s" % (cmd[0], self.path.name, exc)) from exc

    def numeric_names(self) -> List[str]:
        return list(self._numeric)

    def char_names(self) -> List[str]:
        return list(self._char)

    def numeric_digest(self, names: Sequence[str]) -> Optional[str]:
        if not names:
            return None
        payload = self._run_bytes(
            ["ncks", "-C", "-H", "-s", self.dump_format + "\n",
             "-v", ",".join(names), str(self.path)]
        )
        return hashlib.md5(payload).hexdigest()

    def char_digest(self, name: str) -> str:
        text = self._run_text(["ncdump", "-v", name, str(self.path)])
        marker = "data:\n"
        idx = text.find(marker)
        if idx < 0:
            raise DataError(
                "no data section for %s in %s" % (name, self.path.name)
            )
        return hashlib.md5(text[idx + len(marker):].encode()).hexdigest()


class ArrayReader(Reader):
    backend = "numpy"

    def __init__(self, path: Path, dump_format: str = DUMP_FORMAT) -> None:
        self.path = path
        self.dump_format = dump_format
        self.variables = read_variables(path)
        np = _numpy()
        self._numeric: List[str] = []
        self._char: List[str] = []
        for name in sorted(self.variables):
            kind = np.asarray(self.variables[name]).dtype.kind
            if kind in NUMPY_NUMERIC_KINDS:
                self._numeric.append(name)
            elif kind in NUMPY_CHAR_KINDS:
                self._char.append(name)
            else:
                raise DataError(
                    "%s: variable %r has dtype kind %r, which this backend will "
                    "not classify as numeric or character" % (path.name, name, kind)
                )

    def numeric_names(self) -> List[str]:
        return list(self._numeric)

    def char_names(self) -> List[str]:
        return list(self._char)

    def numeric_digest(self, names: Sequence[str]) -> Optional[str]:
        if not names:
            return None
        return hashlib.md5(self.numeric_dump(names)).hexdigest()

    def numeric_dump(self, names: Sequence[str]) -> bytes:
        np = _numpy()
        chunks: List[bytes] = []
        for name in names:
            arr = np.asarray(self.variables[name])
            chunks.append(
                ("# %s %s %s\n" % (name, arr.dtype.str, tuple(arr.shape))).encode()
            )
            for value in arr.reshape(-1).tolist():
                chunks.append((self.dump_format % value).encode() + b"\n")
        return b"".join(chunks)

    def char_digest(self, name: str) -> str:
        np = _numpy()
        arr = np.asarray(self.variables[name])
        payload = ("# %s %s\n" % (name, tuple(arr.shape))).encode()
        payload += b"\n".join(str(v).encode() for v in arr.reshape(-1).tolist())
        return hashlib.md5(payload).hexdigest()

    def numeric_array(self, name: str):
        return _numpy().asarray(self.variables[name])


def open_reader(path: Path, backend: str, dump_format: str = DUMP_FORMAT) -> Reader:
    if backend == "ncks":
        return NcksReader(path, dump_format)
    if backend == "numpy":
        return ArrayReader(path, dump_format)
    raise DataError("unknown backend: %s" % backend)


# --------------------------------------------------------------------------
# in-process readers


def read_variables(path: Path) -> Dict[str, object]:
    """Read one data file into {name: array}. Raises DataError, never returns {}."""
    if not path.is_file():
        raise DataError("no such file: %s" % path)
    suffix = path.suffix
    if suffix == ".npy":
        variables = {path.stem: _numpy().load(str(path), allow_pickle=False)}
    elif suffix == ".npz":
        with _numpy().load(str(path), allow_pickle=False) as handle:
            variables = {name: handle[name] for name in handle.files}
    elif suffix in TABLE_SUFFIXES:
        variables = _read_table(path)
    elif suffix in NETCDF_SUFFIXES:
        variables = _read_netcdf(path)
    else:
        raise DataError(
            "unsupported input %s; this tool reads %s"
            % (path.name, ", ".join(SUPPORTED_SUFFIXES))
        )
    if not variables:
        raise DataError("%s holds no variables" % path.name)
    return variables


def _read_table(path: Path) -> Dict[str, object]:
    """A text table: one header row of column names, then rows of values.

    Columns whose every value parses as a float become numeric variables; the
    rest become character variables. Blank lines and lines starting with '#'
    are ignored. Comma-separated if the header holds a comma, whitespace
    otherwise.
    """
    np = _numpy()
    rows: List[List[str]] = []
    header: Optional[List[str]] = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fields = [f.strip() for f in (line.split(",") if "," in line else line.split())]
        if header is None:
            header = fields
        else:
            if len(fields) != len(header):
                raise DataError(
                    "%s: row has %d fields, header has %d"
                    % (path.name, len(fields), len(header))
                )
            rows.append(fields)
    if not header:
        raise DataError("%s: no header row" % path.name)
    variables: Dict[str, object] = {}
    for index, name in enumerate(header):
        column = [row[index] for row in rows]
        try:
            variables[name] = np.array([float(v) for v in column], dtype=float)
        except ValueError:
            variables[name] = np.array(column, dtype=object)
    return variables


def _read_netcdf(path: Path) -> Dict[str, object]:
    np = _numpy()
    try:
        import netCDF4
    except ImportError:
        netCDF4 = None
    if netCDF4 is not None:
        dataset = netCDF4.Dataset(str(path))
        try:
            dataset.set_auto_mask(False)
            return {name: np.asarray(var[...]) for name, var in dataset.variables.items()}
        finally:
            dataset.close()
    try:
        import xarray
    except ImportError:
        raise DataError(
            "cannot read %s: no NetCDF reader is available. Either install NCO "
            "(ncks and ncdump) for the ncks backend, or install netCDF4 or "
            "xarray for the in-process backend. .npy / .npz / text-table inputs "
            "need neither." % path.name
        ) from None
    with xarray.open_dataset(str(path)) as dataset:
        return {name: np.asarray(var.values) for name, var in dataset.variables.items()}


def load_source(source: Path) -> Dict[str, object]:
    """Read one data source for the statistical comparator.

    A source is a single file, or a directory whose readable data files are
    merged into one namespace. A name defined by two files in the same
    directory is an error rather than a silent last-one-wins.
    """
    if source.is_file():
        return read_variables(source)
    if not source.is_dir():
        raise DataError("no such file or directory: %s" % source)
    merged: Dict[str, object] = {}
    origin: Dict[str, str] = {}
    for path in sorted(source.iterdir()):
        if not path.is_file() or path.suffix not in SUPPORTED_SUFFIXES:
            continue
        for name, value in read_variables(path).items():
            if name in merged:
                raise DataError(
                    "%s: variable %r is defined by both %s and %s"
                    % (source, name, origin[name], path.name)
                )
            merged[name] = value
            origin[name] = path.name
    if not merged:
        raise DataError(
            "%s holds no readable data files (%s)"
            % (source, ", ".join(SUPPORTED_SUFFIXES))
        )
    return merged


# --------------------------------------------------------------------------
# documents


def load_document(path: Path) -> dict:
    """Read a JSON or YAML document — a benchmark file or an acceptance block.

    Benchmarks are YAML by convention, and PyYAML is not in the standard
    library. Rather than shipping a partial YAML reader whose disagreements
    with the real thing would surface as wrong acceptance criteria, a YAML
    document with no PyYAML installed is a DataError naming both ways out.
    """
    if not path.is_file():
        raise DataError("no such document: %s" % path)
    text = path.read_text()
    if path.suffix == ".json":
        try:
            return json.loads(text)
        except ValueError as exc:
            raise DataError("%s is not valid JSON: %s" % (path, exc)) from exc
    try:
        import yaml
    except ImportError:
        raise DataError(
            "cannot read %s: PyYAML is not installed. Install PyYAML, or supply "
            "the same document as .json." % path.name
        ) from None
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DataError("%s is not valid YAML: %s" % (path, exc)) from exc
    if not isinstance(document, dict):
        raise DataError("%s does not hold a mapping" % path)
    return document


# --------------------------------------------------------------------------
# GPTL timing


def case_root_from_run_dir(run_dir: Path) -> Optional[Path]:
    caseroot_file = run_dir / "CASEROOT"
    if not caseroot_file.is_file():
        return None
    text = caseroot_file.read_text().strip()
    return Path(text) if text else None


def find_timing_stats_file(run_dir: Path) -> Path:
    """Locate cesm_timing_stats, preferring the run directory's own copy."""
    direct = run_dir / "timing" / "cesm_timing_stats"
    if direct.is_file():
        return direct
    candidates: List[Path] = []
    timing_dirs = [run_dir / "timing"]
    case_root = case_root_from_run_dir(run_dir)
    if case_root is not None:
        timing_dirs.append(case_root / "timing")
    for timing_dir in timing_dirs:
        if not timing_dir.is_dir():
            continue
        candidates.extend(
            p for p in timing_dir.iterdir()
            if p.name == "cesm_timing_stats"
            or (p.name.startswith("cesm_timing_stats.") and not p.name.endswith(".gz"))
        )
    if not candidates:
        raise DataError("no cesm_timing_stats file found under %s" % run_dir)
    return max(candidates, key=lambda path: path.stat().st_mtime)


def extract_timer(run_dir: Path, timer_name: str) -> float:
    """Wall time for one GPTL timer.

    Field index 6 of the '"name" ...' line, which is what the PyCAM5 script
    read; the column is preserved rather than reinterpreted, so timings stay
    comparable with the numbers already reported.
    """
    timing_file = find_timing_stats_file(run_dir)
    with timing_file.open() as handle:
        for line in handle:
            if '"%s"' % timer_name in line:
                parts = line.split()
                try:
                    return float(parts[6])
                except (IndexError, ValueError) as exc:
                    raise DataError(
                        "malformed timing line for %s in %s" % (timer_name, timing_file)
                    ) from exc
    raise DataError("timer %s not found in %s" % (timer_name, timing_file))
