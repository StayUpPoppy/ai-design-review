from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_design_review.standardizers.coil_counts import (  # noqa: E402
    apply_company_simple_active_coils,
    derive_active_coils,
)
from ai_design_review.end_conditions import normalize_end_grinding, normalize_end_type  # noqa: E402
from ai_design_review.standardizers import standardize_spring  # noqa: E402


def main() -> None:
    assert normalize_end_grinding("两端磨平") == "两端磨削"
    assert normalize_end_grinding("未磨") == "两端不磨削"
    assert normalize_end_type("闭口") == "两端并紧"
    assert normalize_end_type("开口") == "两端不并紧"
    assert _derived_value("compression_spring", 10, end_type="两端不并紧") == 10
    assert _derived_value("compression_spring", 10, end_type="两端并紧") == 8
    assert _derived_value("compression_spring", 10, end_type="两端并紧", support=1.5) == 7
    assert _derived_value("extension_spring", 10) == 10
    assert _derived_value("torsion_spring", 10) == 10
    assert _standardized_value("extension_spring", 10) == 10
    assert _standardized_value("torsion_spring", 10) == 10
    assert derive_active_coils("compression_spring", _parameters(10, active=7, end_type="两端并紧")) == {}
    assert derive_active_coils("compression_spring", _parameters(10)) == {}
    assert derive_active_coils("compression_spring", _parameters(2, end_type="两端并紧")) == {}
    _assert_company_default_refreshes_with_total_coils()
    print("active coil derivation tests passed")


def _derived_value(spring_type: str, total: float, *, end_type: str | None = None, support: float | None = None) -> float:
    item = derive_active_coils(spring_type, _parameters(total, end_type=end_type, support=support))["active_coils"]
    return item["value"]


def _standardized_value(spring_type: str, total: float) -> float:
    payload = standardize_spring(spring_type, _parameters(total))
    return payload["derived_parameters"]["active_coils"]["value"]


def _parameters(
    total: float,
    *,
    active: float | None = None,
    end_type: str | None = None,
    support: float | None = None,
) -> dict:
    parameters = {"total_coils": {"value": total, "unit": "turns"}}
    if active is not None:
        parameters["active_coils"] = {"value": active, "unit": "turns"}
    if end_type is not None:
        parameters["end_type"] = {"value": end_type}
    if support is not None:
        parameters["support_coils"] = {"value": support, "unit": "turns"}
    return parameters


def _assert_company_default_refreshes_with_total_coils() -> None:
    parameters = _parameters(10, end_type="两端并紧")
    assert apply_company_simple_active_coils("compression_spring", parameters) is True
    assert parameters["active_coils"]["value"] == 8
    parameters["total_coils"]["value"] = 12
    assert apply_company_simple_active_coils("compression_spring", parameters) is True
    assert parameters["active_coils"]["value"] == 10

    parameters["active_coils"]["value"] = 9
    parameters["active_coils"]["source"] = ["company_active_coil_rule", "human_edited"]
    assert apply_company_simple_active_coils("compression_spring", parameters) is False
    assert parameters["active_coils"]["value"] == 9


if __name__ == "__main__":
    main()
