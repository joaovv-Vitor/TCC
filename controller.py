# -*- coding: utf-8 -*-
"""
Controlador principal — orquestra microfone, navegador e estados.

Classe
------
VoiceFormFiller
    Implementa o loop principal e gerencia as transições entre
    Modo Navegação e Modo Ditado.
"""

from __future__ import annotations

from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser

from config import (
    logger, CMD_ENCERRAR, CMD_CANCELAR, DEFAULT_URL,
    STT_ENGINE, WHISPER_MODEL_SIZE,
)
from speech import (
    GoogleSpeechRecognizer, WhisperSpeechRecognizer, MicrophoneListener,
)
from browser import DOMMapper, FormField
from matcher import AppState, FieldMatcher


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
        # Seleciona o motor de STT com base na configuração.
        if STT_ENGINE == "whisper":
            logger.info("🔧  Motor de STT: Whisper (%s)", WHISPER_MODEL_SIZE)
            self._speech_engine = WhisperSpeechRecognizer(
                model_size=WHISPER_MODEL_SIZE,
            )
        else:
            logger.info("🔧  Motor de STT: Google Web Speech API")
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
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass  # Ignora erros de conexão ao fechar
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        logger.info("👋  Programa finalizado.")

    # ── Loop principal ─────────────────────────────────────────────

    def _main_loop(self) -> None:
        """Loop contínuo que alterna entre navegação e ditado."""
        try:
            while True:
                text = self._mic.listen_once()

                if text is None:
                    continue

                logger.info("💬  Reconhecido: \"%s\"", text)

                # Comando global de encerramento (comparação exata
                # para evitar falsos positivos em frases longas).
                if text.strip() == CMD_ENCERRAR:
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
        """Modo Navegação: tenta encontrar um campo correspondente."""
        if self._matcher is None:
            logger.error("❌  FieldMatcher não inicializado.")
            return

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

        # Feedback visual no navegador — destaca o campo focado
        self._page.evaluate("""() => {
            if (!document.getElementById('vff-highlight-style')) {
                const s = document.createElement('style');
                s.id = 'vff-highlight-style';
                s.textContent = `
                    .vff-focused {
                        outline: 3px solid #6366f1 !important;
                        outline-offset: 3px;
                        box-shadow: 0 0 0 6px rgba(99,102,241,0.25) !important;
                        animation: vff-pulse 1.5s ease-in-out infinite;
                    }
                    @keyframes vff-pulse {
                        0%,100% { box-shadow: 0 0 0 6px rgba(99,102,241,0.25); }
                        50%     { box-shadow: 0 0 0 10px rgba(99,102,241,0.1); }
                    }
                    .vff-status {
                        position: fixed; top: 0; left: 0; right: 0;
                        padding: 10px 20px;
                        background: linear-gradient(135deg,#6366f1,#a855f7);
                        color: #fff; font-family: system-ui, sans-serif;
                        font-size: 14px; font-weight: 600;
                        text-align: center; z-index: 99999;
                        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                    }
                `;
                document.head.appendChild(s);
            }
            document.querySelectorAll('.vff-focused')
                    .forEach(el => el.classList.remove('vff-focused'));
            document.activeElement.classList.add('vff-focused');
        }""")

        # Barra de status no topo do navegador
        self._page.evaluate(
            """(name) => {
                let bar = document.getElementById('vff-status-bar');
                if (!bar) {
                    bar = document.createElement('div');
                    bar.id = 'vff-status-bar';
                    bar.className = 'vff-status';
                    document.body.prepend(bar);
                }
                bar.textContent = '🎤 Modo Ditado — Fale o conteúdo para: "'
                                  + name + '"';
                bar.style.display = 'block';
            }""",
            matched_key,
        )

        print("\n🔊  BEEP — Campo em foco. Dite o conteúdo.\n")

        # Transição de estado
        self._focused_field = form_field
        self._state = AppState.DICTATION
        logger.info("🔄  Estado → MODO DITADO")

    def _handle_dictation(self, spoken_text: str) -> None:
        """Modo Ditado: preenche o campo focado ou cancela."""
        if self._focused_field is None:
            logger.error("❌  Nenhum campo focado — retornando.")
            self._clear_focus()
            return

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
        """Limpa o foco, remove destaques visuais e retorna ao Modo Navegação."""
        if self._page:
            self._page.evaluate("""() => {
                document.querySelectorAll('.vff-focused')
                        .forEach(el => el.classList.remove('vff-focused'));
                const bar = document.getElementById('vff-status-bar');
                if (bar) bar.style.display = 'none';
                document.activeElement.blur();
            }""")
        self._focused_field = None
        self._state = AppState.NAVIGATION
        logger.info("🔄  Estado → MODO NAVEGAÇÃO")
