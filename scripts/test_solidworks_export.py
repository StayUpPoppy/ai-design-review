"""Shared review cases for Python/JavaScript SolidWorks export parity."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_design_review.generation_readiness import build_generation_parameter_package, assess_generation_readiness
from ai_design_review.generation_contract import COMPRESSION_GENERATION_INPUT_FIELDS
from ai_design_review.generation_schemas import GenerationParameterPackageV2
from ai_design_review.solidworks import build_solidworks_command, build_solidworks_preview, build_solidworks_technical_text


def parameter(value, unit=None, **extra):
    return {"value": value, "unit": unit, "source": ["drawing"], "need_human_review": False, **extra}


def base_review():
    return {"drawing_summary": {"spring_type": "compression_spring", "drawing_name": "订单2"},
            "spring_features": {"pitch_type": {"value": "constant"}},
            "spring_parameters": {
                "material": parameter("SUS304 不锈钢"), "wire_diameter": parameter(1.8, "mm"),
                "mean_diameter": parameter(25.2, "mm"), "free_length": parameter(19, "mm"),
                "total_coils": parameter(4, "圈"), "active_coils": parameter(2, "圈"),
                "support_coils": parameter(1, "圈"), "handedness": parameter("right"),
                "pitch": parameter(8.15, "mm"),
                "end_type": parameter("两端并紧"), "end_grinding": parameter("两端磨削"),
                "solid_height": parameter(6.3, "mm", value_kind="nominal_estimate", source=["formula_calculation"], source_fields=["wire_diameter", "active_coils", "support_coils", "end_type", "end_grinding"]),
                "surface_roughness_ra": parameter(12.5, "μm", surface_location="两端面"),
                "load_points": [
                    {"label": "F1", "height": 14.284, "force": 13.2, "load_tolerance_percent": 10, "need_human_review": False},
                    {"label": "F2", "height": 12.284, "force": 18.9, "load_tolerance_upper": 1, "load_tolerance_lower": -0.5, "need_human_review": False},
                    {"label": "F3", "height": 10, "force": 0, "need_human_review": False},
                ]},
            "technical_requirements": [
                {"type": "other", "content": "材料：SUS304 不锈钢。", "need_human_review": False},
                {"type": "other", "content": "旋向：右旋。", "need_human_review": False},
                {"type": "other", "content": "材料SUS304 不锈钢，表面喷丸处理。", "need_human_review": False},
                {"type": "heat_treatment", "content": "热处理：300℃，20min。", "need_human_review": False},
                {"type": "salt_spray", "content": "中性盐雾72小时。", "need_human_review": False},
                {"type": "other", "content": "不应导出的未确认要求", "need_human_review": True},
            ]}


def cases():
    result = []
    def add(name, edits=None, points=None, features=None, requirements=None, end_note="两端并紧并磨平，磨面角≥270°。", summary=None):
        review = base_review()
        review["drawing_summary"].update(summary or {})
        for field, updates in (edits or {}).items():
            review["spring_parameters"].setdefault(field, {}).update(updates)
        if points is not None:
            review["spring_parameters"]["load_points"] = points + review["spring_parameters"]["load_points"]
        if features:
            review["spring_features"].update(features)
        if requirements:
            review["technical_requirements"].extend(requirements)
        # Spoofed/stale cache must never be a source for outgoing metrics.
        review["design_checks"] = {"metrics": {"solid_stress": {"value": 999999}, "unit_mass": {"value": 999999, "unit": "kg", "status": "estimated"}}}
        result.append({"name": name, "review": review, "end_note": end_note})
    add("book_baseline")
    add("decimal_coils", {"total_coils": {"value": 10.5}, "active_coils": {"value": 8.25}}, summary={"drawing_name": "客户 弹簧001-A"})
    add("precise_decimal_coils", {"total_coils": {"value": 10.5123456789}, "active_coils": {"value": 8.25123456789}})
    for closed, ground, note in [
        (1, 1, "两端并紧并磨平，磨面角≥270°。"), (1, 0, "两端并紧，不磨平。"),
        (0, 1, "两端不并紧，端面磨平。"), (0, 0, "两端不并紧，不磨平。"),
    ]:
        add(f"end_binary_{closed}_{ground}", {"end_coils_closed": parameter(closed), "end_grinding": parameter(ground)}, end_note=note)
        add(f"end_legacy_{closed}_{ground}", {"end_type": parameter("两端并紧" if closed else "两端不并紧"), "end_grinding": parameter("两端磨平" if ground else "两端不磨平")}, end_note=note)
    add("end_open_explicit_angles", {"end_type": parameter("两端不并紧")}, requirements=[
        {"type": "process", "content": "两端不并紧，端面磨平，每端磨270°。", "need_human_review": False},
        {"type": "process", "content": "两端不并紧，端面磨平，每端磨300°。", "need_human_review": False},
    ], end_note="两端不并紧，端面磨平。")
    add("end_open_duplicate", {"end_type": parameter("两端不并紧")}, requirements=[
        {"type": "process", "content": "两端不并紧，端面磨平。", "need_human_review": False},
        {"type": "other", "content": "两端不并紧，端面磨平", "need_human_review": False},
    ], end_note="两端不并紧，端面磨平。")
    add("end_open_pending", {"end_coils_closed": parameter(0, need_human_review=True)}, end_note=None)
    add("end_open_grinding_pending", {"end_type": parameter("两端不并紧"), "end_grinding": parameter(1, need_human_review=True)}, end_note=None)
    add("end_open_active_pending", {"end_type": parameter("两端不并紧"), "active_coils": parameter(2, need_human_review=True)}, end_note="两端不并紧，端面磨平。")
    original_coil_notes = [
        {"type": "other", "content": "工作圈数：2 圈。", "need_human_review": False},
        {"type": "process", "content": "有效圈数：2 圈。", "need_human_review": False},
        {"type": "other", "content": "有效圈数：3 圈。", "need_human_review": False},
        {"type": "other", "content": "有效圈数：2 圈。", "application_scope": "备用弹簧", "need_human_review": False},
        {"type": "other", "content": "工作圈数：2 圈，端面去毛刺。", "need_human_review": False},
    ]
    add("end_closed_active_original", requirements=original_coil_notes)
    add("end_open_active_original", {"end_type": parameter("两端不并紧")}, requirements=original_coil_notes, end_note="两端不并紧，端面磨平。")
    add("end_open_active_legacy_text", {"end_type": parameter("两端不并紧")}, end_note="两端不并紧，端面磨平。")
    add("end_closed_active_legacy_text")
    add("end_legacy_english", {"end_type": parameter("closed_and_ground"), "end_grinding": parameter("ground")})
    add("end_string_binary", {"end_coils_closed": parameter("0"), "end_grinding": parameter("1")}, end_note="两端不并紧，端面磨平。")
    for field in ("end_type", "end_grinding", "end_coils_closed"):
        for suffix, updates in {
            "pending": {"need_human_review": True}, "invalid": {"value": "invalid"},
            "stale": {"derived_value_stale": True}, "formula_stale": {"formula_recommendation_stale": True, "source": ["human_edited"]},
            "cycle": {"source": ["formula_calculation"], "source_fields": [field]},
            "unconfirmed": {"need_human_review": None},
        }.items():
            add(f"end_{field}_{suffix}", {field: {**parameter("两端并紧" if field == "end_type" else 1), **updates}}, end_note=None)
    for field in ("end_type", "end_grinding"):
        for suffix, value in (("missing", None), ("cleared", "")):
            add(f"end_{field}_{suffix}", {field: parameter(value, source=["human_edited"])}, end_note=None)
    add("end_duplicate", requirements=[
        {"type": "process", "content": "两端并紧磨平，每端磨270°。", "need_human_review": False},
        {"type": "other", "content": "两端并紧磨平，每端磨 270°", "need_human_review": False},
    ])
    add("end_different_conditions", requirements=[
        {"type": "process", "content": "两端并紧磨平，每端磨300°。", "need_human_review": False},
        {"type": "process", "content": "两端并紧磨平，每端磨270°，去除毛刺。", "need_human_review": False},
        {"type": "process", "content": "两端并紧磨平，每端磨270°。", "application_scope": "备用弹簧", "need_human_review": False},
    ])
    add("end_legacy_text")
    add("hb_pending", {"solid_height": {"need_human_review": True}})
    add("hb_stale", {"solid_height": {"derived_value_stale": True}})
    add("hb_formula_stale", {"solid_height": {"formula_recommendation_stale": True}})
    add("hb_cleared", {"solid_height": {"value": "", "source": ["human_edited"], "value_kind": "input_height"}})
    add("hb_reference", {"solid_height": {"value": 7.4, "source": ["formula_calculation"], "value_kind": "reference_limit"}})
    add("hb_unknown", {"solid_height": {"source": ["legacy_unknown"], "value_kind": "unknown"}})
    add("hb_invalid_range", {"solid_height": {"value": 20, "source": ["manual"], "value_kind": "input_height"}})
    add("hb_manual", {"solid_height": {"value": 7, "source": ["manual"], "value_kind": "input_height"}})
    fb = {"label": "Fb", "height": 6.3, "force": 25, "need_human_review": False}
    add("fb_matching", points=[fb])
    add("fb_mismatching", points=[{**fb, "height": 7}])
    add("fb_pending", points=[{**fb, "need_human_review": True}])
    add("fb_zero", points=[{**fb, "force": 0}])
    add("fb_invalid", points=[{**fb, "force": -1}])
    add("fb_ambiguous", points=[fb, {**fb, "label": "Pb"}])
    add("fb_without_material", {"material": {"value": "未知材料"}}, points=[fb])
    add("no_material", {"material": {"value": "未知材料"}})
    add("pitch_missing", {"support_coils": {"value": ""}, "pitch": {"value": None}})
    add("invalid_wire", {"wire_diameter": {"value": "NaN"}})
    add("c_one", {"mean_diameter": {"value": 1.8}})
    add("wire_stale", {"wire_diameter": {"derived_value_stale": True}})
    add("hb_cycle", {"solid_height": {"source_fields": ["solid_height"]}})
    add("non_round", features={"wire_section": {"value": "rectangular"}})
    add("units", {"solid_height": {"value": 0.63, "unit": "cm"}}, points=[{**fb, "height": 0.63, "height_unit": "cm", "force": 0.025, "force_unit": "kN", "load_tolerance_upper": 0.0002, "load_tolerance_lower": -0.0002}])
    add("unsupported_load_unit", points=[{**fb, "force_unit": "invalid"}])
    add("roughness_symbol", requirements=[{"type": "surface_roughness", "content": "外圆表面粗糙度：Ra ≤ 3.2 μm。", "need_human_review": False}])
    add("conflicting_original", requirements=[{"type": "other", "content": "材料：65Mn。", "need_human_review": False}])
    add("material_pending", {"material": {"need_human_review": True}})
    add("material_empty", {"material": {"value": ""}})
    add("pitch_stale", {"pitch": parameter(8.15, "mm", source=["formula_calculation"], derived_value_stale=True)})
    add("pitch_invalid", {"pitch": parameter("NaN", "mm")})
    add("material_changed", {"material": {"value": "65Mn"}})
    add("wire_changed", {"wire_diameter": {"value": 2}, "material": {"value": "65Mn"}})
    for name, updates in {
        "pending": {"need_human_review": True}, "missing": {"value": None}, "empty": {"value": ""},
        "zero": {"value": 0}, "negative": {"value": -1}, "nan": {"value": "NaN"},
        "infinity": {"value": "Infinity"}, "text": {"value": "invalid"}, "boolean": {"value": True},
        "stale": {"derived_value_stale": True}, "formula_stale": {"formula_recommendation_stale": True},
        "cycle": {"source": ["formula_calculation"], "source_fields": ["surface_roughness_ra"]},
        "conflict": {"roughness_conflict": True}, "unsupported_unit": {"unit": "mm"},
        "hex": {"value": "0x10"}, "underscore": {"value": "1_2"},
        "micro_alias": {"unit": "µm"}, "ascii_alias": {"unit": "um"}, "legacy_unit": {"unit": None},
        "changed": {"value": 6.3}, "precise": {"value": 12.345678},
    }.items():
        add(f"roughness_{name}", {"surface_roughness_ra": updates})
    add("roughness_requirements", requirements=[
        {"type": "other", "content": "两端面表面粗糙度：Ra 12.5 µm。", "need_human_review": False},
        {"type": "surface_roughness", "content": "Ra 12.5 μm", "application_scope": "两端面", "need_human_review": False},
        {"type": "surface_roughness", "content": "外圆粗糙度 Ra 12.5μm", "need_human_review": False},
        {"type": "surface_roughness", "content": "两端面粗糙度 Ra 6.3μm", "need_human_review": False},
        {"type": "surface_roughness", "content": "两端面粗糙度 Ra ≤ 12.5μm", "need_human_review": False},
        {"type": "surface_roughness", "content": "两端面粗糙度 Ra 12.5μm，表面镀锌", "need_human_review": False},
        {"type": "surface_roughness", "content": "两端面粗糙度 Ra 12.5 mm", "need_human_review": False},
        {"type": "other", "content": "Ｒａ １２.５ µm", "application_scope": "两端面", "need_human_review": False},
    ])
    add("roughness_legacy_text")
    add("roughness_scoped_text", requirements=[{"type": "surface_roughness", "content": "Ra 3.2 μm", "application_scope": "外圆", "need_human_review": False}])
    matching_note = {"type": "surface_roughness", "content": "两端面粗糙度 Ra 12.5μm", "need_human_review": False, "confirmation_source": "human_confirmed"}
    add("roughness_manual_clear", {"surface_roughness_ra": {"value": "", "source": ["human_edited"]}}, requirements=[matching_note])
    add("roughness_pending_note", {"surface_roughness_ra": {"need_human_review": True}}, requirements=[matching_note])
    add("roughness_stale_note", {"surface_roughness_ra": {"derived_value_stale": True}}, requirements=[matching_note])
    add("roughness_legacy_promoted", {"surface_roughness_ra": {"value": None}}, requirements=[matching_note])
    add("roughness_legacy_scopes", {"surface_roughness_ra": {"value": None}}, requirements=[matching_note, {**matching_note, "content": "外圆粗糙度 Ra 12.5μm"}])
    add("roughness_all_missing", {"material": {"value": ""}, "surface_roughness_ra": {"value": ""}})
    add("roughness_only", {"material": {"value": ""}})
    for name, value in (
        ("drawing_no", "YD4765020178"), ("drawing_no_numeric", "00001234"),
        ("drawing_no_mixed", "00-AB/01.2"), ("drawing_no_trimmed", " \t00-A  B-01\n "),
        ("drawing_no_empty", ""), ("drawing_no_blank", " \t\n "), ("drawing_no_null", None),
        ("drawing_no_source_missing", "LIVE-REVIEW-NO"), ("drawing_no_source_snapshot", "LIVE-REVIEW-NO"),
    ):
        add(name, summary={"drawing_no": value})
    add("drawing_no_without_weight", {"material": {"value": ""}}, summary={"drawing_no": "0001"})
    add("drawing_no_only", {"material": {"value": ""}, "surface_roughness_ra": {"value": ""}}, summary={"drawing_no": "0"})
    # Optional SW fields share these expectations with the JavaScript exporter.
    def optional(name, edits, tolerances=None, perpendicularity=None, **kwargs):
        add("optional_" + name, edits, **kwargs)
        result[-1].update(expected_tolerances=tolerances, expected_perpendicularity=perpendicularity)
    for label, field, value in (("外径", "outer_diameter", 28.8), ("自由高度", "free_length", 19), ("中径", "mean_diameter", 25.2)):
        base = parameter(value, "mm", tolerance_upper=1.5, tolerance_lower=-1.5)
        optional(field, {field: base}, {label: 1.5})
        optional(field + "_zero", {field: {**base, "tolerance_upper": 0, "tolerance_lower": 0}}, {label: 0})
        optional(field + "_tiny", {field: {**base, "tolerance_upper": 0.000012345, "tolerance_lower": -0.000012345}}, {label: 0.000012345})
        for suffix, patch in (
            ("asymmetric", {"tolerance_lower": -0.5}), ("one_sided", {"tolerance_lower": None}),
            ("one_sided_zero", {"tolerance_lower": 0}), ("missing", {"tolerance_upper": None, "tolerance_lower": None}),
            ("reversed", {"tolerance_upper": -1.5, "tolerance_lower": 1.5}), ("pending", {"need_human_review": True}),
            ("unknown_confirmation", {"need_human_review": None}), ("stale", {"derived_value_stale": True}),
            ("formula_stale", {"formula_recommendation_stale": True, "source": ["manual"]}),
            ("invalid", {"tolerance_input_draft": "±bad", "tolerance_upper": None, "tolerance_lower": None}), ("boolean", {"tolerance_upper": True, "tolerance_lower": -1}),
            ("draft", {"tolerance_input_draft": "1.5/"}), ("conflict", {"tolerance_conflict": True}),
            ("unit", {"unit": "μm"}),
            ("old_confirmation", {"confirmation_snapshot": {"kind": "parameter", "value": value, "tolerance_upper": 1, "tolerance_lower": -1}}),
        ):
            optional(field + "_" + suffix, {field: {**base, **patch}})
    optional("all", {"outer_diameter": parameter(28.8,"mm",tolerance_upper=1.5,tolerance_lower=-1.5),
        "free_length": parameter(19,"mm",tolerance_upper=0.5,tolerance_lower=-0.5),
        "mean_diameter": parameter(25.2,"mm",tolerance_upper=0.2,tolerance_lower=-0.2),
        "perpendicularity": parameter(0.01,"mm")}, {"外径":1.5,"自由高度":0.5,"中径":0.2}, 0.01,
        summary={"drawing_no":"OPTIONAL-001"})
    for name, unit, value, tolerance, expected in (("cm", "cm", 2.88, 0.15, 1.5), ("m", "m", .0288, .0015, 1.5),
        ("inch", "in", 1.2, .01, .01*25.4), ("alias", "毫米", 28.8, .25, .25)):
        optional("unit_"+name,{"outer_diameter":parameter(value,unit,tolerance_upper=tolerance,tolerance_lower=-tolerance)}, {"外径":expected})
    optional("no_copy",{"inner_diameter":parameter(21.6,"mm",tolerance_upper=2,tolerance_lower=-2),"outer_diameter":parameter(28.8,"mm")})
    optional("bad_nominal",{"outer_diameter":parameter(0,"mm",tolerance_upper=1.5,tolerance_lower=-1.5)})
    optional("dependency_stale",{"outer_diameter":parameter(28.8,"mm",source=["derived"],source_fields=["pitch"],tolerance_upper=1.5,tolerance_lower=-1.5),"pitch":{"derived_value_stale":True}})
    for suffix, patch, expected in (
        ("valid",{},.01), ("zero",{"value":0},0), ("tiny",{"value":.000012345},.000012345),
        ("cm",{"value":.001,"unit":"cm"},.01), ("no_number",{"value":None},None), ("blank",{"value":" "},None),
        ("negative",{"value":-.01},None), ("boolean",{"value":True},None), ("nan",{"value":"NaN"},None),
        ("infinity",{"value":"Infinity"},None), ("hex",{"value":"0x10"},None),
        ("pending",{"need_human_review":True},None), ("stale",{"derived_value_stale":True},None),
        ("formula_stale",{"formula_recommendation_stale":True,"source":["manual"]},None),
        ("conflict",{"value_conflict":True},None), ("unit",{"unit":"degree"},None),
        ("old_confirmation",{"confirmation_snapshot":{"kind":"parameter","value":.02}},None),
    ):
        optional("perpendicularity_"+suffix,{"perpendicularity":{**parameter(.01,"mm"),**patch}}, perpendicularity=expected)
    optional("fullwidth", {"perpendicularity":parameter("１", "mm")})
    optional("snapshot_boolean", {"perpendicularity":parameter(1, "mm", confirmation_snapshot={"value":True})})
    optional("snapshot_empty_kind", {"perpendicularity":parameter(.01,"mm",confirmation_snapshot={"kind":"","value":.01})})
    optional("snapshot_null_kind", {"perpendicularity":parameter(.01,"mm",confirmation_snapshot={"kind":None,"value":.01})})
    optional("numeric_strings", {"outer_diameter":parameter("28.8","mm",tolerance_upper="1.5",tolerance_lower="-1.5"), "perpendicularity":parameter("0.01","mm")}, {"外径":1.5}, .01)
    optional("matching_snapshot", {"perpendicularity":parameter(.01,"mm",confirmation_snapshot={"kind":"parameter","value":.01,"tolerance_upper":None,"tolerance_lower":None})}, perpendicularity=.01)
    optional("unknown_fields", {"perpendicularity":parameter(.01,"mm",need_human_review=None)})
    return result


def run():
    outputs = []
    for case in cases():
        review = case["review"]
        original_review = deepcopy(review)
        package = build_generation_parameter_package(review)
        assert package["source"]["drawing_no"] == original_review["drawing_summary"].get("drawing_no")
        if case["name"] == "drawing_no_source_missing":
            del package["source"]["drawing_no"]
            package["solidworks_preview"] = build_solidworks_preview(package, review)
        if case["name"] == "drawing_no_source_snapshot":
            package["source"]["drawing_no"] = "000-FROZEN-NO"
            package["solidworks_preview"] = build_solidworks_preview(package, review)
        if case["name"] == "roughness_legacy_text":
            generation = package["generation_parameters"]
            generation["technical_requirements"] = []
            generation["technical_requirements_text"] = (
                "两端面粗糙度 Ra 12.5 µm。\n外圆粗糙度 Ra 12.5μm。\n"
                "两端面粗糙度 Ra ≤ 12.5μm。\n"
                + generation["technical_requirements_text"]
            )
            package["solidworks_preview"] = build_solidworks_preview(package, review)
        if case["name"] == "end_legacy_text":
            generation = package["generation_parameters"]
            generation["technical_requirements"] = []
            generation["technical_requirements_text"] += "\n99.两端并紧磨平，每端磨270°。\n100.两端并紧磨平，每端磨 270°。"
            package["solidworks_preview"] = build_solidworks_preview(package, review)
        if case["name"] in {"end_open_active_legacy_text", "end_closed_active_legacy_text"}:
            generation = package["generation_parameters"]
            generation["technical_requirements"] = []
            generation["technical_requirements_text"] += "\n工作圈数：2 圈。\n有效圈数：3 圈。\n工作圈数：2 圈，端面去毛刺。"
            package["solidworks_preview"] = build_solidworks_preview(package, review)
        complete_contract = all(field in package["generation_parameters"]["spring_parameters"] for field in COMPRESSION_GENERATION_INPUT_FIELDS)
        if complete_contract:
            GenerationParameterPackageV2.model_validate(package)
        preview = package["solidworks_preview"]
        assert list(preview) == ["modelParameters", *(["modelParametersTolerance"] if "modelParametersTolerance" in preview else []), "customProperties", "extraProperties", "titleBlockProperties"]
        command = build_solidworks_command("1000000099", package, review)
        model = command["models"][0]
        assert {k: model[k] for k in preview} == preview
        expected_model_keys = ["线径", "中径", "自由高度", "圈数", "有效圈数n", "是否磨平", "是否并紧"]
        if preview["modelParameters"]["是否并紧"] == 0:
            expected_model_keys.remove("有效圈数n")
        assert list(preview["modelParameters"]) == expected_model_keys, case["name"]
        assert review["spring_parameters"]["active_coils"] == original_review["spring_parameters"]["active_coils"]
        if "active_coils" in package["generation_parameters"]["spring_parameters"]:
            active = package["generation_parameters"]["spring_parameters"]["active_coils"]["value"]
            coil_text = preview["extraProperties"]["技术要求"]
            if preview["modelParameters"]["是否并紧"] != 0:
                assert f"有效圈数：{active}。" in coil_text
            elif case["name"] not in {"end_open_active_original", "end_open_active_legacy_text"}:
                assert "有效圈数：" not in coil_text and "工作圈数：" not in coil_text
        assert preview["modelParameters"]["是否并紧"] == package["generation_parameters"]["spring_parameters"].get("end_coils_closed", {}).get("value")
        extra = preview["extraProperties"]
        title = preview["titleBlockProperties"]
        assert isinstance(title, dict) and set(title) <= {"材料", "重量", "客户图号", "垂直度A", "表面粗糙度"}
        assert list(title) == [key for key in ("材料", "重量", "客户图号", "垂直度A", "表面粗糙度") if key in title]
        drawing_no = package["source"].get("drawing_no")
        if isinstance(drawing_no, str) and drawing_no.strip():
            assert title["客户图号"] == drawing_no.strip() and isinstance(title["客户图号"], str)
        else:
            assert "客户图号" not in title
        assert review["drawing_summary"] == original_review["drawing_summary"]
        if "expected_tolerances" in case:
            assert preview.get("modelParametersTolerance") == case["expected_tolerances"], (case["name"], preview)
            assert title.get("垂直度A") == case["expected_perpendicularity"], (case["name"], title)
            for field in ("outer_diameter", "free_length", "mean_diameter", "perpendicularity"):
                assert review["spring_parameters"].get(field) == original_review["spring_parameters"].get(field), (case["name"], field)

        if case["name"] == "drawing_no_without_weight":
            assert title == {"客户图号": "0001", "表面粗糙度": 12.5}
        if case["name"] == "drawing_no_only":
            assert title == {"客户图号": "0"}
        mass = package["derived_parameters"]["solidworks_design_checks"]["metrics"]["unit_mass"]
        assert mass["unit"] == "kg" and "formula" in mass and "inputs" in mass
        if "重量" in title:
            assert isinstance(title["重量"], (int, float)) and title["重量"] == round(mass["value"], 8)
        assert list(extra)[0] == "技术要求" and set(extra) <= {"技术要求", "P'", "C", "τ_b"}
        notes = extra["技术要求"]
        assert notes.startswith("1.旋向：右。\n"), (case["name"], notes)
        if case["end_note"]:
            assert notes.splitlines()[2] == "3." + case["end_note"], (case["name"], notes)
            assert notes.count(case["end_note"]) == 1, notes
        else:
            assert "磨面角≥270°" not in notes
        if case["name"] == "book_baseline" or case["name"].startswith("end_"):
            assert review["technical_requirements"] == original_review["technical_requirements"], case["name"]
        assert "每端磨270°" not in package["generation_parameters"]["technical_requirements_text"] or case["name"] in {"end_duplicate", "end_different_conditions", "end_legacy_text", "end_open_explicit_angles"}
        for index, line in enumerate(notes.splitlines(), 1):
            assert line.startswith(f"{index}."), line
        assert "不应导出的" not in notes
        assert "材料SUS304 不锈钢，表面喷丸处理。" in notes
        assert "热处理：300℃，20min。" in notes and "中性盐雾72小时。" in notes
        assert "F1 = 13.2 N（允差 ±10%）" in notes
        assert "F2 = 18.9 N（允差 +1/-0.5 N）" in notes
        assert "F3 = 0 N" in notes
        assert "材料：SUS304。" not in notes and "材料：SUS304 不锈钢。" not in notes
        assert notes.count("旋向：右。") == 1 and "绕制方向：" not in notes
        name = case["name"]
        if name in {"end_closed_active_original", "end_open_active_original", "end_open_active_legacy_text", "end_closed_active_legacy_text"}:
            assert "有效圈数：3 圈。" in notes and "工作圈数：2 圈，端面去毛刺。" in notes
            if "original" in name:
                assert "备用弹簧" in notes
            if preview["modelParameters"]["是否并紧"] == 0:
                assert notes.count("工作圈数：2 圈。") == 1, notes
                assert "有效圈数：2 圈。" not in notes, "Only equivalent original records are deduplicated; no generated row is restored"
            else:
                assert "总圈数：4，有效圈数：2。" in notes and "工作圈数：2 圈。" not in notes, notes
        if name == "end_open_explicit_angles":
            assert notes.count("每端磨270°") == 1 and notes.count("每端磨300°") == 1
        if name == "end_open_active_pending":
            readiness = assess_generation_readiness(review)
            assert readiness["status"] == "needs_confirmation", readiness
        if name == "end_open_pending":
            assert preview["modelParameters"]["是否并紧"] is None and "有效圈数n" in preview["modelParameters"]
        if name == "end_different_conditions":
            assert "每端磨300°" in notes and "去除毛刺" in notes and "备用弹簧" in notes
        if name == "book_baseline":
            assert extra == {"技术要求": notes, "P'": 2.9314, "C": 14, "τ_b": 451.2669}, extra
            assert "Hb = 6.3 mm" in notes and "Fb =" not in notes
            assert title == {"材料": "SUS304", "重量": 0.00642403, "表面粗糙度": 12.5}
        if name == "material_pending":
            assert title == {"重量": 0.00642403, "表面粗糙度": 12.5}, "Valid weight and Ra are independent of material text confirmation"
        if name == "material_empty":
            assert title == {"表面粗糙度": 12.5}
        if name in {"pitch_missing", "pitch_stale", "pitch_invalid", "invalid_wire", "wire_stale", "non_round"}:
            assert title == {"材料": "SUS304", "表面粗糙度": 12.5}, (name, title)
        if name in {"roughness_manual_clear", "roughness_pending_note", "roughness_stale_note", "roughness_legacy_scopes"}:
            assert "表面粗糙度" not in title and "两端面表面粗糙度：Ra 12.5 μm" in notes
            if name == "roughness_legacy_scopes":
                assert "外圆表面粗糙度：Ra 12.5 μm" in notes and review["spring_parameters"]["surface_roughness_ra"]["value"] is None
        elif name in {f"roughness_{suffix}" for suffix in ["pending", "missing", "empty", "zero", "negative", "nan", "infinity", "text", "boolean", "stale", "formula_stale", "cycle", "conflict", "unsupported_unit", "all_missing", "hex", "underscore"]}:
            assert "表面粗糙度" not in title and "粗糙度" not in notes, (name, title, notes)
        elif name == "drawing_no_only":
            assert "表面粗糙度" not in title and "粗糙度" not in notes
        else:
            expected_ra = review["spring_parameters"]["surface_roughness_ra"]["value"]
            assert title["表面粗糙度"] == expected_ra and not isinstance(title["表面粗糙度"], bool)
            assert f"两端面表面粗糙度：Ra {expected_ra} μm。" not in notes
        if name == "roughness_all_missing":
            assert title == {}
        if name == "roughness_only":
            assert title == {"表面粗糙度": 12.5}
        if name == "roughness_requirements":
            assert "外圆表面粗糙度：Ra 12.5 μm" in notes
            assert "两端面表面粗糙度：Ra 6.3 μm" in notes
            assert "两端面表面粗糙度：Ra ≤ 12.5 μm" in notes
            assert "Ra 12.5 μm，表面镀锌" in notes
            assert "Ra 12.5 mm" in notes and "Ｒａ" not in notes
            assert len(review["technical_requirements"]) == 13, "Only the equivalent standalone legacy record was promoted"
            assert review["spring_parameters"]["surface_roughness_ra"]["surface_location"] == "两端面"
        if name == "roughness_legacy_text":
            assert "外圆粗糙度 Ra 12.5μm" in notes and "Ra ≤ 12.5μm" in notes
            assert "两端面粗糙度 Ra 12.5 µm" not in notes
        if name == "roughness_scoped_text":
            assert "Ra 3.2 μm（作用范围：外圆）" in notes
        if name in {"hb_pending", "hb_stale", "hb_formula_stale", "hb_cleared", "hb_reference", "hb_unknown", "hb_invalid_range", "hb_cycle"}:
            assert "Hb =" not in notes, (name, notes)
        if name in {"hb_stale", "hb_formula_stale", "hb_cleared", "hb_unknown", "hb_invalid_range", "hb_cycle", "fb_invalid", "fb_ambiguous", "non_round", "c_one", "wire_stale", "no_material", "invalid_wire", "pitch_missing"}:
            assert "τ_b" not in extra, (name, extra)
        if name in {"fb_pending", "fb_invalid", "fb_ambiguous"}:
            assert "Fb =" not in notes, (name, notes)
        if name == "fb_matching":
            assert "Hb = 6.3 mm 时，对应压并载荷 Fb = 25 N" in notes
        if name == "fb_mismatching":
            assert "压并高度：Hb = 6.3 mm" in notes and "载荷测试高度 7 mm" in notes
            assert "对应压并载荷" not in notes
        if name == "fb_zero":
            assert extra["τ_b"] == 0 and "Fb = 0 N" in notes
        if name == "fb_without_material":
            assert "P'" not in extra and extra["τ_b"] > 0
        if name == "units":
            assert "Hb = 6.3 mm 时，对应压并载荷 Fb = 25 N（允差 ±0.2 N）" in notes, notes
        if name == "unsupported_load_unit":
            assert assess_generation_readiness(review)["status"] == "needs_confirmation"
            assert "Fb =" not in notes
        if name == "roughness_symbol":
            assert "外圆表面粗糙度：Ra ≤ 3.2 μm。" in notes
        if name == "conflicting_original":
            assert "材料：65Mn。" not in notes
        frozen = deepcopy(package)
        changed = deepcopy(review)
        changed["drawing_summary"]["drawing_no"] = "CHANGED-AFTER-FREEZE"
        changed["spring_parameters"]["wire_diameter"]["value"] = 8
        changed["spring_parameters"]["solid_height"]["value"] = 1
        changed["spring_parameters"]["material"]["value"] = "65Mn"
        changed["spring_parameters"]["total_coils"]["value"] = 8
        changed["spring_parameters"]["end_type"]["value"] = "两端不并紧"
        changed["spring_parameters"]["end_grinding"]["value"] = "两端不磨平"
        assert build_solidworks_command("1000000099", package, changed) == command
        assert package == frozen
        legacy_title = deepcopy(frozen)
        legacy_title["solidworks_preview"]["titleBlockProperties"].pop("客户图号", None)
        if complete_contract:
            dumped = GenerationParameterPackageV2.model_validate(legacy_title).model_dump(mode="json")
            assert "客户图号" not in dumped["solidworks_preview"]["titleBlockProperties"]
        legacy_model = build_solidworks_command("1000000099", legacy_title, changed)["models"][0]
        assert legacy_model["titleBlockProperties"] == legacy_title["solidworks_preview"]["titleBlockProperties"]
        assert "客户图号" not in legacy_model["titleBlockProperties"], "Legacy requests must not gain a drawing number"
        legacy = deepcopy(frozen)
        del legacy["solidworks_preview"]["titleBlockProperties"]
        del legacy["derived_parameters"]["solidworks_design_checks"]["metrics"]["unit_mass"]
        if complete_contract:
            dumped = GenerationParameterPackageV2.model_validate(legacy).model_dump(mode="json")
            assert "titleBlockProperties" not in dumped["solidworks_preview"]
        assert "titleBlockProperties" not in build_solidworks_command("1000000099", legacy, changed)["models"][0]
        outputs.append({"name": name, "input_review": original_review, "review": review, "package": package})
    for value in (float("nan"), float("inf"), float("-inf")):
        invalid = base_review()
        invalid["spring_parameters"]["surface_roughness_ra"]["value"] = value
        assert "表面粗糙度" not in build_generation_parameter_package(invalid)["solidworks_preview"]["titleBlockProperties"]
    baseline = outputs[0]
    for field, updates in [
        ("end_type", {"value": "两端不并紧"}), ("end_grinding", {"value": "invalid"}),
        ("end_type", {"need_human_review": True}), ("end_grinding", {"derived_value_stale": True}),
    ]:
        changed = deepcopy(baseline["review"])
        changed["spring_parameters"][field].update(updates)
        rebuilt = build_solidworks_preview(deepcopy(baseline["package"]), changed)
        assert not rebuilt["extraProperties"]["技术要求"].startswith("1.两端"), field
    old_open = deepcopy(next(item["package"] for item in outputs if item["name"] == "end_binary_0_1"))
    old_open["solidworks_preview"]["modelParameters"]["有效圈数n"] = 2
    old_open["solidworks_preview"]["extraProperties"]["技术要求"] = old_open["solidworks_preview"]["extraProperties"]["技术要求"].replace("1.两端不并紧，端面磨平。", "1.两端不并紧，端面磨平，每端磨270°。", 1)
    old_open["solidworks_preview"]["extraProperties"]["技术要求"] += "\n99.工作圈数：2 圈。"
    frozen_open = deepcopy(old_open["solidworks_preview"])
    assert {key: build_solidworks_command("1000000099", old_open, baseline["review"])["models"][0][key] for key in frozen_open} == frozen_open
    historical = deepcopy(baseline["package"])
    old_text = historical["solidworks_preview"]["extraProperties"]["技术要求"].splitlines()[1:]
    old_text = "\n".join(f"{index}.{line.split('.', 1)[1]}" for index, line in enumerate(old_text, 1)).replace("有效圈数：", "工作圈数：")
    historical["solidworks_preview"]["extraProperties"]["技术要求"] = old_text
    del historical["solidworks_preview"]["modelParameters"]["是否并紧"]
    assert "是否并紧" not in build_solidworks_command("1000000099", historical, baseline["review"])["models"][0]["modelParameters"]
    assert build_solidworks_command("1000000099", historical, baseline["review"])["models"][0]["extraProperties"]["技术要求"] == old_text, "pre-feature frozen requests must not gain the new template"
    for invalid in (float("nan"), float("inf"), -float("inf"), True, {}, []):
        changed = deepcopy(outputs[0]["review"])
        changed["spring_parameters"].update(outer_diameter=parameter(28.8,"mm",tolerance_upper=invalid,tolerance_lower=-1),perpendicularity=parameter(invalid,"mm"))
        projected = build_solidworks_preview(deepcopy(outputs[0]["package"]), changed)
        assert "modelParametersTolerance" not in projected and "垂直度A" not in projected["titleBlockProperties"]
    # Frozen requests do not acquire new properties from a newer live review.
    from ai_design_review.generation_service import stable_payload_hash
    frozen = deepcopy(outputs[0]["package"])
    live = deepcopy(outputs[0]["review"])
    live["spring_parameters"].update(outer_diameter=parameter(28.8,"mm",tolerance_upper=1.5,tolerance_lower=-1.5),perpendicularity=parameter(.01,"mm"))
    old = build_solidworks_command("1000000010",frozen,live)["models"][0]
    assert "modelParametersTolerance" not in old and "垂直度A" not in old["titleBlockProperties"]
    new = build_generation_parameter_package(live)
    assert new["solidworks_preview"]["modelParametersTolerance"] == {"外径":1.5}
    assert stable_payload_hash(frozen) != stable_payload_hash(new)
    GenerationParameterPackageV2.model_validate(new)
    return outputs


def label_cases():
    samples = json.loads((Path(__file__).parent / "fixtures/solidworks_technical_labels.json").read_text(encoding="utf-8"))
    outputs = []
    for sample in samples:
        parameters = {field: {**parameter(None), **value} if isinstance(value, dict) else parameter(value) for field, value in sample.get("parameters", {}).items()}
        if sample.get("direction"):
            parameters["handedness"] = parameter(sample["direction"])
        package = {"generation_parameters": {"spring_parameters": parameters, "technical_requirements": sample.get("requirements", []),
                    "technical_requirements_text": sample.get("legacy", ""), "load_points": []}}
        review = {"spring_parameters": deepcopy(parameters), "technical_requirements": deepcopy(sample.get("requirements", []))}
        original, original_review = deepcopy(package), deepcopy(review)
        expected = "\n".join(f"{i}.{line}" for i, line in enumerate(sample["expected"], 1))
        assert build_solidworks_technical_text(package, review) == expected, sample["name"]
        preview = build_solidworks_preview(package, review)
        assert preview["extraProperties"]["技术要求"] == expected
        assert preview["customProperties"]["旋向"] == {"left": "左旋", "right": "右旋"}.get((parameters.get("handedness") or {}).get("value"))
        assert review == original_review and package["generation_parameters"] == original["generation_parameters"]
        # Frozen pre-change requests are projections already stored, never re-cleaned.
        frozen = deepcopy(package); frozen["solidworks_preview"] = deepcopy(preview)
        old_notes = "1.两端并紧磨平，每端磨270°。\n2.材料：SUS304。\n3.绕制方向：左旋。\n4.总圈数：6 圈。\n5.有效圈数：4 圈。\n6.其他要求：原始冻结正文。"
        frozen["solidworks_preview"]["extraProperties"]["技术要求"] = old_notes
        before = deepcopy(frozen)
        assert build_solidworks_command("1000000009", frozen, review)["models"][0]["extraProperties"]["技术要求"] == old_notes
        assert frozen == before
        outputs.append({**sample, "package": original, "review": original_review, "expected_text": expected})
    return outputs


if __name__ == "__main__":
    labels = label_cases()
    result = labels if "--label-json" in sys.argv else run()
    if "--json" in sys.argv or "--label-json" in sys.argv:
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    else:
        print(f"PASS: {len(result)} SW export cases and {len(labels)} label fixtures, exact keys, notes, omission, precision, units and frozen snapshots")
