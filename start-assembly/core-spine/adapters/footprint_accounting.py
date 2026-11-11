"""Footprint accounting adapter (Module 17) — pymrio as a dependency.

pymrio (IndEcol/pymrio) is used here as a library only: no pymrio code
is copied into this assembly, and the library is kept unmodified and
replaceable — it stays a pip dependency, never vendored.

    pymrio 0.7.0 (PyPI, verified 2026-11-11), sweep clone HEAD c22b419
    (2026-10-22), 11,254 lines, 227 stars.
    LGPL-3.0 — LICENSE file contains the full GNU Lesser General
    Public License v3 text, Copyright (c) 2014 Konstantin Stadler;
    the PyPI classifier agrees ("GNU Lesser General Public License
    v3 (LGPLv3)").
    WARNING, licence inconsistency (recorded, LICENSE authoritative):
    the README.rst badge says "License-GPL v3" and links to
    gpl-3.0, while the LICENSE file and the classifier say LGPL-3.0.
    The LICENSE file is authoritative; the badge is wrong.

ADJUST conditions from the source audit (binding, all four):
1. Dependency ONLY — never copy pymrio code into START. The LGPL-3.0
   notice is kept and the library stays unmodified and replaceable /
   relinkable, so it is never vendored or copied into MIT-licensed
   START code.
2. pymrio's automatic downloads of EXIOBASE / WIOD / EORA databases
   go through START's data-fetch approval and provenance path, never
   as an unreviewed side effect. This adapter NEVER calls any
   pymrio download, load, or parse function (no load_exiobase,
   load_wiod, load_eora26, download_*, parse_*, load_all,
   load_test, get_repo_content). It only constructs an IOSystem
   from in-memory NumPy/pandas arrays. The tests prove this two
   ways: the adapter source contains none of the forbidden call
   names, and build + check still pass with the network socket
   blocked and every pymrio download function monkeypatched to
   raise.
3. Its computed accounts are model results — candidates through
   the separate verify step with needs_human_decision=true.
4. The README-badge vs LICENSE-file inconsistency is recorded
   here and in LICENCES.md; the LICENSE file is authoritative.

Governance (binding): pymrio computes accounts. Its outputs are
model results, NOT verified plans. Every result this adapter
returns carries verified=false and needs_human_decision=true,
and must still go through START's separate verify step like any
other model output. Nothing from pymrio may mark a plan verified
or authorise anything.

Synthetic case (clearly synthetic, not a real region or a real
database): a 2-region x 2-sector environmentally extended
multi-regional input-output table, one stressor (CO2, t), one
final-demand category (Households) per region, built in memory
from plain arrays:

    Regions:  R1, R2
    Sectors:  Agriculture, Manufacturing
    Z (intermediate demand, t):      [[10, 5, 2, 1],
                                      [ 4,20, 3, 2],
                                      [ 1, 2,15, 6],
                                      [ 2, 1, 4,25]]
    Y (final demand, t):             [[30, 5],
                                      [20, 8],
                                      [10,25],
                                      [ 5,30]]
    F (CO2 per unit output, t/t):    [[2, 1, 0.5, 0.2]]

pymrio's calc_all() then gives total output x = [53, 57, 59, 67] t
and the emissions accounts D_pba (production-based), D_cba
(consumption-based), D_imp and D_exp (trade-embodied imports /
exports). The footprint identity this adapter checks, per region r:

    D_pba[r] = D_cba[r] + D_exp[r] - D_imp[r]

and, over all regions, total production-based = total
consumption-based (trade cancels). On the synthetic case the
identity holds exactly: D_pba = [3.0, 0.7] t, D_cba =
[2.44025416, 1.25974584] t, D_imp = [0.19171127, 0.75145711] t,
D_exp = [0.75145711, 0.19171127] t, totals 3.7 t each, residual
0.0 t (2.2e-16 t in floating point).

Consistency check, under the spine's status rules
(adapters/statuses.py):
- PASS when the largest absolute identity residual is within the
  stated tolerance (default 1e-9 t).
- FAIL when it exceeds the tolerance — a deliberately inconsistent
  case (an emissions account tampered with after calculation) is
  detected, never passed.
- UNKNOWN when the input is missing (None), empty (no Z/Y), or
  contains non-finite values — never PASS.
"""

import math

import numpy as np
import pandas as pd
import pymrio

from adapters.statuses import ConstraintResult, InternalStatus

PYMRIO_VERSION = "0.7.0"
PYMRIO_REPO = "IndEcol/pymrio"
PYMRIO_LICENCE = "LGPL-3.0"
PYMRIO_SWEEP_COMMIT = "c22b419"

REGIONS = ["R1", "R2"]
SECTORS = ["Agriculture", "Manufacturing"]
STRESSOR = "CO2"
UNIT = "t"

# Synthetic intermediate-demand matrix Z, rows/cols ordered
# (R1, Agriculture), (R1, Manufacturing), (R2, Agriculture),
# (R2, Manufacturing). See module docstring.
SYNTHETIC_Z = np.array(
    [
        [10.0, 5.0, 2.0, 1.0],
        [4.0, 20.0, 3.0, 2.0],
        [1.0, 2.0, 15.0, 6.0],
        [2.0, 1.0, 4.0, 25.0],
    ]
)

# Synthetic final demand Y: one Households column per region.
SYNTHETIC_Y = np.array(
    [
        [30.0, 5.0],
        [20.0, 8.0],
        [10.0, 25.0],
        [5.0, 30.0],
    ]
)

# Synthetic CO2 extension F, t of CO2 per t of output.
SYNTHETIC_F = np.array([[2.0, 1.0, 0.5, 0.2]])

# Call names this adapter must never use: any pymrio download, load,
# or parse of a real database. Enforced by tests/test_footprint_accounting.py.
FORBIDDEN_CALLS = (
    "load_exiobase",
    "load_wiod",
    "load_eora",
    "download_",
    "parse_",
    "load_all",
    "load_test",
    "get_repo_content",
)


def pymrio_version() -> str:
    """Installed pymrio version string, as reported by the package."""
    return getattr(pymrio, "__version__", "unknown")


def _sector_index():
    return pd.MultiIndex.from_product(
        [REGIONS, SECTORS], names=["region", "sector"]
    )


def build_system(z_values=None, y_values=None, f_values=None):
    """Build the synthetic IOSystem entirely in memory.

    z_values / y_values / f_values override the synthetic defaults
    with plain arrays of the same shapes. No file is read, no
    database is parsed, and no download is triggered — the system
    is constructed from the arrays alone. Passing an empty or
    missing array builds a system whose consistency check must
    come back UNKNOWN — never PASS.
    """
    z = np.array(SYNTHETIC_Z if z_values is None else z_values, dtype=float)
    y = np.array(SYNTHETIC_Y if y_values is None else y_values, dtype=float)
    f = np.array(SYNTHETIC_F if f_values is None else f_values, dtype=float)
    idx = _sector_index()
    z_df = pd.DataFrame(z, index=idx, columns=idx)
    y_df = pd.DataFrame(
        y,
        index=idx,
        columns=pd.MultiIndex.from_product(
            [REGIONS, ["Households"]], names=["region", "category"]
        ),
    )
    f_df = pd.DataFrame(
        f, index=pd.Index([STRESSOR], name="stressor"), columns=idx
    )
    unit_df = pd.DataFrame(
        [[UNIT] * len(idx)], index=["unit"], columns=idx
    )
    system = pymrio.IOSystem(
        Z=z_df,
        Y=y_df,
        emissions=dict(name="emissions", F=f_df),
        unit=unit_df,
        name="START synthetic 2-region MRIO",
        description="Synthetic — not a real region or a real database",
    )
    system.calc_all()
    return system


def _by_region(df) -> np.ndarray:
    """Sum a (stressor x sector) account frame per region."""
    # DataFrame.groupby(axis=1) is removed in pandas 3.x; transpose.
    return df.T.groupby(level=0).sum().T.values.flatten()


def _accounts_are_finite(system) -> bool:
    for attr in ("Z", "Y"):
        frame = getattr(system, attr, None)
        if frame is None or frame.size == 0:
            return False
        if not np.all(np.isfinite(frame.values.astype(float))):
            return False
    ext = getattr(system, "emissions", None)
    if ext is None:
        return False
    for attr in ("F", "D_pba", "D_cba", "D_imp", "D_exp"):
        frame = getattr(ext, attr, None)
        if frame is None:
            return False
        if not np.all(np.isfinite(frame.values.astype(float))):
            return False
    return True


def check_footprint(system, tolerance: float = 1e-9) -> ConstraintResult:
    """Footprint-consistency check for a pymrio IOSystem.

    Checks the per-region identity D_pba[r] = D_cba[r] + D_exp[r] -
    D_imp[r] and the global identity total D_pba = total D_cba.
    PASS when the largest absolute residual is within tolerance;
    FAIL when it exceeds it; UNKNOWN when the system is missing,
    empty, or non-finite.
    """
    constraint_id = "pymrio-footprint-identity"
    if system is None:
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "no IOSystem supplied: nothing to check",
        )
    if getattr(system, "Z", None) is None or getattr(system, "Y", None) is None:
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "empty system (no Z/Y): footprint identity cannot be checked",
            evidence=["Z or Y missing"],
        )
    if system.Z.size == 0 or system.Y.size == 0:
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "empty system (empty Z/Y): footprint identity cannot be checked",
            evidence=["Z or Y empty"],
        )
    if not _accounts_are_finite(system):
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "non-finite or missing values in Z/Y/F or accounts: "
            "footprint identity cannot be checked",
        )
    ext = system.emissions
    pba = _by_region(ext.D_pba)
    cba = _by_region(ext.D_cba)
    imp = _by_region(ext.D_imp)
    exp = _by_region(ext.D_exp)
    per_region_residual = pba - (cba + exp - imp)
    total_residual = float(pba.sum() - cba.sum())
    residual = float(
        max(
            float(np.max(np.abs(per_region_residual))),
            abs(total_residual),
        )
    )
    if not math.isfinite(residual):
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "non-finite footprint residual",
            actual_value=residual,
            unit=UNIT,
        )
    status = (
        InternalStatus.PASS if residual <= tolerance else InternalStatus.FAIL
    )
    return ConstraintResult(
        constraint_id,
        status,
        (
            f"max |D_pba - (D_cba + D_exp - D_imp)| = {residual} {UNIT} "
            f"vs tolerance {tolerance} {UNIT}: {status.value}"
        ),
        actual_value=residual,
        required_value=tolerance,
        unit=UNIT,
        evidence=[
            f"pymrio {PYMRIO_VERSION} (LGPL-3.0, dependency only)",
            f"regions {REGIONS}, sectors {SECTORS}, stressor {STRESSOR}",
            f"D_pba total {float(pba.sum())} {UNIT}, "
            f"D_cba total {float(cba.sum())} {UNIT}",
        ],
        source_ids=["synthetic-2-region-mrio"],
    )


def accounts_to_dict(system, check: ConstraintResult = None) -> dict:
    """Return the computed accounts as plain JSON-able data.

    Model results only: verified=false, needs_human_decision=true.
    These accounts are candidates for the separate verify step, never
    a verification of any plan.
    """
    if check is None:
        check = check_footprint(system)
    ext = system.emissions
    return {
        "schema_version": "1.0.0",
        "system": "START synthetic 2-region MRIO",
        "synthetic": True,
        "unit": UNIT,
        "regions": list(REGIONS),
        "sectors": list(SECTORS),
        "stressor": STRESSOR,
        "pymrio_version": PYMRIO_VERSION,
        "pymrio_repo": PYMRIO_REPO,
        "pymrio_licence": PYMRIO_LICENCE,
        "total_output_t": [float(v) for v in system.x.values.flatten()],
        "production_based_co2_t": {
            region: float(v)
            for region, v in zip(REGIONS, _by_region(ext.D_pba))
        },
        "consumption_based_co2_t": {
            region: float(v)
            for region, v in zip(REGIONS, _by_region(ext.D_cba))
        },
        "trade_embodied_imports_co2_t": {
            region: float(v)
            for region, v in zip(REGIONS, _by_region(ext.D_imp))
        },
        "trade_embodied_exports_co2_t": {
            region: float(v)
            for region, v in zip(REGIONS, _by_region(ext.D_exp))
        },
        "footprint_identity": check.to_dict(),
        "verified": False,
        "needs_human_decision": True,
    }
