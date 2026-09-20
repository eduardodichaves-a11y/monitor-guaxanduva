import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ARQUIVO = "dados.json"

URL_MARE = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/tabuamare.html"
)

# Região do Comasa - Joinville/SC
LAT = -26.27018
LON = -48.81041


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


def buscar_previsao():
    url = "https://api.open-meteo.com/v1/forecast"

    parametros = {
        "latitude": LAT,
        "longitude": LON,

        "current": (
            "precipitation,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "wind_gusts_10m"
        ),

        "hourly": (
            "precipitation_probability,"
            "precipitation,"
            "wind_speed_10m,"
            "wind_direction_10m,"
            "wind_gusts_10m"
        ),

        "forecast_days": 2,
        "timezone": "America/Sao_Paulo",
    }

    try:
        r = requests.get(
            url,
            params=parametros,
            timeout=30,
            headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
        )

        r.raise_for_status()
        resposta = r.json()

        atual = resposta.get("current", {})
        horario = resposta.get("hourly", {})

        tempos = horario.get("time", [])

        agora = datetime.now(
            ZoneInfo("America/Sao_Paulo")
        )

        indice = 0

        if tempos:
            alvo = agora.strftime("%Y-%m-%dT%H:00")

            if alvo in tempos:
                indice = tempos.index(alvo)

        def valor(lista):
            try:
                return lista[indice]
            except Exception:
                return None

        return {
            "status": "online",
            "fonte": "Open-Meteo",
            "modelo": "Best Match",

            "atual": {
                "horario": atual.get("time"),
                "precipitacao_mm":
                    atual.get("precipitation"),

                "vento_kmh":
                    atual.get("wind_speed_10m"),

                "direcao_graus":
                    atual.get("wind_direction_10m"),

                "rajada_kmh":
                    atual.get("wind_gusts_10m"),
            },

            "proxima_hora": {
                "horario":
                    valor(horario.get("time", [])),

                "probabilidade_chuva_pct":
                    valor(
                        horario.get(
                            "precipitation_probability",
                            [],
                        )
                    ),

                "precipitacao_mm":
                    valor(
                        horario.get(
                            "precipitation",
                            [],
                        )
                    ),

                "vento_kmh":
                    valor(
                        horario.get(
                            "wind_speed_10m",
                            [],
                        )
                    ),

                "direcao_graus":
                    valor(
                        horario.get(
                            "wind_direction_10m",
                            [],
                        )
                    ),

                "rajada_kmh":
                    valor(
                        horario.get(
                            "wind_gusts_10m",
                            [],
                        )
                    ),
            },
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte": "Open-Meteo",
            "erro": str(erro),
        }


def main():
    agora = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    )

    previsao = buscar_previsao()

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
            "teste_fonte":
                testar_fonte(URL_MARE),
            "altura_m": None,
        },

        "rio": {
            "nome": "Rio Guaxanduva",
            "status":
                "sem_sensor_publico_confirmado",
            "nivel_m": None,
        },

        "previsao": previsao,

        "granizo": {
            "status": "sem_alerta_integrado",
            "fonte":
                "Defesa Civil - integração futura",
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

    print(
        json.dumps(
            previsao,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
