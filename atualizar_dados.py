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

URL_RADAR_LISTA = (
    "https://sifap.defesacivil.sc.gov.br/"
    "radarsc/rest/radar/getUltimasImagens"
)

# Referência aproximada da região do Comasa.
# Não representa endereço residencial.
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

        "daily": (
            "precipitation_sum,"
            "precipitation_probability_max,"
            "wind_speed_10m_max,"
            "wind_gusts_10m_max"
        ),

        "forecast_days": 7,
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
        diario = resposta.get("daily", {})

        tempos = horario.get("time", [])

        agora = datetime.now(
            ZoneInfo("America/Sao_Paulo")
        )

        indice = None

        for i, tempo in enumerate(tempos):
            try:
                momento = datetime.fromisoformat(tempo)

                momento = momento.replace(
                    tzinfo=ZoneInfo("America/Sao_Paulo")
                )

                if momento > agora:
                    indice = i
                    break

            except Exception:
                continue

        def valor(lista):
            if indice is None:
                return None

            try:
                return lista[indice]
            except Exception:
                return None

        dias = []

        datas = diario.get("time", [])
        chuva_total = diario.get(
            "precipitation_sum", []
        )
        probabilidade = diario.get(
            "precipitation_probability_max", []
        )
        vento_max = diario.get(
            "wind_speed_10m_max", []
        )
        rajada_max = diario.get(
            "wind_gusts_10m_max", []
        )

        for i, data in enumerate(datas):

            def diario_valor(lista):
                try:
                    return lista[i]
                except Exception:
                    return None

            dias.append({
                "data": data,
                "probabilidade_chuva_pct":
                    diario_valor(probabilidade),
                "precipitacao_total_mm":
                    diario_valor(chuva_total),
                "vento_max_kmh":
                    diario_valor(vento_max),
                "rajada_max_kmh":
                    diario_valor(rajada_max),
            })

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

            "proximos_7_dias": dias,
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


def buscar_radar():
    """
    Consulta o MOSAICO / C-MAX do RadarSC.

    Nesta primeira etapa não interpreta os pixels.
    Apenas valida a integração e a atualidade dos
    sete quadros fornecidos pelo servidor oficial.
    """

    try:
        r = requests.get(
            URL_RADAR_LISTA,
            params={
                "prod": 4,
                "radar": "COMP",
                "data": "",
            },
            timeout=30,
            headers={
                "User-Agent": "Monitor-Guaxanduva/1.0"
            },
        )

        r.raise_for_status()

        imagens = r.json()

        if not isinstance(imagens, list):
            raise ValueError(
                "Resposta do radar não é uma lista."
            )

        if not imagens:
            raise ValueError(
                "Radar não retornou imagens."
            )

        # Mantemos no máximo os 7 quadros usados
        # pela própria interface RadarSC.
        imagens = imagens[-7:]

        quadros = []

        for nome in imagens:
            try:
                # O RadarSC usa no início do arquivo:
                # AAAAMMDDHHMMSS...
                data_utc = datetime.strptime(
                    nome[:14],
                    "%Y%m%d%H%M%S",
                ).replace(
                    tzinfo=ZoneInfo("UTC")
                )

                data_local = data_utc.astimezone(
                    ZoneInfo("America/Sao_Paulo")
                )

                quadros.append({
                    "arquivo": nome,
                    "horario_utc":
                        data_utc.isoformat(),
                    "horario_local":
                        data_local.isoformat(),
                })

            except Exception:
                # Não aceitamos arquivo cujo timestamp
                # não possa ser interpretado.
                continue

        if not quadros:
            raise ValueError(
                "Nenhum quadro possui timestamp válido."
            )

        ultimo = quadros[-1]

        ultimo_utc = datetime.fromisoformat(
            ultimo["horario_utc"]
        )

        agora_utc = datetime.now(
            ZoneInfo("UTC")
        )

        idade_minutos = (
            agora_utc - ultimo_utc
        ).total_seconds() / 60

        # Evita idade negativa caso exista pequena
        # diferença de relógio entre servidores.
        idade_minutos = max(
            0,
            round(idade_minutos, 1),
        )

        # Nesta fase adotamos 30 minutos como trava
        # conservadora de frescor. Poderemos ajustar
        # depois de observar o comportamento real.
        atualizado = idade_minutos <= 30

        return {
            "status":
                "online"
                if atualizado
                else "desatualizado",

            "fonte":
                "Defesa Civil de Santa Catarina - RadarSC",

            "radar": "COMP",
            "produto": "C-MAX",
            "produto_codigo": 4,

            "extent": [
                -58.0651279,
                -33.8163446,
                -46.4999942,
                -24.7653703,
            ],

            "quantidade_quadros":
                len(quadros),

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "idade_ultimo_quadro_min":
                idade_minutos,

            "dados_frescos":
                atualizado,

            "analise_movimento":
                "aguardando_proxima_etapa",
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte":
                "Defesa Civil de Santa Catarina - RadarSC",
            "radar": "COMP",
            "produto": "C-MAX",
            "produto_codigo": 4,
            "dados_frescos": False,
            "erro": str(erro),
        }


def main():
    agora = datetime.now(
        ZoneInfo("America/Sao_Paulo")
    )

    previsao = buscar_previsao()
    mare = buscar_mare()
    radar = buscar_radar()

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

        "radar": radar,

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

    print("RADAR:")
    print(
        json.dumps(
            radar,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
