# 🎙️ Voice Form Filler — MVP do TCC

> **Uso de reconhecimento de fala para preenchimento de formulários online**

## Descrição

Sistema que permite preencher formulários web usando apenas comandos de voz.
Combina **Playwright** (controle de navegador) com **SpeechRecognition** (captura
de áudio do microfone) para criar uma interface acessível de preenchimento
automático.

## Arquitetura

```
┌──────────────────┐      campo encontrado      ┌──────────────────┐
│                  │ ──────────────────────────▸ │                  │
│  MODO NAVEGAÇÃO  │                             │   MODO DITADO    │
│  (estado padrão) │ ◂────────────────────────── │                  │
└──────────────────┘  texto preenchido / cancel  └──────────────────┘
```

### Componentes

| Classe                   | Responsabilidade                                      |
|--------------------------|-------------------------------------------------------|
| `SpeechRecognizerBase`   | Interface abstrata para motores de STT (SOLID)        |
| `GoogleSpeechRecognizer` | Implementação usando Google Web Speech API             |
| `MicrophoneListener`     | Captura de áudio + calibração de ruído ambiente        |
| `DOMMapper`              | Varredura do DOM e mapeamento de campos do formulário  |
| `FieldMatcher`           | Correspondência fuzzy entre fala e nomes de campos     |
| `VoiceFormFiller`        | Controlador principal — máquina de estados + loop      |

## Pré-requisitos

- Python 3.10+
- Microfone funcional
- Dependências de sistema para compilar o PyAudio:

```bash
# No Debian/Ubuntu
sudo apt install portaudio19-dev python3-dev

# No Fedora Linux
sudo dnf install portaudio-devel python3-devel gcc-c++
```

## Instalação

```bash
# 1. Criar e ativar ambiente virtual
python3 -m venv .venv
source .venv/bin/activate

# 2. Instalar dependências Python
pip install -r requirements.txt

# 3. Instalar navegador do Playwright
playwright install chromium
```

## Uso

```bash
# Executa abrindo o formulário local de teste (test_form.html) automaticamente!
python voice_form_filler.py

# Ou especifique qualquer formulário online
python voice_form_filler.py "https://httpbin.org/forms/post"
```

### Comandos de Voz

| Comando              | Ação                                              |
|----------------------|---------------------------------------------------|
| *nome de um campo*   | Foca o campo correspondente (Modo Navegação)      |
| *texto livre*        | Preenche o campo em foco (Modo Ditado)            |
| `"cancelar"`         | Cancela o ditado e volta ao Modo Navegação        |
| `"encerrar programa"`| Fecha o navegador e finaliza a execução           |

## Extensibilidade

Para trocar o motor de reconhecimento de fala (ex: Whisper, Vosk), basta criar
uma nova classe que herde de `SpeechRecognizerBase` e implemente o método
`recognize()`:

```python
class WhisperRecognizer(SpeechRecognizerBase):
    def recognize(self, audio: sr.AudioData) -> Optional[str]:
        # Sua implementação aqui
        ...
```

## Licença

Projeto acadêmico — TCC.
# TCC
