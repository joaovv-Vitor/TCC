#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Voice Form Filler — MVP do TCC
"Uso de reconhecimento de fala para preenchimento de formulários online"

Autor:  Jovi
Data:   2026-05-22

Uso:
    python main.py [URL]

Se nenhuma URL for fornecida, busca o formulário local 'test_form.html'
e, se não existir, usa o formulário padrão do httpbin.org.
"""

import os
import sys

from config import logger, DEFAULT_URL
from controller import VoiceFormFiller


def main() -> None:
    """Ponto de entrada do script."""
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
