"""Simulated model output: keep protected tokens exactly as a real model must."""
import re


def protected_reply(row, translated):
    spans = []
    for token, original in sorted(row.get("_engineering_tokens", {}).items(), key=lambda entry: len(entry[1]), reverse=True):
        canonical = original.replace("МПа", "MPa").replace("ГОСТ", "GOST").replace(",", ".")
        choices = [original, original.strip(), canonical, canonical.strip()]
        match = next((candidate for value in choices if value for candidate in re.finditer(re.escape(value), translated)
                      if not any(candidate.start() < end and candidate.end() > start for start, end, _ in spans)), None)
        if match is None:
            raise AssertionError(f"Test translation lost protected source token {original!r}")
        spans.append((*match.span(), token))
    for start, end, token in sorted(spans, reverse=True):
        translated = translated[:start] + token + translated[end:]
    return translated
