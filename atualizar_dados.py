import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


FUSO = ZoneInfo("America/Sao_Paulo")

URL_MARE = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/tabuamare.html"
)

ARQUIVO_SAIDA = "dados.json"


def agora():
    return datetime.now(FUSO)


def baixar_pagina(url):
    resposta = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0 Monitor-Guaxanduva/1.0"
        },
    )

    resposta.raise_for_status()
    return resposta.text


def converter_numero(texto):
    try:
        return float(
            texto.strip().replace(",", ".")
        )
    except (ValueError, AttributeError):
        return None


def coletar_mare():
    """
    Busca a página oficial da EPAGRI/CIRAM.

    O programa somente publica valores que
    conseguir identificar na fonte.

    Se a estrutura da página mudar, retorna
    indisponível em vez de inventar informação.
    """

    try:
        html = baixar_pagina(URL_MARE)

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        texto = soup.get_text(
            "\n",
            strip=True
        )

        linhas = [
            linha.strip()
            for linha in texto.splitlines()
            if linha.strip()
        ]

        # Localiza a área referente a Joinville.
        posicao_joinville = None

        for indice, linha in enumerate(linhas):
            linha_minuscula = linha.lower()

            if (
                "joinville" in linha_minuscula
                or "babitonga" in linha_minuscula
            ):
                posicao_joinville = indice
                break

        if posicao_joinville is None:
            return {
                "status": "indisponivel",
                "fonte": "EPAGRI/CIRAM",
                "tipo": "mare_astronomica_prevista",
                "local": "Joinville / Baía da Babitonga",
                "eventos": [],
                "proxima": None,
                "motivo": (
                    "Joinville não foi localizada "
                    "na página oficial."
                ),
            }

        # Trabalha apenas com uma região limitada
        # da página depois de encontrar Joinville.
        trecho = linhas[
            posicao_joinville:
            posicao_joinville + 300
        ]

        padrao_data = re.compile(
            r"\b\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})\b"
        )

        padrao_hora = re.compile(
            r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b"
        )

        padrao_altura = re.compile(
            r"(?<!\d)(-?\d+[,.]\d+)\s*(?:m\b)?",
            re.IGNORECASE,
        )

        eventos = []
        data_atual = None

        for indice, linha in enumerate(trecho):

            data_encontrada = padrao_data.search(
