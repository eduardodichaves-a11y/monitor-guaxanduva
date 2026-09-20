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
            "User-Agent":
            "Monitor-Guaxanduva/1.0"
        },
    )

    resposta.raise_for_status()
    return resposta.text


def numero(texto):
    texto = texto.strip().replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return None


def procurar_mare_joinville(html):
    """
    Procura na tabela oficial da EPAGRI/CIRAM
    as previsões de maré referentes a Joinville.

    Como a apresentação da página pode mudar,
    o coletor é conservador: se não reconhecer
    os dados com segurança, informa indisponível
    em vez de fabricar valores.
    """

    soup = BeautifulSoup(html, "html.parser")

    texto = soup.get_text(
        "\n",
        strip=True
    )

    linhas = [
        linha.strip()
        for linha in texto.splitlines()
        if linha.strip()
    ]

    hoje = agora()

    formatos_data = [
        hoje.strftime("%d/%m/%Y"),
        hoje.strftime("%d/%m/%y"),
        hoje.strftime("%d/%m"),
    ]

    inicio = None

    for i, linha in enumerate(linhas):
        minuscula = linha.lower()

        if (
            "joinville" in minuscula
            or
