import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ARQUIVO = "dados.json"

URL_MARE = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/tabuamare.html"
)


def testar_fonte(url):
    try:
        r = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
        )
        r.raise_for_status()

        return {
            "status": "online",
            "http": r.status_code,
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "erro": str(erro),
        }


def main():
    agora = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    )

    dados = {
        "monitor": "Monitor Guaxanduva",
        "local": "Comasa - Joinville/SC",
        "gerado_em": agora.isoformat(),

        "chuva": {
            "status": "aguardando_integracao",
            "fonte": "CEMADEN",
            "leitura_mm": None,
            "acumulado_1h_mm": None,
            "acumulado_24h_mm": None,
        },

        "mare": {
            "fonte": "EPAGRI/CIRAM",
            "teste_fonte": testar_fonte(URL_MARE),
            "altura_m": None,
        },

        "rio": {
            "nome": "Rio Guaxanduva",
            "status": "sem_sensor_publico_confirmado",
            "nivel_m": None,
        },

        "emergencia": {
            "defesa_civil": "199",
            "bombeiros": "193",
        },
    }

    with open(
        ARQUIVO,
        "w",
        encoding="utf-8",
    ) as arquivo:
        json.dump(
            dados,
            arquivo,
            ensure_ascii=False,
            indent=2,
        )

    print("dados.json criado com sucesso")


if __name__ == "__main__":
    main()
