# -*- coding: utf-8 -*-
"""
Máquina de Estados e Correspondência Fuzzy.

Classes
-------
AppState
    Enum com os estados possíveis do sistema.
FieldMatcher
    Compara a frase dita com as chaves do dicionário de campos.
"""

from __future__ import annotations

import enum
from difflib import SequenceMatcher
from typing import Optional

from config import logger, SIMILARITY_THRESHOLD


class AppState(enum.Enum):
    """Estados possíveis do sistema."""

    NAVIGATION = "NAVEGAÇÃO"
    DICTATION = "DITADO"


class FieldMatcher:
    """Compara a frase dita com as chaves do dicionário de campos.

    Usa ``SequenceMatcher`` (difflib) para encontrar a melhor
    correspondência fuzzy, tolerando variações de pronúncia e
    pequenos erros de reconhecimento.
    """

    def __init__(
        self,
        field_keys: list[str],
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> None:
        self._keys = field_keys
        self._threshold = threshold

    def find_best_match(self, spoken: str) -> Optional[str]:
        """Retorna a chave mais similar à frase falada."""
        spoken = spoken.lower().strip()

        # 1. Correspondência exata
        if spoken in self._keys:
            logger.info("🎯  Match exato: '%s' (100%%)", spoken)
            return spoken

        # 2. Correspondência por substring
        substring_matches: list[tuple[str, float]] = []
        for key in self._keys:
            if spoken in key or key in spoken:
                ratio = len(min(spoken, key, key=len)) / len(
                    max(spoken, key, key=len)
                )
                substring_matches.append((key, ratio))
        if substring_matches:
            best = max(substring_matches, key=lambda x: x[1])
            if best[1] >= self._threshold:
                logger.info(
                    "🔗  Match por substring: '%s' → '%s' (%.0f%%)",
                    spoken, best[0], best[1] * 100,
                )
                return best[0]

        # 3. Similaridade difusa (SequenceMatcher)
        best_key: Optional[str] = None
        best_ratio: float = 0.0
        for key in self._keys:
            ratio = SequenceMatcher(None, spoken, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key

        if best_ratio >= self._threshold and best_key is not None:
            logger.info(
                "🔍  Match fuzzy: '%s' → '%s' (%.0f%%)",
                spoken, best_key, best_ratio * 100,
            )
            return best_key

        logger.debug(
            "Sem match para '%s' (melhor: '%s' = %.0f%%, limiar: %.0f%%)",
            spoken, best_key, best_ratio * 100, self._threshold * 100,
        )
        return None
