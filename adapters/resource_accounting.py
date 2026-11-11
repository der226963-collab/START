"""Resource accounting adapter (Module 17) — ODYM as a dependency.

ODYM (Open Dynamic Material Systems Model, IndEcol/ODYM) is used here
as a library only: no ODYM code is copied into this assembly.
Installed from git, pinned to the sweep's audited commit, because ODYM
was never published to PyPI (`pip install ODYM` fails; pypi.org returns
404 for it — see ASSEMBLY_REPORT.md item 9).

    ODYM 0.1.0, commit 9792c23b1faced9515b425033694328aa8301c0f (2025-09-26)
    MIT, Copyright (c) 2025 International Society for Industrial
    Ecology and Contributors.

Cautions, from the source audit (binding):
- xlwt/xlrd are legacy Excel dependencies. This adapter never calls
  any ODYM Excel read/write — in-memory only.
- MFAsystem uses mutable default arguments (ProcessList=[],
  FlowDict={}). This adapter ALWAYS passes explicit, freshly built
  lists/dicts at construction and never relies on the defaults.

Governance (binding): ODYM computes accounts. Its outputs are model
results, NOT verified plans. Every result this adapter returns carries
verified=false and needs_human_decision=true, and must still go
through START's separate verify step like any other model output.
Nothing from ODYM may mark a plan verified or authorise anything.

Synthetic case (clearly synthetic, not a real region): the material
stock-flow embodied in the spine's 1-site 2-crop food system
(wheat 50 ha / potato 20 ha, delivered 600 t / shortage 50 t in the
LP), reduced to one material in tonnes over 3 years (2026-2028):
fertiliser enters the Field from the Environment, harvest moves
Field -> Storage, dispatch leaves Storage for the Environment
(consumption). The Field retains part of the input as stock and
Storage accumulates/releases stock, so the stock changes below are
part of the balance, not an afterthought.

    F_0_1 fertiliser in, t/yr:  [10, 12, 11]
    F_1_2 harvest, t/yr:        [ 8, 10,  9]
    F_2_0 dispatch, t/yr:       [ 7,  9, 10]
    S_1 field stock change:     [ 2,  2,  2]  (= F_0_1 - F_1_2)
    S_2 storage stock change:   [ 1,  1, -1]  (= F_1_2 - F_2_0)

Under ODYM's own MassBalance() this system balances exactly
(residual 0 at every year, process and element): for each process,
inflows - outflows - net stock change = 0.

Balance check, under the spine's status rules (adapters/statuses.py):
- PASS when the largest absolute MassBalance residual is within the
  stated tolerance (default 1e-9 t).
- FAIL when it exceeds the tolerance — a deliberately unbalanced case
  is detected, never passed.
- UNKNOWN when the input is missing (None), empty (no flows), or
  contains non-finite values — never PASS.
"""

import math

import numpy as np
import pandas as pd

import odym.classes as _odym_classes

from adapters.statuses import ConstraintResult, InternalStatus

ODYM_VERSION = "0.1.0"
ODYM_PINNED_COMMIT = "9792c23b1faced9515b425033694328aa8301c0f"
ODYM_PINNED_COMMIT_SHORT = "9792c23"
ODYM_REPO = "IndEcol/ODYM"
ODYM_LICENCE = "MIT"

# Synthetic years and material. One element ("All") only.
YEARS = [2026, 2027, 2028]
UNIT = "t"

# Synthetic flow values, t/yr, one row per year (see module docstring).
SYNTHETIC_FLOWS = {
    "F_0_1": [10.0, 12.0, 11.0],  # fertiliser: Environment -> Field
    "F_1_2": [8.0, 10.0, 9.0],    # harvest: Field -> Storage
    "F_2_0": [7.0, 9.0, 10.0],    # dispatch: Storage -> Environment
}

# Synthetic net stock changes (ODYM Stock Type 1), t/yr.
SYNTHETIC_STOCKS = {
    "S_1": [2.0, 2.0, 2.0],    # field stock change, at process 1
    "S_2": [1.0, 1.0, -1.0],   # storage stock change, at process 2
}

_FLOW_DEFS = (
    ("F_0_1", "Fertiliser input", 0, 1),
    ("F_1_2", "Harvest", 1, 2),
    ("F_2_0", "Dispatch", 2, 0),
)

_STOCK_DEFS = (
    ("S_1", "Field stock change", 1),
    ("S_2", "Storage stock change", 2),
)

_PROCESS_DEFS = (
    (0, "Environment"),
    (1, "Field"),
    (2, "Storage"),
)


def odym_version() -> str:
    """Installed ODYM version string, as reported by the package."""
    import odym

    return getattr(odym, "__version__", "unknown")


def build_index_table(years=None) -> pd.DataFrame:
    """Minimal ODYM index table: Time, Element, Unity.

    ODYM requires 'Time' and 'Element' aspects to be present.
    """
    years = list(years) if years is not None else list(YEARS)
    classifications = {
        "Time": _odym_classes.Classification(
            Name="Time", Dimension="Time", Items=years
        ),
        "Element": _odym_classes.Classification(
            Name="Chem_Elements", Dimension="Element", Items=["All"]
        ),
        "Unity": _odym_classes.Classification(
            Name="Unity", Dimension="Unity", Items=[1]
        ),
    }
    aspects = ["Time", "Element", "Unity"]
    table = pd.DataFrame(
        {
            "Aspect": aspects,
            "Description": ["Time", "Element", "Unity"],
            "Dimension": ["Time", "Element", "Unity"],
            "Classification": [classifications[a] for a in aspects],
            "IndexLetter": ["t", "e", "i"],
        }
    )
    # set_index(inplace=True) is deprecated in pandas 3.x (PDEP-8).
    return table.set_index("Aspect")


def build_system(flow_values=None, stock_values=None, years=None):
    """Build the synthetic MFAsystem.

    flow_values / stock_values override the synthetic defaults, keyed
    by flow/stock id, one value per year. Passing an empty dict (or a
    dict with a flow removed) builds a system whose balance check
    must come back FAIL or UNKNOWN — never PASS.

    Every collection is built fresh here and passed explicitly to
    MFAsystem: the constructor's mutable defaults (ProcessList=[],
    FlowDict={}) are never relied on.
    """
    years = list(years) if years is not None else list(YEARS)
    flows = dict(SYNTHETIC_FLOWS if flow_values is None else flow_values)
    stocks = dict(SYNTHETIC_STOCKS if stock_values is None else stock_values)
    index_table = build_index_table(years)

    # Explicit, freshly built collections — never the constructor defaults.
    process_list = [
        _odym_classes.Process(Name=name, ID=pid) for pid, name in _PROCESS_DEFS
    ]
    flow_dict = {
        key: _odym_classes.Flow(
            Name=name,
            P_Start=p_start,
            P_End=p_end,
            Indices="t,e",
            Values=np.array(flows[key], dtype=float).reshape(len(years), 1),
            Uncert=None,
        )
        for key, name, p_start, p_end in _FLOW_DEFS
        if key in flows
    }
    stock_dict = {
        key: _odym_classes.Stock(
            Name=name,
            P_Res=p_res,
            Indices="t,e",
            Type=1,  # net stock change / addition to stock
            Values=np.array(stocks[key], dtype=float).reshape(len(years), 1),
            Uncert=None,
        )
        for key, name, p_res in _STOCK_DEFS
        if key in stocks
    }

    system = _odym_classes.MFAsystem(
        Name="START synthetic food-system material flow",
        Time_Start=min(years),
        Time_End=max(years),
        Geogr_Scope="Synthetic — not a real region",
        Unit=UNIT,
        IndexTable=index_table,
        Elements=index_table.loc["Element"].Classification.Items,
        ProcessList=process_list,
        FlowDict=flow_dict,
        StockDict=stock_dict,
        ParameterDict={},
    )
    return system


def _values_are_finite(system) -> bool:
    for flow in system.FlowDict.values():
        if flow.Values is None or not np.all(np.isfinite(flow.Values)):
            return False
    for stock in system.StockDict.values():
        if stock.Values is None or not np.all(np.isfinite(stock.Values)):
            return False
    return True


def check_balance(system, tolerance: float = 1e-9) -> ConstraintResult:
    """Stock-flow balance check for an ODYM MFAsystem.

    Uses ODYM's own MassBalance(): residual = inflows - outflows -
    net stock change, per year/process/element. PASS when the largest
    absolute residual is within tolerance; FAIL when it exceeds it;
    UNKNOWN when the system is missing, empty, or non-finite.
    """
    constraint_id = "odym-stock-flow-balance"
    if system is None:
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "no MFAsystem supplied: nothing to balance-check",
        )
    if not system.FlowDict:
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "empty system (no flows): balance cannot be checked",
            evidence=["no flows in FlowDict"],
        )
    if not _values_are_finite(system):
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "non-finite or missing flow/stock values: balance cannot be checked",
        )
    balance = system.MassBalance()
    residual = float(np.max(np.abs(balance))) if balance.size else 0.0
    if not math.isfinite(residual):
        return ConstraintResult(
            constraint_id,
            InternalStatus.UNKNOWN,
            "non-finite mass-balance residual",
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
            f"max |inflows - outflows - stock change| = {residual} {UNIT} "
            f"vs tolerance {tolerance} {UNIT}: {status.value}"
        ),
        actual_value=residual,
        required_value=tolerance,
        unit=UNIT,
        evidence=[
            f"odym {ODYM_VERSION} @ {ODYM_PINNED_COMMIT_SHORT}",
            f"years {system.Time_Start}-{system.Time_End}",
            f"processes {[p.Name for p in system.ProcessList]}",
        ],
        source_ids=["synthetic-food-system-material-flow"],
    )


def accounts_to_dict(system, balance: ConstraintResult = None) -> dict:
    """Return the computed accounts as plain JSON-able data.

    Model results only: verified=false, needs_human_decision=true.
    These accounts are candidates for the separate verify step, never
    a verification of any plan.
    """
    if balance is None:
        balance = check_balance(system)
    flows = {
        key: [float(v) for v in flow.Values.flatten()]
        for key, flow in system.FlowDict.items()
    }
    stocks = {
        key: [float(v) for v in stock.Values.flatten()]
        for key, stock in system.StockDict.items()
    }
    return {
        "schema_version": "1.0.0",
        "system": "START synthetic food-system material flow",
        "synthetic": True,
        "unit": UNIT,
        "years": list(system.Time_L),
        "odym_version": ODYM_VERSION,
        "odym_commit": ODYM_PINNED_COMMIT_SHORT,
        "odym_repo": ODYM_REPO,
        "processes": [p.Name for p in system.ProcessList],
        "flows_t_per_year": flows,
        "stock_changes_t_per_year": stocks,
        "balance": balance.to_dict(),
        "verified": False,
        "needs_human_decision": True,
    }
