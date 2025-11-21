"""Shared dataset access helpers for Semantic Kernel tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
import json
import logging

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


class SharedDataRepository:
    """Lazy loader for the canonical datasets under ``shared/``."""

    def __init__(self, shared_root: Path | None = None) -> None:
        self.shared_root = shared_root or self._discover_shared_root()
        self.datasets_dir = self.shared_root / "datasets"
        self.config_dir = self.shared_root / "config"
        self.submission_dir = self.shared_root / "submission"

        self._df_cache: Dict[str, pd.DataFrame] = {}
        self._json_cache: Dict[str, Any] = {}
        self._yaml_cache: Dict[str, Any] = {}

        logger.info("Shared data repository initialized at %s", self.shared_root)

    def load_dataframe(self, relative_path: str) -> pd.DataFrame:
        key = relative_path.replace("\\", "/")
        if key not in self._df_cache:
            path = self.datasets_dir / relative_path
            if not path.exists():
                raise FileNotFoundError(f"Dataset not found: {path}")
            self._df_cache[key] = pd.read_csv(path)
            logger.debug("Cached dataframe: %s", path)
        return self._df_cache[key].copy()

    def load_json(self, relative_path: str) -> Any:
        key = relative_path.replace("\\", "/")
        if key not in self._json_cache:
            path = self.datasets_dir / relative_path
            if not path.exists():
                raise FileNotFoundError(f"JSON dataset not found: {path}")
            with open(path, "r", encoding="utf-8") as handle:
                self._json_cache[key] = json.load(handle)
            logger.debug("Cached json: %s", path)
        return self._json_cache[key]

    def load_yaml(self, relative_path: str) -> Any:
        key = relative_path.replace("\\", "/")
        if key not in self._yaml_cache:
            path = self.datasets_dir / relative_path
            if not path.exists():
                raise FileNotFoundError(f"YAML dataset not found: {path}")
            with open(path, "r", encoding="utf-8") as handle:
                self._yaml_cache[key] = yaml.safe_load(handle)
            logger.debug("Cached yaml: %s", path)
        return self._yaml_cache[key]

    def load_submission_document(self, relative_path: str) -> str:
        doc_path = self.submission_dir / "documents" / relative_path
        if not doc_path.exists():
            raise FileNotFoundError(f"Submission document not found: {doc_path}")
        with open(doc_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def load_config(self, relative_path: str) -> Any:
        path = self.config_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with open(path, "r", encoding="utf-8") as handle:
            if path.suffix in {".yaml", ".yml"}:
                return yaml.safe_load(handle)
            return json.load(handle)

    @staticmethod
    def coerce_record(record: Dict[str, Any]) -> Dict[str, Any]:
        return {key: SharedDataRepository._coerce_value(value) for key, value in record.items()}

    @staticmethod
    def _coerce_value(value: Any) -> Any:
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:  # pragma: no cover - fallback path
                pass
        if isinstance(value, float) and pd.isna(value):
            return None
        return value

    @staticmethod
    def _discover_shared_root() -> Path:
        current = Path(__file__).resolve()
        for ancestor in current.parents:
            candidate = ancestor / "shared"
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            "Unable to locate shared/ directory. Set shared_root manually when instantiating SharedDataRepository."
        )
