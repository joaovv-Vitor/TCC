# -*- coding: utf-8 -*-
"""
Camada de Reconhecimento de Fala (Speech-to-Text).

Classes
-------
SpeechRecognizerBase
    Interface abstrata para motores de STT (SOLID — Open/Closed).
GoogleSpeechRecognizer
    Implementação usando a API gratuita do Google Web Speech.
MicrophoneListener
    Encapsula a captura de áudio do microfone.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import speech_recognition as sr

from config import logger, SPEECH_LANGUAGE, LISTEN_TIMEOUT, PHRASE_TIME_LIMIT


# ═══════════════════════════════════════════════════════════════════════
# Interface abstrata
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


# ═══════════════════════════════════════════════════════════════════════
# Implementação Google
# ═══════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════
# Implementação Whisper (OpenAI — offline/local)
# ═══════════════════════════════════════════════════════════════════════


class WhisperSpeechRecognizer(SpeechRecognizerBase):
    """Implementação usando o modelo Whisper da OpenAI (execução local).

    O Whisper roda inteiramente offline no hardware do usuário.
    Quando há GPU disponível, usa CUDA para aceleração; caso contrário,
    faz fallback para CPU (mais lento, mas funcional).

    Referência:
        https://github.com/openai/whisper
        Notebook pt-BR: piegu/language-models → Whisper_Medium_Portuguese_GPU

    Dependências extras:
        pip install openai-whisper torch

    Parâmetros
    ----------
    model_size : str
        Tamanho do modelo ('tiny', 'base', 'small', 'medium', 'large').
    language : str
        Código do idioma (ex: 'pt' para português).
    """

    def __init__(
        self,
        model_size: str = "medium",
        language: str = "pt",
    ) -> None:
        self._language = language
        self._model = None
        self._model_size = model_size

    def _ensure_model_loaded(self) -> None:
        """Carrega o modelo Whisper na primeira chamada (lazy loading)."""
        if self._model is not None:
            return

        import whisper
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(
            "🤖  Carregando Whisper '%s' no dispositivo '%s'…",
            self._model_size, device,
        )
        self._model = whisper.load_model(
            self._model_size, device=device
        )
        logger.info("✅  Modelo Whisper carregado com sucesso.")

    def recognize(self, audio: sr.AudioData) -> Optional[str]:
        """Transcreve áudio usando Whisper local.

        Converte o ``AudioData`` do SpeechRecognition para um array
        numpy float32 (formato esperado pelo Whisper) sem salvar
        arquivos temporários em disco.
        """
        try:
            import numpy as np
            import io
            import wave

            self._ensure_model_loaded()

            # Converte AudioData → WAV em memória → numpy float32
            wav_bytes = audio.get_wav_data(
                convert_rate=16000, convert_width=2
            )
            with io.BytesIO(wav_bytes) as wav_io:
                with wave.open(wav_io, "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    audio_np = np.frombuffer(frames, dtype=np.int16)

            # Normaliza int16 → float32 no range [-1.0, 1.0]
            audio_float = audio_np.astype(np.float32) / 32768.0

            # Transcreve com Whisper
            result = self._model.transcribe(
                audio_float,
                language=self._language,
                fp16=(next(self._model.parameters()).device.type == "cuda"),
            )

            text = result.get("text", "").lower().strip()
            if not text:
                logger.warning("Whisper não produziu transcrição.")
                return None

            return text

        except Exception as exc:
            logger.error("Erro no Whisper: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# Implementação Vosk (offline/local, leve, sem GPU)
# ═══════════════════════════════════════════════════════════════════════


class VoskSpeechRecognizer(SpeechRecognizerBase):
    """Implementação usando Vosk (execução local, leve, sem GPU).

    O Vosk é um motor de reconhecimento de fala offline e leve que
    roda em CPU sem dificuldade.  Ideal para máquinas sem GPU ou
    quando se quer baixa latência com consumo mínimo de recursos.

    O modelo é baixado automaticamente na primeira execução caso o
    diretório ``model_path`` não exista.

    Referência:
        https://alphacephei.com/vosk/
        Modelos: https://alphacephei.com/vosk/models

    Dependências extras:
        pip install vosk

    Parâmetros
    ----------
    model_path : str
        Caminho para o diretório do modelo Vosk descompactado.
        Se não existir, o modelo será baixado automaticamente.
    """

    # URL do modelo small pt-BR (~39 MB) — rápido e funcional.
    _MODEL_URL = (
        "https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
    )
    _MODEL_DIR_NAME = "vosk-model-small-pt-0.3"

    def __init__(self, model_path: str = "") -> None:
        self._model_path = model_path
        self._model = None

    def _ensure_model_loaded(self) -> None:
        """Carrega o modelo Vosk na primeira chamada (lazy loading)."""
        if self._model is not None:
            return

        import os
        from vosk import Model

        # Resolve caminho padrão (ao lado do script)
        if not self._model_path:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self._model_path = os.path.join(
                base_dir, self._MODEL_DIR_NAME
            )

        # Baixa o modelo se não existir
        if not os.path.isdir(self._model_path):
            self._download_model()

        logger.info(
            "🗣️  Carregando modelo Vosk de '%s'…", self._model_path
        )
        self._model = Model(self._model_path)
        logger.info("✅  Modelo Vosk carregado com sucesso.")

    def _download_model(self) -> None:
        """Baixa e descompacta o modelo Vosk automaticamente."""
        import os
        import zipfile
        import urllib.request

        base_dir = os.path.dirname(self._model_path)
        zip_path = os.path.join(base_dir, "vosk-model-pt.zip")

        logger.info(
            "📥  Baixando modelo Vosk pt-BR (~39 MB)…\n    %s",
            self._MODEL_URL,
        )
        urllib.request.urlretrieve(self._MODEL_URL, zip_path)
        logger.info("📦  Descompactando modelo…")

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(base_dir)

        os.remove(zip_path)
        logger.info("✅  Modelo Vosk extraído em '%s'.", self._model_path)

    def recognize(self, audio: sr.AudioData) -> Optional[str]:
        """Transcreve áudio usando Vosk local.

        Converte o ``AudioData`` para WAV 16kHz mono e alimenta o
        ``KaldiRecognizer`` do Vosk.
        """
        try:
            import json
            from vosk import KaldiRecognizer

            self._ensure_model_loaded()

            # Converte para WAV 16kHz, 16-bit, mono (formato Vosk)
            wav_bytes = audio.get_wav_data(
                convert_rate=16000, convert_width=2
            )

            recognizer = KaldiRecognizer(self._model, 16000)
            recognizer.SetWords(False)

            # Alimenta o áudio completo ao reconhecedor
            # Pula os 44 bytes do header WAV
            recognizer.AcceptWaveform(wav_bytes[44:])
            result = json.loads(recognizer.FinalResult())

            text = result.get("text", "").lower().strip()
            if not text:
                logger.warning("Vosk não produziu transcrição.")
                return None

            return text

        except Exception as exc:
            logger.error("Erro no Vosk: %s", exc)
            return None


# ═══════════════════════════════════════════════════════════════════════
# Listener de microfone
# ═══════════════════════════════════════════════════════════════════════


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
