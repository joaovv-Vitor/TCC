#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===========================================================================
voice_form_filler.py — MVP do TCC
"Uso de reconhecimento de fala para preenchimento de formulários online"

Autor:  Jovi
Data:   2026-05-22

Descrição
---------
Script que combina controle de navegador (Playwright – modo síncrono) com
captura de voz (SpeechRecognition) para permitir que o usuário preencha
formulários web usando apenas comandos de voz.

Arquitetura
-----------
O sistema opera como uma **máquina de estados finita** com dois estados:

    ┌──────────────────┐      campo encontrado      ┌──────────────────┐
    │                  │ ──────────────────────────▸ │                  │
    │  MODO NAVEGAÇÃO  │                             │   MODO DITADO    │
    │  (estado padrão) │ ◂────────────────────────── │                  │
    └──────────────────┘  texto preenchido / cancel  └──────────────────┘

Dependências
------------
    pip install playwright SpeechRecognition PyAudio
    playwright install chromium
===========================================================================
"""

from __future__ import annotations

import os
import sys
import enum
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

import speech_recognition as sr
from playwright.sync_api import sync_playwright, Page, Browser, Locator


# ── Configuração do logger ──────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VoiceFormFiller")


# ── Constantes ──────────────────────────────────────────────────────────

# Comando que encerra o programa em qualquer estado.
CMD_ENCERRAR = "encerrar programa"

# Comando que cancela o preenchimento no Modo Ditado.
CMD_CANCELAR = "cancelar"

# Limiar mínimo de similaridade (0–1) para considerar que a frase dita
# corresponde a um campo do formulário.  0.6 = 60% de semelhança.
SIMILARITY_THRESHOLD = 0.55

# Idioma do reconhecimento de fala.
SPEECH_LANGUAGE = "pt-BR"

# Tempo máximo (segundos) que o microfone espera por uma frase.
LISTEN_TIMEOUT = 8

# Tempo máximo (segundos) de comprimento da frase.
PHRASE_TIME_LIMIT = 10

# URL padrão para testes (formulário de exemplo do httpbin).
DEFAULT_URL = "https://httpbin.org/forms/post"


# ═══════════════════════════════════════════════════════════════════════
# 1. CAMADA DE RECONHECIMENTO DE FALA  (Speech-to-Text)
# ═══════════════════════════════════════════════════════════════════════


class SpeechRecognizerBase(ABC):
    """Interface abstrata para motores de reconhecimento de fala.

    Permite que, no futuro, a API do Google seja substituída por
    Whisper, Vosk, Azure, etc., bastando criar uma nova subclasse
    sem alterar o restante do sistema (princípio Open/Closed — SOLID).
    """

    @abstractmethod
    def recognize(self, audio: sr.AudioData) -> Optional[str]:
        """Converte áudio em texto.  Retorna ``None`` se não entender."""
        ...


class GoogleSpeechRecognizer(SpeechRecognizerBase):
    """Implementação usando a API gratuita do Google Web Speech."""

    def __init__(self, language: str = SPEECH_LANGUAGE) -> None:
        self._language = language
        self._recognizer = sr.Recognizer()

    def recognize(self, audio: sr.AudioData) -> Optional[str]:
        try:
            text: str = self._recognizer.recognize_google(
                audio, language=self._language
            )
            return text.lower().strip()
        except sr.UnknownValueError:
            logger.warning("Não foi possível entender o áudio.")
            return None
        except sr.RequestError as exc:
            logger.error("Erro de rede na API do Google: %s", exc)
            return None


class MicrophoneListener:
    """Encapsula a captura de áudio do microfone.

    Responsável por:
      • Ajustar o nível de ruído ambiente.
      • Aguardar e capturar a fala do usuário.
      • Delegar o reconhecimento para um ``SpeechRecognizerBase``.
    """

    def __init__(
        self,
        recognizer_engine: SpeechRecognizerBase,
        listen_timeout: int = LISTEN_TIMEOUT,
        phrase_time_limit: int = PHRASE_TIME_LIMIT,
    ) -> None:
        self._engine = recognizer_engine
        self._recognizer = sr.Recognizer()
        self._timeout = listen_timeout
        self._phrase_limit = phrase_time_limit

    def calibrate(self, duration: float = 1.5) -> None:
        """Calibra o reconhecedor para o ruído ambiente atual."""
        logger.info("🎙️  Calibrando microfone (%.1fs)…", duration)
        with sr.Microphone() as source:
            self._recognizer.adjust_for_ambient_noise(
                source, duration=duration
            )
        logger.info("✅  Calibração concluída.")

    def listen_once(self) -> Optional[str]:
        """Captura uma única frase do microfone.

        Returns
        -------
        str | None
            Texto reconhecido em letras minúsculas, ou ``None`` se
            nenhum áudio inteligível for captado.
        """
        try:
            with sr.Microphone() as source:
                logger.info("🎤  Aguardando fala…")
                audio = self._recognizer.listen(
                    source,
                    timeout=self._timeout,
                    phrase_time_limit=self._phrase_limit,
                )
            return self._engine.recognize(audio)

        except sr.WaitTimeoutError:
            logger.debug("Silêncio prolongado — nenhum áudio detectado.")
            return None
        except OSError as exc:
            logger.error("Erro no dispositivo de áudio: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# 2. CAMADA DE CONTROLE DO NAVEGADOR  (Playwright)
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class FormField:
    """Representa um campo de formulário mapeado do DOM.

    Attributes
    ----------
    friendly_name : str
        Chave amigável derivada de ``placeholder``, ``aria-label``,
        ``<label>`` associado ou ``name``.
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


class DOMMapper:
    """Faz a varredura do DOM e cria um dicionário de campos.

    Estratégia de extração do nome amigável (em ordem de prioridade):
        1. Atributo ``placeholder``
        2. Atributo ``aria-label``
        3. Texto do ``<label>`` associado via ``for``/``id``
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
                // 1. Tenta via atributo 'id' + <label for="id">
                if (el.id) {
                    const label = document.querySelector(
                        `label[for="${el.id}"]`
                    );
                    if (label) return label.textContent.trim();
                }
                // 2. Tenta via <label> ancestral
                const parent = el.closest('label');
                if (parent) return parent.textContent.trim();
                return null;
            }""",
            element_handle,
        )
        return label_text

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

        # ── <input> ────────────────────────────────────────────────
        inputs = self._page.query_selector_all("input")
        for el in inputs:
            input_type = (el.get_attribute("type") or "text").lower()
            if input_type not in self.ALLOWED_INPUT_TYPES:
                continue

            friendly = (
                el.get_attribute("placeholder")
                or el.get_attribute("aria-label")
                or self._get_label_text(el)
                or el.get_attribute("name")
            )
            if not friendly:
                continue

            friendly = friendly.lower().strip()
            # Gera um locator estável via seletor CSS
            locator = self._build_locator(el)
            if locator is None:
                continue

            fields[friendly] = FormField(
                friendly_name=friendly,
                locator=locator,
                tag="input",
                input_type=input_type,
            )

        # ── <textarea> ─────────────────────────────────────────────
        textareas = self._page.query_selector_all("textarea")
        for el in textareas:
            friendly = (
                el.get_attribute("placeholder")
                or el.get_attribute("aria-label")
                or self._get_label_text(el)
                or el.get_attribute("name")
            )
            if not friendly:
                continue

            friendly = friendly.lower().strip()
            locator = self._build_locator(el)
            if locator is None:
                continue

            fields[friendly] = FormField(
                friendly_name=friendly,
                locator=locator,
                tag="textarea",
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


# ═══════════════════════════════════════════════════════════════════════
# 3. MÁQUINA DE ESTADOS  (State Machine)
# ═══════════════════════════════════════════════════════════════════════


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
        """Retorna a chave mais similar à frase falada.

        Tenta primeiro correspondência por substring (ex: usuário diz
        "nome" e a chave é "nome completo"), depois fallback para
        similaridade difusa.

        Returns
        -------
        str | None
            A chave do campo mais parecida, ou ``None`` se nenhuma
            atingir o limiar mínimo.
        """
        spoken = spoken.lower().strip()

        # 1. Correspondência exata
        if spoken in self._keys:
            return spoken

        # 2. Correspondência por substring  (ex: "nome" ∈ "nome completo")
        substring_matches: list[tuple[str, float]] = []
        for key in self._keys:
            if spoken in key or key in spoken:
                # Dá mais peso a substrings mais longas
                ratio = len(min(spoken, key, key=len)) / len(
                    max(spoken, key, key=len)
                )
                substring_matches.append((key, ratio))
        if substring_matches:
            best = max(substring_matches, key=lambda x: x[1])
            if best[1] >= self._threshold:
                return best[0]

        # 3. Similaridade difusa  (Levenshtein-like via SequenceMatcher)
        best_key: Optional[str] = None
        best_ratio: float = 0.0
        for key in self._keys:
            ratio = SequenceMatcher(None, spoken, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key

        if best_ratio >= self._threshold and best_key is not None:
            logger.debug(
                "Correspondência fuzzy: '%s' → '%s' (%.0f%%)",
                spoken, best_key, best_ratio * 100,
            )
            return best_key

        return None


class VoiceFormFiller:
    """Controlador principal — orquestra microfone, navegador e estados.

    Esta classe implementa o **loop principal** do sistema e gerencia
    as transições entre Modo Navegação e Modo Ditado.
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        headless: bool = False,
    ) -> None:
        self._url = url
        self._headless = headless

        # Componentes (injetados via composição)
        self._speech_engine = GoogleSpeechRecognizer()
        self._mic = MicrophoneListener(self._speech_engine)

        # Estado da máquina
        self._state = AppState.NAVIGATION
        self._focused_field: Optional[FormField] = None
        self._fields: dict[str, FormField] = {}
        self._matcher: Optional[FieldMatcher] = None

        # Playwright — inicializados em ``start()``
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None

    # ── Ciclo de vida ──────────────────────────────────────────────

    def start(self) -> None:
        """Inicializa navegador, mapeia campos e entra no loop."""
        logger.info("🚀  Iniciando VoiceFormFiller…")

        # 1. Iniciar Playwright e abrir a página
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless
        )
        self._page = self._browser.new_page()
        self._page.goto(self._url, wait_until="domcontentloaded")
        logger.info("🌐  Página carregada: %s", self._url)

        # 2. Mapear campos do formulário
        mapper = DOMMapper(self._page)
        self._fields = mapper.map_fields()

        if not self._fields:
            logger.error("❌  Nenhum campo de formulário encontrado!")
            self._shutdown()
            return

        self._matcher = FieldMatcher(list(self._fields.keys()))

        # 3. Calibrar microfone
        self._mic.calibrate()

        # 4. Entrar no loop de interação
        logger.info("=" * 60)
        logger.info("   SISTEMA PRONTO — FALE O NOME DE UM CAMPO")
        logger.info("   Diga '%s' para sair.", CMD_ENCERRAR)
        logger.info("=" * 60)
        self._main_loop()

    def _shutdown(self) -> None:
        """Fecha navegador e libera recursos do Playwright."""
        logger.info("🛑  Encerrando…")
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("👋  Programa finalizado.")

    # ── Loop principal ─────────────────────────────────────────────

    def _main_loop(self) -> None:
        """Loop contínuo que alterna entre navegação e ditado.

        A cada iteração:
          1. Captura uma frase via microfone.
          2. Verifica se é o comando de encerramento.
          3. Delega o processamento ao handler do estado atual.
        """
        try:
            while True:
                text = self._mic.listen_once()

                if text is None:
                    # Silêncio ou áudio ininteligível — volta ao topo.
                    continue

                logger.info("💬  Reconhecido: \"%s\"", text)

                # Comando global de encerramento
                if CMD_ENCERRAR in text:
                    break

                # Despacha para o handler do estado atual
                if self._state == AppState.NAVIGATION:
                    self._handle_navigation(text)
                elif self._state == AppState.DICTATION:
                    self._handle_dictation(text)

        except KeyboardInterrupt:
            logger.info("⚡  Interrupção pelo teclado (Ctrl+C).")
        finally:
            self._shutdown()

    # ── Handlers de estado ─────────────────────────────────────────

    def _handle_navigation(self, spoken_text: str) -> None:
        """Modo Navegação: tenta encontrar um campo correspondente.

        Se encontrar, foca o campo no navegador e transita para
        Modo Ditado.  Caso contrário, exibe um aviso e continua
        no Modo Navegação.
        """
        assert self._matcher is not None
        matched_key = self._matcher.find_best_match(spoken_text)

        if matched_key is None:
            logger.info(
                "❓  Nenhum campo correspondente a \"%s\".", spoken_text
            )
            logger.info(
                "    Campos disponíveis: %s",
                ", ".join(f'"{k}"' for k in self._fields),
            )
            return

        form_field = self._fields[matched_key]
        logger.info(
            "✅  Campo encontrado: \"%s\" → focando…", matched_key
        )

        # Foca o campo no navegador
        form_field.locator.focus()

        # Feedback sonoro simulado no terminal
        print("\n🔊  BEEP — Campo em foco. Dite o conteúdo.\n")

        # Transição de estado
        self._focused_field = form_field
        self._state = AppState.DICTATION
        logger.info("🔄  Estado → MODO DITADO")

    def _handle_dictation(self, spoken_text: str) -> None:
        """Modo Ditado: preenche o campo focado ou cancela.

        Se o usuário disser "cancelar", retorna ao Modo Navegação
        sem preencher.  Caso contrário, insere o texto no campo.
        """
        assert self._focused_field is not None

        if CMD_CANCELAR in spoken_text:
            logger.info("🚫  Ditado cancelado pelo usuário.")
            self._clear_focus()
            return

        # Preenche o campo com o texto reconhecido
        field = self._focused_field
        logger.info(
            "✏️  Preenchendo \"%s\" com: \"%s\"",
            field.friendly_name, spoken_text,
        )
        field.locator.fill(spoken_text)

        print(
            f"✅  Campo \"{field.friendly_name}\" "
            f"preenchido com \"{spoken_text}\"\n"
        )

        # Volta ao Modo Navegação
        self._clear_focus()

    def _clear_focus(self) -> None:
        """Limpa o foco e retorna ao Modo Navegação."""
        # Remove o foco do campo no navegador (foca o body)
        if self._page:
            self._page.evaluate("document.activeElement.blur()")
        self._focused_field = None
        self._state = AppState.NAVIGATION
        logger.info("🔄  Estado → MODO NAVEGAÇÃO")


# ═══════════════════════════════════════════════════════════════════════
# 4. PONTO DE ENTRADA
# ═══════════════════════════════════════════════════════════════════════


def main() -> None:
    """Ponto de entrada do script.

    Uso:
        python voice_form_filler.py [URL]

    Se nenhuma URL for fornecida, busca o formulário local 'test_form.html'
    e, se não existir, usa o formulário padrão do httpbin.org.
    """
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        # Tenta localizar o formulário HTML de teste local
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_html = os.path.join(script_dir, "test_form.html")
        if os.path.exists(local_html):
            url = f"file://{local_html}"
            logger.info("🏠  Identificado formulário de teste local: %s", url)
        else:
            url = DEFAULT_URL

    app = VoiceFormFiller(url=url, headless=False)
    app.start()


if __name__ == "__main__":
    main()
