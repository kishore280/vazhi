import logging
from copy import deepcopy
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_PRESET_ID = "general"

CHUNK_PRESETS: dict[str, dict[str, str]] = {
    "general": {
        "label": "General",
        "description": "Splits by delimiter and length. Good default for most plain documents.",
    },
    "qa": {
        "label": "QA",
        "description": "Extracts question-answer pairs. Good for FAQs and Q&A documents.",
    },
    "book": {
        "label": "Book",
        "description": "Detects chapter/heading structure and merges along it. Good for manuals and long structured documents.",
    },
    "semantic": {
        "label": "Semantic",
        "description": "Structural Markdown-aware splitting with an embedding-cluster fallback for oversized paragraphs.",
    },
    "separator": {
        "label": "Separator",
        "description": "Strict delimiter splitting. Only splits further inside oversized sections.",
    },
}

CHUNK_PRESET_IDS = set(CHUNK_PRESETS)

CHUNK_ENGINE_VERSION = "ragflow_like_v1"
GENERAL_INTERNAL_PARSER_ID = "naive"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def normalize_chunk_preset_id(value: str | None) -> str:
    if not value:
        return DEFAULT_CHUNK_PRESET_ID

    normalized = str(value).strip().lower()
    if normalized == GENERAL_INTERNAL_PARSER_ID:
        return DEFAULT_CHUNK_PRESET_ID

    if normalized in CHUNK_PRESET_IDS:
        return normalized

    logger.warning(f"Unknown chunk preset id '{value}', fallback to general")
    return DEFAULT_CHUNK_PRESET_ID


def map_to_internal_parser_id(preset_id: str) -> str:
    normalized = normalize_chunk_preset_id(preset_id)
    if normalized == DEFAULT_CHUNK_PRESET_ID:
        return GENERAL_INTERNAL_PARSER_ID
    return normalized


def get_default_chunk_parser_config(preset_id: str) -> dict[str, Any]:
    normalize_chunk_preset_id(preset_id)
    return {}


def ensure_chunk_defaults_in_additional_params(additional_params: dict[str, Any] | None) -> dict[str, Any]:
    params = dict(additional_params or {})
    params["chunk_preset_id"] = normalize_chunk_preset_id(params.get("chunk_preset_id"))

    if "chunk_parser_config" in params and not isinstance(params.get("chunk_parser_config"), dict):
        logger.warning("Invalid chunk_parser_config in additional_params, fallback to empty dict")
        params["chunk_parser_config"] = {}

    return params


def resolve_chunk_processing_params(
    kb_additional_params: dict[str, Any] | None,
    file_processing_params: dict[str, Any] | None,
    request_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    kb_additional = ensure_chunk_defaults_in_additional_params(kb_additional_params)
    file_params = dict(file_processing_params or {})
    request = dict(request_params or {})

    preset_id = normalize_chunk_preset_id(
        request.get("chunk_preset_id") or file_params.get("chunk_preset_id") or kb_additional.get("chunk_preset_id")
    )

    parser_config = get_default_chunk_parser_config(preset_id)

    kb_parser_config = kb_additional.get("chunk_parser_config")
    if isinstance(kb_parser_config, dict):
        parser_config = deep_merge(parser_config, kb_parser_config)

    file_parser_config = file_params.get("chunk_parser_config")
    if isinstance(file_parser_config, dict):
        parser_config = deep_merge(parser_config, file_parser_config)

    req_parser_config = request.get("chunk_parser_config")
    if isinstance(req_parser_config, dict):
        parser_config = deep_merge(parser_config, req_parser_config)

    return {
        "chunk_preset_id": preset_id,
        "chunk_parser_config": parser_config,
        "chunk_engine_version": CHUNK_ENGINE_VERSION,
    }


def get_chunk_preset_options() -> list[dict[str, str]]:
    return [
        {"value": preset_id, "label": preset["label"], "description": preset["description"]}
        for preset_id, preset in CHUNK_PRESETS.items()
    ]
