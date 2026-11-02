"""Shared Python/JS cases for explicit technical-output choices, without models."""
from __future__ import annotations

import json
import sys
from copy import deepcopy

from test_solidworks_export import base_review
from ai_design_review.generation_readiness import build_generation_parameter_package
from ai_design_review.solidworks import build_solidworks_command, build_solidworks_technical_projection
from ai_design_review.technical_output_deletions import refresh_technical_output_deletions


def deletion(entry):
    return deepcopy({key: entry[key] for key in ("source_key", "fields", "load_point_ids", "basis")})


def fixture():
    review = base_review()
    review["technical_requirements"] = []
    review["spring_parameters"]["solid_height"].update(source=["manual"], value_kind="input_height")
    build_generation_parameter_package(review)
    return review


def shared_cases():
    cases = []

    def add(name, review, package=None):
        package = package or build_generation_parameter_package(review)
        before = deepcopy(review)
        projection = build_solidworks_technical_projection(package, review)
        assert review == before, name + " projection is read-only"
        assert [entry["display"] for entry in projection["entries"]] == [f"{i}.{entry['body']}" for i, entry in enumerate(projection["entries"], 1)]
        cases.append({"name": name, "review": deepcopy(review), "package": deepcopy(package), "projection": projection})
        return projection

    base = fixture()
    initial = add("baseline", base)
    assert len(initial["entries"]) == 7
    for entry in initial["entries"]:
        review = deepcopy(base)
        review["technical_output_deletions"] = [deletion(entry)]
        before = deepcopy(review["spring_parameters"])
        projection = add("delete_" + entry["source_key"], review)
        assert entry["source_key"] not in [item["source_key"] for item in projection["entries"]]
        assert len(projection["entries"]) == 6 and review["spring_parameters"] == before
    review = deepcopy(base)
    review["technical_output_deletions"] = [deletion(entry) for entry in initial["entries"]]
    assert add("delete_all", review)["text"] == ""

    for key, field, value in [("auto:handedness", "handedness", "left"), ("auto:coils", "total_coils", 4.5),
                              ("auto:end", "end_grinding", "两端不磨削"), ("auto:solid_height", "solid_height", 7)]:
        entry = next(item for item in initial["entries"] if item["source_key"] == key)
        review = deepcopy(base)
        review["technical_output_deletions"] = [deletion(entry)]
        review["spring_parameters"]["material"]["value"] = "65Mn"
        refresh_technical_output_deletions(review)
        assert len(review["technical_output_deletions"]) == 1
        add("unrelated_" + key, review)
        review["spring_parameters"][field]["need_human_review"] = True
        refresh_technical_output_deletions(review)
        assert len(review["technical_output_deletions"]) == 1, "confirmation alone does not expire a choice"
        add("pending_" + key, review)
        review["spring_parameters"][field]["value"] = value
        refresh_technical_output_deletions(review)
        assert not review["technical_output_deletions"]
        add("changed_pending_" + key, review)
        review["spring_parameters"][field]["need_human_review"] = False
        assert key in [item["source_key"] for item in add("changed_confirmed_" + key, review)["entries"]]

    for change, value in [("label", "P1"), ("force", 20), ("height", 15), ("load_tolerance_percent", 5)]:
        review = deepcopy(base)
        point = review["spring_parameters"]["load_points"][0]
        entry = next(item for item in initial["entries"] if point["load_point_id"] in item["load_point_ids"])
        review["technical_output_deletions"] = [deletion(entry)]
        review["spring_parameters"]["load_points"].reverse()
        refresh_technical_output_deletions(review)
        assert review["technical_output_deletions"], "reorder preserves stable point association"
        point[change] = value
        refresh_technical_output_deletions(review)
        assert not review["technical_output_deletions"]
        add("load_" + change, review)

    for auto in initial["entries"][:3]:
        review = deepcopy(base)
        review["technical_requirements"] = [{"requirement_id": "raw", "type": "other", "content": auto["body"], "need_human_review": False}]
        linked = next(item for item in add("linked_" + auto["source_key"], review)["entries"] if item["source_key"] == auto["source_key"])
        assert linked["requirement_ids"] == ["raw"]
        review["technical_output_deletions"] = [deletion(linked)]
        review["technical_requirements"] = []
        assert auto["source_key"] not in [item["source_key"] for item in add("linked_deleted_" + auto["source_key"], review)["entries"]]
        review["technical_requirements"] = [{"requirement_id": "new", "type": "other", "content": auto["body"], "need_human_review": False}]
        restored = add("new_explicit_" + auto["source_key"], review)
        assert any(item["body"] == auto["body"] and not item["automatic"] and item["requirement_ids"] == ["new"] for item in restored["entries"])

    review = deepcopy(base)
    entry = initial["entries"][0]
    review["technical_output_deletions"] = [deletion(entry)]
    review["technical_output_deletions"][0]["basis"]["parameters"][0][1]["value"] = "forged"
    assert add("wrong_basis", review)["text"] == initial["text"]
    review = deepcopy(base)
    package = build_generation_parameter_package(review)
    package["generation_parameters"]["technical_requirements"] = []
    package["generation_parameters"]["technical_requirements_text"] = "1.不得有锐边。"
    legacy = next(item for item in add("legacy", review, package)["entries"] if item["body"] == "不得有锐边。")
    review["technical_output_deletions"] = [deletion(legacy)]
    assert "不得有锐边" not in add("legacy_deleted", review, package)["text"]
    frozen = build_generation_parameter_package(base)
    changed = deepcopy(base)
    changed["technical_output_deletions"] = [deletion(entry) for entry in initial["entries"]]
    command = build_solidworks_command("1000000001", frozen, changed)
    assert command["models"][0]["extraProperties"]["技术要求"] == frozen["solidworks_preview"]["extraProperties"]["技术要求"]
    return cases


if __name__ == "__main__":
    rows = shared_cases()
    if "--json" in sys.argv:
        print(json.dumps(rows))
    else:
        print(f"PASS {len(rows)} technical deletion cases: provenance, decimal coils, all-delete, input/confirmation changes, stable loads, explicit re-add, legacy and frozen requests")
