from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardizers.coil_counts import (  # noqa: E402
    apply_company_simple_active_coils,
    derive_active_coils,
)
from ai_design_review.standardizers import standardize_spring  # noqa: E402


def main() -> None:
    assert _derived_value("compression_spring", 10) == 8
    assert _derived_value("extension_spring", 10) == 10
    assert _derived_value("torsion_spring", 10) == 10
    assert _standardized_value("extension_spring", 10) == 10
    assert _standardized_value("torsion_spring", 10) == 10
    assert derive_active_coils("compression_spring", _parameters(10, active=7)) == {}
    assert derive_active_coils("compression_spring", _parameters(2)) == {}
    _assert_company_default_refreshes_with_total_coils()
    print("active coil derivation tests passed")


def _derived_value(spring_type: str, total: float) -> float:
    item = derive_active_coils(spring_type, _parameters(total))["active_coils"]
    return item["value"]


def _standardized_value(spring_type: str, total: float) -> float:
    payload = standardize_spring(spring_type, _parameters(total))
    return payload["derived_parameters"]["active_coils"]["value"]


def _parameters(total: float, *, active: float | None = None) -> dict:
    parameters = {"total_coils": {"value": total, "unit": "turns"}}
    if active is not None:
        parameters["active_coils"] = {"value": active, "unit": "turns"}
    return parameters


def _assert_company_default_refreshes_with_total_coils() -> None:
    parameters = _parameters(10)
    assert apply_company_simple_active_coils("compression_spring", parameters) is True
    assert parameters["active_coils"]["value"] == 8
    parameters["total_coils"]["value"] = 12
    assert apply_company_simple_active_coils("compression_spring", parameters) is True
    assert parameters["active_coils"]["value"] == 10

    parameters["active_coils"]["value"] = 9
    parameters["active_coils"]["source"] = ["company_simple_rule", "human_edited"]
    assert apply_company_simple_active_coils("compression_spring", parameters) is False
    assert parameters["active_coils"]["value"] == 9


if __name__ == "__main__":
    main()
