from __future__ import annotations

import base64
import importlib
import importlib.util
import os
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Protocol

from .base import RecognitionEngine
from .ocr_adapter import ocr_payload_to_candidates
from ..io_utils import project_path, write_json
from ..preprocessing import IMAGE_EXTENSIONS, render_pdf_with_pdftoppm


SUPPORTED_OCR_PROVIDERS = {"auto", "baidu_ocr", "baidu_paddleocr_vl", "rapidocr"}
DEFAULT_OCR_PROVIDER = "auto"


class OcrProviderError(RuntimeError):
    """Raised when the requested OCR provider chain cannot produce text."""

    def __init__(
        self,
        message: str,
        diagnostics: dict[str, Any],
        diagnostics_path: Path | None = None,
    ):
        super().__init__(message)
        self.diagnostics = diagnostics
        self.diagnostics_path = diagnostics_path


class OcrProvider(Protocol):
    name: str

    def recognize(
        self,
        image_paths: list[Path],
        provider_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return page dictionaries containing normalized text blocks."""


class BaiduOcrProvider:
    """Baidu high-accuracy OCR with location information."""

    name = "baidu_ocr"
    token_endpoint = "https://aip.baidubce.com/oauth/2.0/token"
    ocr_endpoint = "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate"

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        timeout_seconds: float = 45,
        max_attempts: int = 2,
    ):
        self.api_key = api_key or os.getenv("BAIDU_OCR_API_KEY")
        self.secret_key = secret_key or os.getenv("BAIDU_OCR_SECRET_KEY")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self._access_token: str | None = None

    def recognize(
        self,
        image_paths: list[Path],
        provider_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not _is_configured_credential(self.api_key) or not _is_configured_credential(self.secret_key):
            raise RuntimeError(
                "Baidu OCR credentials are not configured. Set BAIDU_OCR_API_KEY and "
                "BAIDU_OCR_SECRET_KEY."
            )

        import httpx

        provider_diagnostics["endpoint"] = self.ocr_endpoint
        provider_diagnostics["pages"] = []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            token_started = time.monotonic()
            token = self._get_access_token(client)
            provider_diagnostics["authentication"] = {
                "status": "success",
                "duration_ms": _elapsed_ms(token_started),
            }

            pages: list[dict[str, Any]] = []
            for page_number, image_path in enumerate(image_paths, start=1):
                page_diag: dict[str, Any] = {
                    "page": page_number,
                    "image_path": str(image_path),
                    "attempts": [],
                }
                provider_diagnostics["pages"].append(page_diag)
                payload = self._recognize_page(client, token, image_path, page_diag)
                blocks = baidu_result_to_text_blocks(payload, page_number)
                page_diag["status"] = "success"
                page_diag["text_block_count"] = len(blocks)
                pages.append(
                    {
                        "page": page_number,
                        "image_path": str(image_path),
                        "texts": blocks,
                        "raw": payload,
                    }
                )
            return pages

    def _get_access_token(self, client: Any) -> str:
        if self._access_token:
            return self._access_token
        response = client.post(
            self.token_endpoint,
            params={
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.secret_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            error = payload.get("error_description") or payload.get("error") or "missing access_token"
            raise RuntimeError(f"Baidu OCR authentication failed: {error}")
        self._access_token = str(token)
        return self._access_token

    def _recognize_page(
        self,
        client: Any,
        token: str,
        image_path: Path,
        page_diag: dict[str, Any],
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        last_error: Exception | None = None
        for attempt_number in range(1, self.max_attempts + 1):
            started = time.monotonic()
            attempt: dict[str, Any] = {
                "attempt": attempt_number,
                "stage": "request",
                "status": "running",
            }
            page_diag["attempts"].append(attempt)
            try:
                response = client.post(
                    self.ocr_endpoint,
                    params={"access_token": token},
                    data={
                        "image": encoded,
                        "probability": "true",
                        "detect_direction": "true",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                attempt["http_status"] = response.status_code
                response.raise_for_status()
                payload = response.json()
                if payload.get("error_code") is not None:
                    attempt["error_code"] = payload.get("error_code")
                    raise RuntimeError(
                        f"Baidu OCR error {payload.get('error_code')}: "
                        f"{payload.get('error_msg', 'unknown error')}"
                    )
                attempt["status"] = "success"
                attempt["duration_ms"] = _elapsed_ms(started)
                return payload
            except Exception as exc:
                last_error = exc
                attempt["status"] = "failed"
                attempt["duration_ms"] = _elapsed_ms(started)
                attempt["exception_type"] = type(exc).__name__
                attempt["exception_message"] = _safe_error(exc)
                if attempt_number < self.max_attempts:
                    time.sleep(min(1.5, 0.4 * attempt_number))
        raise RuntimeError(f"Baidu OCR failed after {self.max_attempts} attempts: {_safe_error(last_error)}")


class BaiduPaddleOcrVlProvider(BaiduOcrProvider):
    """Baidu asynchronous PaddleOCR-VL document parser."""

    name = "baidu_paddleocr_vl"
    input_mode = "document"
    submit_endpoint = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task"
    query_endpoint = "https://aip.baidubce.com/rest/2.0/brain/online/v2/paddle-vl-parser/task/query"

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        timeout_seconds: float = 45,
        task_timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ):
        super().__init__(api_key, secret_key, timeout_seconds=timeout_seconds)
        self.task_timeout_seconds = task_timeout_seconds or float(
            os.getenv("BAIDU_DOC_PARSER_TIMEOUT_SECONDS", "240")
        )
        self.poll_interval_seconds = poll_interval_seconds or float(
            os.getenv("BAIDU_DOC_PARSER_POLL_SECONDS", "5")
        )

    def recognize(
        self,
        document_paths: list[Path],
        provider_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not _is_configured_credential(self.api_key) or not _is_configured_credential(self.secret_key):
            raise RuntimeError(
                "Baidu OCR credentials are not configured. Set BAIDU_OCR_API_KEY and "
                "BAIDU_OCR_SECRET_KEY."
            )
        if len(document_paths) != 1:
            raise RuntimeError("Baidu PaddleOCR-VL expects exactly one PDF or image document")

        import httpx

        document_path = document_paths[0]
        _validate_baidu_document(document_path)
        provider_diagnostics.update(
            {
                "submit_endpoint": self.submit_endpoint,
                "query_endpoint": self.query_endpoint,
                "document_path": str(document_path),
                "polls": [],
            }
        )

        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            token_started = time.monotonic()
            token = self._get_access_token(client)
            provider_diagnostics["authentication"] = {
                "status": "success",
                "duration_ms": _elapsed_ms(token_started),
            }
            task_id = self._submit_document(client, token, document_path, provider_diagnostics)
            provider_diagnostics["task_id"] = task_id
            parse_result = self._wait_for_result(client, token, task_id, provider_diagnostics)

        pages = baidu_paddleocr_vl_result_to_pages(parse_result, document_path)
        if not pages:
            raise RuntimeError("Baidu PaddleOCR-VL returned no parsed pages")
        provider_diagnostics["page_count"] = len(pages)
        return pages

    def _submit_document(
        self,
        client: Any,
        token: str,
        document_path: Path,
        provider_diagnostics: dict[str, Any],
    ) -> str:
        started = time.monotonic()
        encoded = base64.b64encode(document_path.read_bytes()).decode("ascii")
        response = client.post(
            self.submit_endpoint,
            params={"access_token": token},
            data={
                "file_data": encoded,
                "file_name": document_path.name,
                "return_span_boxes": "true",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        provider_diagnostics["submit"] = {
            "http_status": response.status_code,
            "duration_ms": _elapsed_ms(started),
        }
        response.raise_for_status()
        payload = response.json()
        _raise_baidu_api_error(payload, "PaddleOCR-VL task submission")
        task_id = (payload.get("result") or {}).get("task_id")
        if not task_id:
            raise RuntimeError("Baidu PaddleOCR-VL task submission returned no task_id")
        return str(task_id)

    def _wait_for_result(
        self,
        client: Any,
        token: str,
        task_id: str,
        provider_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = time.monotonic() + self.task_timeout_seconds
        while True:
            started = time.monotonic()
            response = client.post(
                self.query_endpoint,
                params={"access_token": token},
                data={"task_id": task_id},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            poll_diag: dict[str, Any] = {
                "http_status": response.status_code,
                "duration_ms": _elapsed_ms(started),
            }
            provider_diagnostics["polls"].append(poll_diag)
            response.raise_for_status()
            payload = response.json()
            _raise_baidu_api_error(payload, "PaddleOCR-VL task query")
            result = payload.get("result") or {}
            status = str(result.get("status") or "").lower()
            poll_diag["status"] = status or "unknown"

            if status == "success":
                parse_result_url = result.get("parse_result_url")
                if not parse_result_url:
                    raise RuntimeError("Baidu PaddleOCR-VL task succeeded without parse_result_url")
                download_started = time.monotonic()
                parse_response = client.get(str(parse_result_url))
                provider_diagnostics["result_download"] = {
                    "http_status": parse_response.status_code,
                    "duration_ms": _elapsed_ms(download_started),
                }
                parse_response.raise_for_status()
                return parse_response.json()
            if status == "failed":
                task_error = result.get("task_error") or "unknown task error"
                raise RuntimeError(f"Baidu PaddleOCR-VL task failed: {task_error}")
            if status not in {"pending", "processing", "running"}:
                raise RuntimeError(f"Baidu PaddleOCR-VL returned unexpected task status: {status or 'empty'}")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Baidu PaddleOCR-VL task did not finish within {self.task_timeout_seconds:g} seconds"
                )
            time.sleep(self.poll_interval_seconds)


class RapidOcrProvider:
    """Local OCR backed by RapidOCR and ONNX Runtime."""

    name = "rapidocr"

    def __init__(self, engine_factory: Any | None = None):
        self.engine_factory = engine_factory

    def recognize(
        self,
        image_paths: list[Path],
        provider_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        factory = self.engine_factory
        if factory is None:
            try:
                from rapidocr import RapidOCR
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "RapidOCR is not installed. Install `rapidocr` and `onnxruntime`."
                ) from exc
            factory = RapidOCR

        started = time.monotonic()
        engine = factory()
        provider_diagnostics["create_engine_duration_ms"] = _elapsed_ms(started)
        provider_diagnostics["pages"] = []

        pages: list[dict[str, Any]] = []
        for page_number, image_path in enumerate(image_paths, start=1):
            page_started = time.monotonic()
            page_diag: dict[str, Any] = {
                "page": page_number,
                "image_path": str(image_path),
                "status": "running",
            }
            provider_diagnostics["pages"].append(page_diag)
            try:
                raw = engine(str(image_path))
                blocks = rapidocr_result_to_text_blocks(raw, page_number)
                page_diag["status"] = "success"
                page_diag["duration_ms"] = _elapsed_ms(page_started)
                page_diag["text_block_count"] = len(blocks)
                pages.append(
                    {
                        "page": page_number,
                        "image_path": str(image_path),
                        "texts": blocks,
                        "raw": _jsonable(raw),
                    }
                )
            except Exception as exc:
                page_diag["status"] = "failed"
                page_diag["duration_ms"] = _elapsed_ms(page_started)
                page_diag["exception_type"] = type(exc).__name__
                page_diag["exception_message"] = _safe_error(exc)
                raise
        return pages


class UnifiedOcrEngine(RecognitionEngine):
    """Route PDF/image OCR through a cloud provider with a local fallback."""

    name = "ocr"

    def __init__(
        self,
        provider: str | None = None,
        work_dir: str | Path | None = None,
        diagnostics_path: str | Path | None = None,
        dpi: int = 220,
        max_image_side: int = 8000,
        providers: dict[str, OcrProvider] | None = None,
    ):
        self.provider = normalize_ocr_provider(provider or os.getenv("OCR_PROVIDER", DEFAULT_OCR_PROVIDER))
        self.work_dir = Path(work_dir) if work_dir else None
        self.diagnostics_path = Path(diagnostics_path) if diagnostics_path else None
        self.dpi = dpi
        self.max_image_side = max_image_side
        self.providers: dict[str, OcrProvider] = providers or {
            "baidu_ocr": BaiduOcrProvider(),
            "baidu_paddleocr_vl": BaiduPaddleOcrVlProvider(),
            "rapidocr": RapidOcrProvider(),
        }

    def extract(self, file_path: str | Path) -> list[dict[str, Any]]:
        return self.extract_with_raw(file_path)["candidates"]

    def extract_with_raw(self, file_path: str | Path) -> dict[str, Any]:
        path = Path(file_path)
        diagnostics: dict[str, Any] = {
            "engine": self.name,
            "requested_provider": self.provider,
            "selected_provider": None,
            "status": "running",
            "file_path": str(path),
            "providers": [],
            "fallback_reasons": [],
        }
        started = time.monotonic()
        try:
            diagnostics["stage"] = "validate_input"
            self._validate_input(path)
        except Exception as exc:
            _record_failure(diagnostics, exc)
            diagnostics["duration_ms"] = _elapsed_ms(started)
            self._write_diagnostics(diagnostics)
            raise OcrProviderError(
                f"OCR input preparation failed: {type(exc).__name__}: {_safe_error(exc)}",
                diagnostics,
                self.diagnostics_path,
            ) from exc

        image_paths: list[Path] | None = None
        for provider_name in self._provider_sequence():
            provider_diag: dict[str, Any] = {
                "provider": provider_name,
                "status": "running",
            }
            diagnostics["providers"].append(provider_diag)
            provider_started = time.monotonic()
            try:
                provider = self.providers[provider_name]
                input_mode = str(getattr(provider, "input_mode", "images"))
                provider_diag["input_mode"] = input_mode
                if input_mode == "document":
                    provider_inputs = [path]
                    provider_diag["input_paths"] = [str(path)]
                else:
                    if image_paths is None:
                        diagnostics["stage"] = "prepare_images"
                        image_paths = self._prepare_images(path)
                        diagnostics["image_paths"] = [str(item) for item in image_paths]
                    provider_inputs = image_paths
                    provider_diag["input_paths"] = [str(item) for item in image_paths]
                raw_pages = provider.recognize(provider_inputs, provider_diag)
                texts = [block for page in raw_pages for block in page.get("texts", [])]
                if not texts:
                    raise RuntimeError(f"{provider_name} returned no text blocks")

                provider_diag["status"] = "success"
                provider_diag["duration_ms"] = _elapsed_ms(provider_started)
                provider_diag["text_block_count"] = len(texts)
                diagnostics["status"] = "success"
                diagnostics["stage"] = "complete"
                diagnostics["selected_provider"] = provider_name
                diagnostics["text_block_count"] = len(texts)
                diagnostics["page_count"] = len(raw_pages)
                diagnostics["duration_ms"] = _elapsed_ms(started)

                payload = {
                    "engine": provider_name,
                    "provider": provider_name,
                    "requested_provider": self.provider,
                    "texts": texts,
                    "raw_pages": raw_pages,
                }
                payload["candidates"] = ocr_payload_to_candidates(payload)
                diagnostics["candidate_count"] = len(payload["candidates"])
                self._write_diagnostics(diagnostics)
                payload["diagnostics"] = _public_diagnostics(diagnostics, self.diagnostics_path)
                payload["warnings"] = [
                    f"OCR automatically fell back to {provider_name}: {reason}"
                    for reason in diagnostics["fallback_reasons"]
                ]
                return payload
            except Exception as exc:
                provider_diag["status"] = "failed"
                provider_diag["duration_ms"] = _elapsed_ms(provider_started)
                provider_diag["exception_type"] = type(exc).__name__
                provider_diag["exception_message"] = _safe_error(exc)
                provider_diag["traceback_tail"] = traceback.format_exception(
                    type(exc), exc, exc.__traceback__
                )[-12:]
                diagnostics["fallback_reasons"].append(
                    f"{provider_name} failed: {type(exc).__name__}: {_safe_error(exc)}"
                )
                diagnostics["status"] = "retrying"
                self._write_diagnostics(diagnostics)

        diagnostics["status"] = "failed"
        diagnostics["stage"] = "recognize"
        diagnostics["duration_ms"] = _elapsed_ms(started)
        self._write_diagnostics(diagnostics)
        attempted = ", ".join(item["provider"] for item in diagnostics["providers"])
        raise OcrProviderError(
            f"OCR failed with providers [{attempted}]; see diagnostics for details",
            diagnostics,
            self.diagnostics_path,
        )

    def _provider_sequence(self) -> list[str]:
        if self.provider == "auto":
            return ["baidu_ocr", "rapidocr"]
        return [self.provider]

    def _prepare_images(self, file_path: Path) -> list[Path]:
        suffix = file_path.suffix.lower()
        work_dir = self.work_dir or project_path(
            "outputs", "ocr_pages", f"{file_path.stem}_{uuid.uuid4().hex[:8]}"
        )
        raw_dir = work_dir / "rendered"
        normalized_dir = work_dir / "normalized"
        raw_dir.mkdir(parents=True, exist_ok=True)
        normalized_dir.mkdir(parents=True, exist_ok=True)

        if suffix == ".pdf":
            raw_paths = [
                Path(item)
                for item in render_pdf_with_pdftoppm(
                    file_path,
                    raw_dir,
                    prefix="page",
                    dpi=self.dpi,
                )
            ]
        elif suffix in IMAGE_EXTENSIONS:
            raw_paths = [file_path]
        else:
            raise RuntimeError(f"OCR only supports PDF or image input: {suffix}")

        return _normalize_images(raw_paths, normalized_dir, self.max_image_side)

    @staticmethod
    def _validate_input(file_path: Path) -> None:
        if not file_path.exists():
            raise FileNotFoundError(file_path)
        suffix = file_path.suffix.lower()
        if suffix != ".pdf" and suffix not in IMAGE_EXTENSIONS:
            raise RuntimeError(f"OCR only supports PDF or image input: {suffix}")

    def _write_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        if self.diagnostics_path:
            write_json(self.diagnostics_path, diagnostics)


def normalize_ocr_provider(provider: str) -> str:
    normalized = str(provider or DEFAULT_OCR_PROVIDER).strip().lower()
    aliases = {
        "baidu": "baidu_ocr",
        "baidu_vl": "baidu_paddleocr_vl",
        "paddleocr_vl": "baidu_paddleocr_vl",
        "paddle_vl": "baidu_paddleocr_vl",
        "rapid": "rapidocr",
        "paddleocr": "auto",
        "paddle": "auto",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_OCR_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_OCR_PROVIDERS))
        raise ValueError(f"Unsupported OCR provider '{provider}'. Expected one of: {supported}")
    return normalized


def ocr_runtime_status() -> dict[str, Any]:
    api_key = _is_configured_credential(os.getenv("BAIDU_OCR_API_KEY"))
    secret_key = _is_configured_credential(os.getenv("BAIDU_OCR_SECRET_KEY"))
    has_rapidocr = importlib.util.find_spec("rapidocr") is not None
    has_onnxruntime = importlib.util.find_spec("onnxruntime") is not None
    rapid_status = "missing_runtime"
    rapid_detail = None
    if has_rapidocr and has_onnxruntime:
        try:
            importlib.import_module("onnxruntime")
            importlib.import_module("rapidocr")
            rapid_status = "ready"
        except Exception as exc:
            rapid_status = "runtime_error"
            rapid_detail = f"{type(exc).__name__}: {_safe_error(exc)}"
    configured_default = os.getenv("OCR_PROVIDER", DEFAULT_OCR_PROVIDER)
    try:
        default_provider = normalize_ocr_provider(configured_default)
    except ValueError:
        default_provider = DEFAULT_OCR_PROVIDER
    return {
        "default_provider": default_provider,
        "supported_providers": sorted(SUPPORTED_OCR_PROVIDERS),
        "baidu_ocr": {
            "status": "ready" if api_key and secret_key else "missing_credentials",
        },
        "baidu_paddleocr_vl": {
            "status": "ready" if api_key and secret_key else "missing_credentials",
            "mode": "explicit_only",
        },
        "rapidocr": {
            "status": rapid_status,
            "rapidocr_package": has_rapidocr,
            "onnxruntime_package": has_onnxruntime,
            **({"detail": rapid_detail} if rapid_detail else {}),
        },
    }


def baidu_result_to_text_blocks(payload: dict[str, Any], page_number: int) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in payload.get("words_result", []) or []:
        text = str(item.get("words", "")).strip()
        if not text:
            continue
        probability = item.get("probability") or {}
        confidence = probability.get("average", item.get("probability", 0.78))
        location = item.get("location") or {}
        blocks.append(
            {
                "text": text,
                "source": "baidu_ocr",
                "confidence": _confidence(confidence, 0.78),
                "page": page_number,
                "position": _position_from_location(location),
                "suggested_region": "Baidu OCR text line",
            }
        )
    return blocks


def baidu_paddleocr_vl_result_to_pages(
    payload: dict[str, Any],
    document_path: Path,
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for index, page in enumerate(payload.get("pages", []) or [], start=1):
        try:
            page_number = int(page.get("page_num", index - 1)) + 1
        except (TypeError, ValueError):
            page_number = index
        blocks = _baidu_paddleocr_vl_page_blocks(page, page_number)
        pages.append(
            {
                "page": page_number,
                "image_path": str(document_path),
                "texts": blocks,
                "raw": page,
            }
        )
    return pages


def _baidu_paddleocr_vl_page_blocks(
    page: dict[str, Any],
    page_number: int,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for layout in page.get("layouts", []) or []:
        layout_type = str(layout.get("type") or "text")
        span_boxes = layout.get("span_boxes") or []
        span_count = 0
        for span in span_boxes:
            text = _text_value(span.get("text"))
            if not text:
                continue
            span_count += 1
            blocks.append(
                _baidu_paddleocr_vl_block(
                    text,
                    page_number,
                    span.get("location"),
                    f"PaddleOCR-VL {layout_type} line",
                    0.86,
                )
            )
        text = _text_value(layout.get("text"))
        if text and not span_count:
            blocks.append(
                _baidu_paddleocr_vl_block(
                    text,
                    page_number,
                    layout.get("position"),
                    f"PaddleOCR-VL {layout_type}",
                    0.84,
                    polygon=layout.get("polygon"),
                )
            )

    for table in page.get("tables", []) or []:
        table_position = table.get("position")
        for cell in table.get("cells", []) or []:
            text = _text_value(cell.get("text"))
            if text:
                blocks.append(
                    _baidu_paddleocr_vl_block(
                        text,
                        page_number,
                        cell.get("position") or table_position,
                        "PaddleOCR-VL table cell",
                        0.82,
                    )
                )

    if not blocks:
        text = _text_value(page.get("text"))
        if text:
            blocks.append(
                _baidu_paddleocr_vl_block(
                    text,
                    page_number,
                    None,
                    "PaddleOCR-VL page text",
                    0.78,
                )
            )
    return _deduplicate_text_blocks(blocks)


def _baidu_paddleocr_vl_block(
    text: str,
    page_number: int,
    location: Any,
    suggested_region: str,
    confidence: float,
    polygon: Any = None,
) -> dict[str, Any]:
    return {
        "text": text,
        "source": "baidu_paddleocr_vl",
        "confidence": confidence,
        "page": page_number,
        "position": _position_from_xywh(location, polygon),
        "suggested_region": suggested_region,
    }


def rapidocr_result_to_text_blocks(raw: Any, page_number: int) -> list[dict[str, Any]]:
    boxes = getattr(raw, "boxes", None)
    texts = getattr(raw, "txts", None)
    scores = getattr(raw, "scores", None)
    if texts is not None:
        return _blocks_from_parallel_values(boxes, texts, scores, page_number)

    result = raw
    if isinstance(result, tuple) and len(result) >= 1:
        result = result[0]
    if result is None:
        return []
    if not isinstance(result, list):
        return []

    blocks: list[dict[str, Any]] = []
    for item in result:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        polygon, text, score = item[0], item[1], item[2]
        if not str(text).strip():
            continue
        blocks.append(
            {
                "text": str(text).strip(),
                "source": "rapidocr",
                "confidence": _confidence(score, 0.72),
                "page": page_number,
                "position": _position_from_polygon(polygon),
                "suggested_region": "RapidOCR text line",
            }
        )
    return blocks


def _blocks_from_parallel_values(
    boxes: Any,
    texts: Any,
    scores: Any,
    page_number: int,
) -> list[dict[str, Any]]:
    boxes = _as_list(boxes)
    texts = _as_list(texts)
    scores = _as_list(scores)
    blocks = []
    for index, text in enumerate(texts):
        if not str(text).strip():
            continue
        polygon = boxes[index] if index < len(boxes) else None
        score = scores[index] if index < len(scores) else 0.72
        blocks.append(
            {
                "text": str(text).strip(),
                "source": "rapidocr",
                "confidence": _confidence(score, 0.72),
                "page": page_number,
                "position": _position_from_polygon(polygon),
                "suggested_region": "RapidOCR text line",
            }
        )
    return blocks


def _normalize_images(raw_paths: list[Path], output_dir: Path, max_side: int) -> list[Path]:
    from PIL import Image, ImageOps, ImageSequence

    normalized: list[Path] = []
    page_number = 0
    for raw_path in raw_paths:
        with Image.open(raw_path) as source:
            frames = ImageSequence.Iterator(source) if getattr(source, "n_frames", 1) > 1 else [source]
            for frame in frames:
                page_number += 1
                image = ImageOps.exif_transpose(frame.copy()).convert("RGB")
                if max(image.size) > max_side:
                    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                target = output_dir / f"page-{page_number:04d}.png"
                image.save(target, format="PNG", optimize=True)
                while target.stat().st_size > 9_000_000 and max(image.size) > 1600:
                    resized = (
                        max(1, int(image.width * 0.85)),
                        max(1, int(image.height * 0.85)),
                    )
                    image = image.resize(resized, Image.Resampling.LANCZOS)
                    image.save(target, format="PNG", optimize=True)
                normalized.append(target)
    if not normalized:
        raise RuntimeError("OCR input produced no pages")
    return normalized


def _position_from_location(location: dict[str, Any]) -> dict[str, Any] | None:
    try:
        left = float(location["left"])
        top = float(location["top"])
        width = float(location["width"])
        height = float(location["height"])
    except (KeyError, TypeError, ValueError):
        return None
    polygon = [
        [left, top],
        [left + width, top],
        [left + width, top + height],
        [left, top + height],
    ]
    return {
        "coordinate_type": "pixel",
        "x": left + width / 2,
        "y": top + height / 2,
        "width": width,
        "height": height,
        "polygon": polygon,
    }


def _position_from_xywh(location: Any, polygon: Any = None) -> dict[str, Any] | None:
    values = _as_list(location)
    if len(values) >= 4:
        try:
            left, top, width, height = (float(values[index]) for index in range(4))
        except (TypeError, ValueError):
            pass
        else:
            points = _polygon_points(polygon) or [
                [left, top],
                [left + width, top],
                [left + width, top + height],
                [left, top + height],
            ]
            return {
                "coordinate_type": "pixel",
                "x": left + width / 2,
                "y": top + height / 2,
                "width": width,
                "height": height,
                "polygon": points,
            }
    return _position_from_polygon(polygon)


def _position_from_polygon(polygon: Any) -> dict[str, Any] | None:
    points = _polygon_points(polygon)
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "coordinate_type": "pixel",
        "x": sum(xs) / len(xs),
        "y": sum(ys) / len(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
        "polygon": points,
    }


def _polygon_points(polygon: Any) -> list[list[float]]:
    polygon = _as_list(polygon)
    points = []
    for item in polygon:
        values = _as_list(item)
        if len(values) < 2:
            continue
        try:
            points.append([float(values[0]), float(values[1])])
        except (TypeError, ValueError):
            continue
    return points


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, tuple):
        value = list(value)
    return value if isinstance(value, list) else []


def _text_value(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value if item is not None).strip()
    return str(value or "").strip()


def _deduplicate_text_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for block in blocks:
        position = block.get("position") or {}
        key = (
            block.get("page"),
            block.get("text"),
            round(float(position.get("x", -1)), 2),
            round(float(position.get("y", -1)), 2),
        )
        if key not in seen:
            seen.add(key)
            unique.append(block)
    return unique


def _confidence(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _jsonable(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    if hasattr(value, "to_json"):
        candidate = value.to_json()
        return _jsonable(candidate)
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return _jsonable(vars(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _record_failure(target: dict[str, Any], exc: Exception) -> None:
    target["status"] = "failed"
    target["exception_type"] = type(exc).__name__
    target["exception_message"] = _safe_error(exc)
    target["traceback_tail"] = traceback.format_exception(type(exc), exc, exc.__traceback__)[-12:]


def _raise_baidu_api_error(payload: dict[str, Any], operation: str) -> None:
    error_code = payload.get("error_code")
    if error_code in (None, 0, "0"):
        return
    error_message = payload.get("error_msg") or "unknown error"
    raise RuntimeError(f"Baidu {operation} error {error_code}: {error_message}")


def _validate_baidu_document(path: Path) -> None:
    suffix = path.suffix.lower()
    supported = {
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tif",
        ".tiff",
        ".ofd",
        ".doc",
        ".docx",
        ".txt",
        ".wps",
        ".ppt",
        ".pptx",
    }
    if suffix not in supported:
        raise RuntimeError(f"Baidu PaddleOCR-VL does not support file type: {suffix}")
    size = path.stat().st_size
    image_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    if suffix in image_suffixes and size > 10_000_000:
        raise RuntimeError("Baidu PaddleOCR-VL image input must not exceed 10 MB")
    if suffix in {".pdf", ".ofd"} and size > 100_000_000:
        raise RuntimeError("Baidu PaddleOCR-VL PDF/OFD input must not exceed 100 MB")
    if suffix not in image_suffixes | {".pdf", ".ofd"} and size > 50_000_000:
        raise RuntimeError("Baidu PaddleOCR-VL flowing document input must not exceed 50 MB")


def _public_diagnostics(diagnostics: dict[str, Any], path: Path | None) -> dict[str, Any]:
    return {
        "status": diagnostics.get("status"),
        "requested_provider": diagnostics.get("requested_provider"),
        "selected_provider": diagnostics.get("selected_provider"),
        "page_count": diagnostics.get("page_count", 0),
        "text_block_count": diagnostics.get("text_block_count", 0),
        "candidate_count": diagnostics.get("candidate_count", 0),
        "fallback_count": len(diagnostics.get("fallback_reasons", [])),
        "diagnostics_path": str(path) if path else None,
    }


def _safe_error(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"
    message = " ".join(str(exc).splitlines()).strip()
    if len(message) > 320:
        return message[:317] + "..."
    return message or type(exc).__name__


def _is_configured_credential(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized) and not normalized.startswith("replace-with-")


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
