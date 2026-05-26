# -*- coding: utf-8 -*-
"""
Camada de Controle do Navegador (Playwright).

Classes
-------
FormField
    Dataclass que representa um campo de formulário mapeado do DOM.
DOMMapper
    Faz a varredura do DOM e cria um dicionário de campos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Page, Locator

from config import logger


# ═══════════════════════════════════════════════════════════════════════
# Modelo de dados
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FormField:
    """Representa um campo de formulário mapeado do DOM.

    Attributes
    ----------
    friendly_name : str
        Chave amigável derivada de ``<label>``, ``aria-label``,
        ``placeholder`` ou ``name``.
    locator : Locator
        Locator do Playwright que aponta para o elemento no DOM.
    tag : str
        Tag HTML do elemento ('input' ou 'textarea').
    input_type : str
        Valor do atributo ``type`` (apenas para ``<input>``).
    """

    friendly_name: str
    locator: Locator
    tag: str
    input_type: str = "text"


# ═══════════════════════════════════════════════════════════════════════
# Mapeador de DOM
# ═══════════════════════════════════════════════════════════════════════


class DOMMapper:
    """Faz a varredura do DOM e cria um dicionário de campos.

    Estratégia de extração do nome amigável (em ordem de prioridade):
        1. Texto do ``<label>`` associado via ``for``/``id``
        2. Atributo ``aria-label``
        3. Atributo ``placeholder``
        4. Atributo ``name``

    Todos os nomes são normalizados para letras minúsculas e sem
    espaços extras, permitindo comparação direta com o texto da fala.
    """

    # Tipos de <input> que fazem sentido preencher com texto.
    ALLOWED_INPUT_TYPES = {
        "text", "email", "password", "search", "tel", "url", "number",
    }

    def __init__(self, page: Page) -> None:
        self._page = page

    def _get_label_text(self, element_handle) -> Optional[str]:
        """Tenta obter o texto do <label> associado ao elemento."""
        label_text = self._page.evaluate(
            """(el) => {
                // Extrai texto limpo do label, removendo inputs
                // internos para não capturar valores digitados.
                function cleanText(label) {
                    const clone = label.cloneNode(true);
                    clone.querySelectorAll('input, textarea, select')
                         .forEach(c => c.remove());
                    return clone.textContent.trim() || null;
                }
                // 1. Tenta via atributo 'id' + <label for="id">
                if (el.id) {
                    const label = document.querySelector(
                        `label[for="${el.id}"]`
                    );
                    if (label) return cleanText(label);
                }
                // 2. Tenta via <label> ancestral
                const parent = el.closest('label');
                if (parent) return cleanText(parent);
                return null;
            }""",
            element_handle,
        )
        return label_text

    def _extract_friendly_name(self, el) -> Optional[str]:
        """Extrai o nome amigável de um elemento do DOM.

        Prioridade: label > aria-label > placeholder > name.
        Labels são priorizados pois representam o que o usuário
        *vê* na tela e, portanto, tende a *falar*.
        """
        friendly = (
            self._get_label_text(el)
            or el.get_attribute("aria-label")
            or el.get_attribute("placeholder")
            or el.get_attribute("name")
        )
        if friendly:
            return friendly.lower().strip()
        return None

    def map_fields(self) -> dict[str, FormField]:
        """Varre a página e retorna ``{nome_amigável: FormField}``.

        O dicionário resultante é a peça central do sistema: é ele que
        conecta o que o usuário *diz* ao campo que deve ser preenchido.

        Returns
        -------
        dict[str, FormField]
            Mapeamento nome_amigável → FormField.
        """
        fields: dict[str, FormField] = {}

        # Itera sobre os tipos de elemento suportados, evitando
        # duplicação de lógica entre <input> e <textarea>.
        for tag in ("input", "textarea"):
            elements = self._page.query_selector_all(tag)
            for el in elements:
                input_type = "text"
                if tag == "input":
                    input_type = (
                        el.get_attribute("type") or "text"
                    ).lower()
                    if input_type not in self.ALLOWED_INPUT_TYPES:
                        continue

                friendly = self._extract_friendly_name(el)
                if not friendly:
                    continue

                locator = self._build_locator(el)
                if locator is None:
                    continue

                if friendly in fields:
                    logger.warning(
                        "⚠️  Campo duplicado ignorado: \"%s\"",
                        friendly,
                    )
                    continue

                fields[friendly] = FormField(
                    friendly_name=friendly,
                    locator=locator,
                    tag=tag,
                    input_type=input_type,
                )

        logger.info(
            "📋  Campos mapeados (%d): %s",
            len(fields),
            ", ".join(f'"{k}"' for k in fields),
        )
        return fields

    def _build_locator(self, element_handle) -> Optional[Locator]:
        """Cria um ``Locator`` estável para o elemento.

        Prioriza ``id`` > ``name`` > seletor composto (tag + type + nth).
        """
        el_id = element_handle.get_attribute("id")
        if el_id:
            return self._page.locator(f"#{el_id}")

        name = element_handle.get_attribute("name")
        tag = element_handle.evaluate("el => el.tagName.toLowerCase()")
        if name:
            return self._page.locator(f'{tag}[name="{name}"]')

        placeholder = element_handle.get_attribute("placeholder")
        if placeholder:
            return self._page.locator(
                f'{tag}[placeholder="{placeholder}"]'
            )

        # Fallback: usa aria-label
        aria = element_handle.get_attribute("aria-label")
        if aria:
            return self._page.locator(f'{tag}[aria-label="{aria}"]')

        logger.warning(
            "⚠️  Elemento sem id/name/placeholder — ignorado."
        )
        return None
