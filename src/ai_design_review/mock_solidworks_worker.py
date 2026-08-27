from __future__ import annotations

import io
import json
import math
import os
import signal
import socket
import time
from datetime import UTC, datetime
from threading import Event
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

from .technical_requirements import build_technical_requirements_text


STOP_EVENT = Event()
CAPABILITY = "mock_solidworks_compression_v1"


def _positive_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(max(value, minimum), maximum)


class MockSolidWorksWorker:
    """HTTP-only worker that exercises the future SolidWorks contract."""

    def __init__(self) -> None:
        self.base_url = str(os.getenv("MOCK_SOLIDWORKS_API_BASE_URL", "http://127.0.0.1:8770")).rstrip("/")
        self.api_key = str(os.getenv("GENERATION_WORKER_API_KEY") or "").strip()
        self.admin_api_key = str(os.getenv("GENERATION_ADMIN_API_KEY") or "").strip()
        self.delay = _positive_float("MOCK_SOLIDWORKS_DELAY_SECONDS", 0.8, minimum=0, maximum=30)
        self.poll_seconds = _positive_float("MOCK_SOLIDWORKS_POLL_SECONDS", 1, minimum=0.2, maximum=30)
        self.worker_id = f"mock-sw-{socket.gethostname()}-{os.getpid()}"
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60,
        )

    def run(self) -> None:
        if not self.api_key:
            raise RuntimeError("GENERATION_WORKER_API_KEY is required for the mock SolidWorks worker.")
        if not self.admin_api_key:
            raise RuntimeError("GENERATION_ADMIN_API_KEY is required for the mock SolidWorks worker.")
        self._enable_mock_template()
        while not STOP_EVENT.is_set():
            job = self.claim()
            if job is None:
                STOP_EVENT.wait(self.poll_seconds)
                continue
            self.process(job)

    def _enable_mock_template(self) -> None:
        while not STOP_EVENT.is_set():
            try:
                response = self.client.patch(
                    "/api/admin/generation-templates/mock/compression-spring/versions/v3/status",
                    headers={"Authorization": f"Bearer {self.admin_api_key}"},
                    json={"enabled": True},
                )
                if response.status_code == 200:
                    return
                if response.status_code == 404:
                    created = self.client.post(
                        "/api/admin/generation-templates",
                        headers={"Authorization": f"Bearer {self.admin_api_key}"},
                        json={
                            "template_code": "mock/compression-spring",
                            "version": "v3",
                            "drawing_type": "compression_spring",
                            "label": "模拟圆柱螺旋压缩弹簧（冻结协议 V1）",
                            "priority": 1002,
                            "enabled": True,
                            "is_mock": True,
                            "required_fields": [
                                "wire_diameter", "mean_diameter", "free_length", "total_coils",
                                "active_coils", "handedness", "end_grinding", "end_coils_closed",
                            ],
                            "match_rules": {},
                            "parameter_mapping": {},
                            "worker_capability": CAPABILITY,
                        },
                    )
                    if created.status_code in {200, 201, 409}:
                        continue
                    created.raise_for_status()
                response.raise_for_status()
            except httpx.HTTPError:
                STOP_EVENT.wait(self.poll_seconds)

    def claim(self) -> dict[str, Any] | None:
        response = self.client.post(
            "/api/generation-worker/jobs/claim",
            json={"worker_id": self.worker_id, "capabilities": [CAPABILITY]},
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()["generation_job"]

    def process(self, job: dict[str, Any]) -> None:
        generation_id = str(job["generation_id"])
        scenario = str((job.get("execution_options") or {}).get("mock_scenario") or "success")
        try:
            self._status(generation_id, "generating_3d", 20)
            self._wait()
            if scenario == "fail_3d":
                raise MockGenerationFailure("mock_3d_failed", "模拟三维模型生成失败。")

            self._status(generation_id, "generating_2d", 55)
            self._wait()
            if scenario == "fail_2d":
                raise MockGenerationFailure("mock_2d_failed", "模拟二维工程图生成失败。")
            if scenario == "timeout":
                self._wait(multiplier=3)
                raise MockGenerationFailure("mock_timeout", "模拟 SolidWorks 生图超时。")

            artifacts = render_mock_artifacts(job)
            self._status(generation_id, "uploading", 80)
            for artifact_type, filename, mime_type, content in artifacts:
                self._upload(generation_id, artifact_type, filename, mime_type, content)
            response = self.client.post(
                f"/api/generation-worker/jobs/{generation_id}/complete",
                json={"worker_id": self.worker_id},
            )
            response.raise_for_status()
        except MockGenerationFailure as exc:
            self._fail(generation_id, exc.code, str(exc))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                self._fail(generation_id, "mock_worker_http_error", str(exc))
        except Exception as exc:
            self._fail(generation_id, "mock_worker_error", f"{type(exc).__name__}: {exc}")

    def _status(self, generation_id: str, status: str, progress: int) -> None:
        response = self.client.patch(
            f"/api/generation-worker/jobs/{generation_id}/status",
            json={
                "worker_id": self.worker_id,
                "status": status,
                "stage": status,
                "progress": progress,
            },
        )
        response.raise_for_status()

    def _upload(self, generation_id: str, artifact_type: str, filename: str, mime_type: str, content: bytes) -> None:
        response = self.client.post(
            f"/api/generation-worker/jobs/{generation_id}/artifacts",
            data={"worker_id": self.worker_id, "artifact_type": artifact_type, "is_mock": "true"},
            files={"file": (filename, content, mime_type)},
        )
        response.raise_for_status()

    def _fail(self, generation_id: str, code: str, message: str) -> None:
        try:
            response = self.client.post(
                f"/api/generation-worker/jobs/{generation_id}/failed",
                json={"worker_id": self.worker_id, "error_code": code, "error_message": message},
            )
            if response.status_code not in {200, 409}:
                response.raise_for_status()
        except httpx.HTTPError:
            pass

    def _wait(self, *, multiplier: float = 1) -> None:
        STOP_EVENT.wait(self.delay * multiplier)


class MockGenerationFailure(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def render_mock_artifacts(job: dict[str, Any]) -> list[tuple[str, str, str, bytes]]:
    package = job.get("parameter_package") or {}
    generation_parameters = package.get("generation_parameters") or {}
    parameters = generation_parameters.get("spring_parameters") or {}
    load_points = generation_parameters.get("load_points") or []
    technical_requirements = generation_parameters.get("technical_requirements") or []
    supplied_technical_text = generation_parameters.get("technical_requirements_text")
    if isinstance(supplied_technical_text, str) and (supplied_technical_text or not technical_requirements):
        technical_requirements_text = supplied_technical_text
    else:
        technical_requirements_text = build_technical_requirements_text(technical_requirements)
    values = {
        field: item.get("value") if isinstance(item, dict) else item
        for field, item in parameters.items()
    }
    image = _drawing_image(job, values, load_points, technical_requirements, technical_requirements_text)
    png_buffer = io.BytesIO()
    image.save(png_buffer, format="PNG")
    pdf_buffer = io.BytesIO()
    image.convert("RGB").save(pdf_buffer, format="PDF", resolution=150)
    manifest = {
        "mock": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "generation_id": job.get("generation_id"),
        "template_code": job.get("template_code"),
        "template_version": job.get("template_version"),
        "parameter_hash": job.get("parameter_hash"),
        "parameters": values,
        "load_points": load_points,
        "technical_requirements": technical_requirements,
        "technical_requirements_text": technical_requirements_text,
        "notice": "This manifest represents a mock 3D model. It is not a SolidWorks file.",
    }
    log = {
        "mock": True,
        "worker": "MockSolidWorksWorker",
        "stages": ["generating_3d", "generating_2d", "uploading", "completed"],
    }
    prefix = str((package.get("source") or {}).get("drawing_no") or job.get("generation_id") or "drawing")
    prefix = "".join(char if char.isalnum() or char in "-_" else "_" for char in prefix)[:80] or "drawing"
    return [
        ("png", f"{prefix}_mock_preview.png", "image/png", png_buffer.getvalue()),
        ("pdf", f"{prefix}_mock_drawing.pdf", "application/pdf", pdf_buffer.getvalue()),
        ("model_manifest", f"{prefix}_mock_model_manifest.json", "application/json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")),
        ("log", f"{prefix}_mock_worker_log.json", "application/json", json.dumps(log, ensure_ascii=False, indent=2).encode("utf-8")),
    ]


def _drawing_image(
    job: dict[str, Any],
    values: dict[str, Any],
    load_points: list[Any],
    technical_requirements: list[Any],
    technical_requirements_text: str | None = None,
) -> Image.Image:
    width = 1600
    title_font = _load_font(25)
    body_font = _load_font(20)
    requirement_lines = _technical_requirement_lines(
        technical_requirements,
        body_font,
        max_width=width - 160,
        technical_requirements_text=technical_requirements_text,
    )
    load_point_lines = _load_point_lines(load_points)
    load_point_y = 810
    requirement_line_height = 34
    requirement_y = load_point_y + max(42, len(load_point_lines) * requirement_line_height + 42)
    parameter_hash_y = max(900, requirement_y + len(requirement_lines) * requirement_line_height + 30)
    height = max(1000, parameter_hash_y + 100)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 35, width - 35, height - 35), outline="#1f2937", width=4)
    draw.text((70, 65), "MOCK SOLIDWORKS DRAWING - NOT FOR PRODUCTION", fill="#b91c1c", font=title_font)
    draw.text((70, 105), f"Generation: {job.get('generation_id')}", fill="#111827", font=body_font)
    draw.text((70, 135), f"Template: {job.get('template_code')} @ {job.get('template_version')}", fill="#111827", font=body_font)

    wire = _number(values.get("wire_diameter"), 2)
    mean = _number(values.get("mean_diameter"), 18)
    outer = mean + wire
    free = _number(values.get("free_length"), 40)
    turns = max(_number(values.get("total_coils"), 10), 1)
    left, right = 120, 980
    center_y = 470
    amplitude = min(max(outer * 8, 80), 250)
    point_count = max(int(turns * 48), 96)
    points = []
    for index in range(point_count + 1):
        ratio = index / point_count
        x = left + (right - left) * ratio
        y = center_y + amplitude * math.sin(ratio * turns * 2 * math.pi)
        points.append((x, y))
    draw.line(points, fill="#2563eb", width=max(3, min(int(wire * 3), 16)))
    draw.line((left, center_y - amplitude - 40, left, center_y + amplitude + 40), fill="#6b7280", width=2)
    draw.line((right, center_y - amplitude - 40, right, center_y + amplitude + 40), fill="#6b7280", width=2)
    draw.text((left, center_y + amplitude + 70), f"Free length: {free:g} mm", fill="#111827", font=body_font)
    draw.text((left, center_y + amplitude + 105), f"Mean diameter: {mean:g} mm", fill="#111827", font=body_font)

    table_x, table_y = 1080, 210
    draw.rectangle((table_x - 25, table_y - 35, 1510, 820), outline="#9ca3af", width=2)
    draw.text((table_x, table_y - 15), "Confirmed parameters", fill="#111827", font=body_font)
    fields = [
        "wire_diameter", "mean_diameter", "free_length", "total_coils",
        "active_coils", "handedness", "end_grinding", "end_coils_closed",
    ]
    y = table_y + 30
    for field in fields:
        if values.get(field) in (None, ""):
            continue
        draw.text((table_x, y), f"{field}: {values[field]}", fill="#111827", font=body_font)
        y += 42
    draw.text((70, 770), "Load test points / 载荷测试点", fill="#111827", font=body_font)
    if load_point_lines:
        for line in load_point_lines:
            draw.text((70, load_point_y), line, fill="#111827", font=body_font)
            load_point_y += requirement_line_height
    else:
        draw.text((70, load_point_y), "None", fill="#4b5563", font=body_font)
    draw.text((70, requirement_y), "Technical requirements / 技术要求", fill="#111827", font=body_font)
    requirement_y += requirement_line_height
    for line in requirement_lines:
        draw.text((70, requirement_y), line, fill="#111827", font=body_font)
        requirement_y += 34
    draw.text((70, parameter_hash_y), f"Parameter hash: {job.get('parameter_hash')}", fill="#4b5563", font=body_font)
    return image


def _load_point_lines(load_points: list[Any]) -> list[str]:
    """Create a compact, complete protocol table for confirmed load points."""

    lines: list[str] = []
    for item in load_points:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        height = item.get("height") if isinstance(item.get("height"), dict) else {}
        force = item.get("force") if isinstance(item.get("force"), dict) else {}
        height_value = height.get("value")
        force_value = force.get("value")
        if not label or height_value is None or force_value is None:
            continue
        tolerance_upper = force.get("tolerance_upper")
        tolerance_lower = force.get("tolerance_lower")
        tolerance = ""
        if tolerance_upper is not None or tolerance_lower is not None:
            upper = "" if tolerance_upper is None else f"+{_number(tolerance_upper, 0):g}"
            lower = "" if tolerance_lower is None else f"{_number(tolerance_lower, 0):g}"
            tolerance = f" ({upper}/{lower} N)"
        lines.append(
            f"{label}: H={_number(height_value, 0):g} mm, F={_number(force_value, 0):g} N{tolerance}"
        )
    return lines


def _technical_requirement_lines(
    technical_requirements: list[Any],
    font: ImageFont.ImageFont,
    *,
    max_width: int,
    technical_requirements_text: str | None = None,
) -> list[str]:
    """Wrap every supplied note without truncating its content.

    SolidWorks owns the final production title-block layout.  The mock output
    deliberately grows vertically so local integration tests can prove that
    the complete ordered protocol array reached the drawing stage.
    """

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1), "white"))
    lines: list[str] = []
    text = (
        technical_requirements_text
        if isinstance(technical_requirements_text, str)
        else build_technical_requirements_text(technical_requirements)
    )
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not paragraph.strip():
            continue
        lines.extend(
            _wrap_text_line(
                measure,
                paragraph,
                font,
                max_width=max_width,
                first_prefix="",
                continuation_prefix="  ",
            )
        )
    return lines


def _wrap_text_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    *,
    max_width: int,
    first_prefix: str,
    continuation_prefix: str,
) -> list[str]:
    if not text:
        return [first_prefix.rstrip()]

    wrapped: list[str] = []
    current = first_prefix
    for character in text:
        candidate = current + character
        if current != first_prefix and draw.textlength(candidate, font=font) > max_width:
            wrapped.append(current.rstrip())
            current = continuation_prefix + character
        else:
            current = candidate
    wrapped.append(current.rstrip())
    return wrapped


def _load_font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "DejaVuSans.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stop(*_: object) -> None:
    STOP_EVENT.set()


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker = MockSolidWorksWorker()
    try:
        worker.run()
    finally:
        worker.client.close()


if __name__ == "__main__":
    main()
