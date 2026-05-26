# -*- coding: utf-8 -*-
"""
Configurações e constantes globais do Voice Form Filler.
"""

from __future__ import annotations

import logging


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
# corresponde a um campo do formulário.  0.55 = 55% de semelhança.
SIMILARITY_THRESHOLD = 0.55

# Idioma do reconhecimento de fala.
SPEECH_LANGUAGE = "pt-BR"

# Tempo máximo (segundos) que o microfone espera por uma frase.
LISTEN_TIMEOUT = 8

# Tempo máximo (segundos) de comprimento da frase.
PHRASE_TIME_LIMIT = 10

# URL padrão para testes (formulário de exemplo do httpbin).
DEFAULT_URL = "https://httpbin.org/forms/post"

# ── Configuração do motor de STT ────────────────────────────────────────

# Motor de reconhecimento de fala a ser utilizado.
# Opções: "google"  → Google Web Speech API (online, sem GPU)
#         "whisper" → OpenAI Whisper (offline, local, requer GPU p/ speed)
STT_ENGINE = "google"

# Tamanho do modelo Whisper (usado apenas quando STT_ENGINE = "whisper").
# Opções: "tiny", "base", "small", "medium", "large"
# "medium" oferece bom equilíbrio entre acurácia e velocidade em pt-BR.
# "large" oferece a melhor acurácia, mas exige mais VRAM (~10 GB).
WHISPER_MODEL_SIZE = "medium"

