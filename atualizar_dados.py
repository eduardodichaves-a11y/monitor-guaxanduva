import json
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ARQUIVO = "dados.json"

URL_MARE_CSV = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)

# Referência aproximada da região do Comasa
LAT = -26.27
LON = -48.81


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
            headers={
                "User-Agent": "Monitor-Guaxanduva/1.0"
            },
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
                "horario":
                    atual.get("time"),

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
                    valor(
                        horario.get("time", [])
                    ),

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


def buscar_mare():
    try:
        r = requests.get(
            URL_MARE_CSV,
            timeout=30,
            headers={
                "User-Agent": "Monitor-Guaxanduva/1.0"
            },
        )

        r.raise_for_status()

        # O diagnóstico confirmou ISO-8859-1.
        r.encoding = "ISO-8859-1"

        agora = datetime.now(
            ZoneInfo("America/Sao_Paulo")
        )

        data_hoje = agora.strftime("%d/%m/%Y")

        eventos = []

        for linha in r.text.splitlines():

            linha = linha.strip()

            if not linha:
                continue

            partes = linha.split(";")

            if len(partes) != 3:
                continue

            data, hora, altura = partes

            if data.strip() != data_hoje:
                continue

            try:
                altura_m = float(
                    altura.strip().replace(",", ".")
                )

                # Valida também o horário.
                datetime.strptime(
                    hora.strip(),
                    "%H:%M",
                )

            except ValueError:
                continue

            eventos.append({
                "hora": hora.strip(),
                "altura_m": altura_m,
            })

        if not eventos:
            raise ValueError(
                "Nenhum evento de maré "
                f"encontrado para {data_hoje}"
            )

        # Garante ordem cronológica.
        eventos.sort(
            key=lambda evento:
                datetime.strptime(
                    evento["hora"],
                    "%H:%M",
                )
        )

        agora_minutos = (
            agora.hour * 60
            + agora.minute
        )

        anterior = None
        proximo = None

        for evento in eventos:

            hora_evento = datetime.strptime(
                evento["hora"],
                "%H:%M",
            )

            minutos_evento = (
                hora_evento.hour * 60
                + hora_evento.minute
            )

            if minutos_evento <= agora_minutos:
                anterior = evento

            elif proximo is None:
                proximo = evento

        # IMPORTANTE:
        # Não calculamos uma altura "agora".
        # A tábua fornece extremos previstos.
        return {
            "status": "online",
            "fonte": "EPAGRI/CIRAM",
            "tipo": "tabua_de_mare_prevista",
            "local": "Joinville",
            "data": data_hoje,
            "eventos": eventos,
            "anterior": anterior,
            "proximo": proximo,
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte": "EPAGRI/CIRAM",
            "tipo": "tabua_de_mare_prevista",
            "erro": str(erro),
        }


def main():
    agora = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    )

    previsao = buscar_previsao()
    mare = buscar_mare()

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

        "mare": mare,

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

    print("MARÉ:")

    print(
        json.dumps(
            mare,
            ensure_ascii=False,
            indent=2,
        )
    )

    print("PREVISÃO:")

    print(
        json.dumps(
            previsao,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
