import json
import hashlib
import io
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3
from PIL import Image


ARQUIVO = "dados.json"

LAT = -26.27
LON = -48.81

URL_MARE_CSV = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)

URL_RADAR_SITE = (
    "https://sifap.defesacivil.sc.gov.br/radarsc/"
)

URL_RADAR_BASE = URL_RADAR_SITE + "rest/radar/"

URL_RADAR_LISTA = (
    URL_RADAR_BASE + "getUltimasImagens"
)

URL_RADAR_IMAGEM = (
    URL_RADAR_BASE + "getImagem"
)

URL_RADAR_LEGENDA = (
    URL_RADAR_SITE + "img/legenda.png"
)

RADAR_EXTENT = [
    -58.0651279,
    -33.8163446,
    -46.4999942,
    -24.7653703,
]

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


def requisicao_radar(url, params=None):
    resposta = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "Monitor-Guaxanduva/1.0"
        },
        verify=False,
    )
    resposta.raise_for_status()
    return resposta


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

        agora = datetime.now(
            ZoneInfo("America/Sao_Paulo")
        )

        indice = None

        for i, tempo in enumerate(
            horario.get("time", [])
        ):
            try:
                momento = datetime.fromisoformat(
                    tempo
                ).replace(
                    tzinfo=ZoneInfo(
                        "America/Sao_Paulo"
                    )
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

        for i, data in enumerate(datas):
            def dv(nome):
                try:
                    return diario.get(
                        nome, []
                    )[i]
                except Exception:
                    return None

            dias.append({
                "data": data,
                "probabilidade_chuva_pct":
                    dv(
                        "precipitation_probability_max"
                    ),
                "precipitacao_total_mm":
                    dv("precipitation_sum"),
                "vento_max_kmh":
                    dv("wind_speed_10m_max"),
                "rajada_max_kmh":
                    dv("wind_gusts_10m_max"),
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
                    atual.get(
                        "wind_direction_10m"
                    ),
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
            partes = linha.strip().split(";")

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
                    hora.strip(), "%H:%M"
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
            key=lambda e:
                datetime.strptime(
                    e["hora"], "%H:%M"
                )
        )

        agora_minutos = (
            agora.hour * 60 + agora.minute
        )

        anterior = None
        proximo = None

        for evento in eventos:
            h = datetime.strptime(
                evento["hora"], "%H:%M"
            )

            minutos = h.hour * 60 + h.minute

            if minutos <= agora_minutos:
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


def coordenada_para_pixel(
    longitude,
    latitude,
    largura,
    altura,
):
    oeste, sul, leste, norte = RADAR_EXTENT

    x = round(
        (longitude - oeste)
        / (leste - oeste)
        * (largura - 1)
    )

    y = round(
        (norte - latitude)
        / (norte - sul)
        * (altura - 1)
    )

    x = max(0, min(largura - 1, x))
    y = max(0, min(altura - 1, y))

    return x, y


def analisar_png(conteudo):
    imagem = Image.open(
        io.BytesIO(conteudo)
    )

    formato = imagem.format
    modo_original = imagem.mode
    largura, altura = imagem.size

    rgba = imagem.convert("RGBA")
    pixels = list(rgba.getdata())

    transparentes = sum(
        1 for p in pixels if p[3] == 0
    )

    semitransparentes = sum(
        1
        for p in pixels
        if 0 < p[3] < 255
    )

    visiveis = [
        p for p in pixels if p[3] > 0
    ]

    contador = Counter(visiveis)

    cores = []

    for cor, quantidade in contador.most_common(
        30
    ):
        cores.append({
            "rgba": list(cor),
            "pixels": quantidade,
        })

    x, y = coordenada_para_pixel(
        LON,
        LAT,
        largura,
        altura,
    )

    pixel_central = rgba.getpixel((x, y))

    raio = 5
    janela = []

    for py in range(
        max(0, y - raio),
        min(altura, y + raio + 1),
    ):
        for px in range(
            max(0, x - raio),
            min(largura, x + raio + 1),
        ):
            janela.append(
                rgba.getpixel((px, py))
            )

    janela_visivel = [
        p for p in janela if p[3] > 0
    ]

    contador_janela = Counter(
        janela_visivel
    )

    cores_janela = [
        {
            "rgba": list(cor),
            "pixels": qtd,
        }
        for cor, qtd
        in contador_janela.most_common(10)
    ]

    total = largura * altura

    return {
        "formato": formato,
        "modo_original": modo_original,
        "largura_px": largura,
        "altura_px": altura,
        "total_pixels": total,
        "pixels_transparentes":
            transparentes,
        "pixels_semitransparentes":
            semitransparentes,
        "pixels_visiveis":
            len(visiveis),
        "percentual_visivel":
            round(
                len(visiveis)
                / total
                * 100,
                4,
            ),
        "cores_visiveis_distintas":
            len(contador),
        "cores_mais_frequentes":
            cores,

        "comasa": {
            "longitude_aproximada": LON,
            "latitude_aproximada": LAT,
            "pixel_x": x,
            "pixel_y": y,
            "pixel_rgba":
                list(pixel_central),
            "janela_px": "11x11",
            "pixels_visiveis_janela":
                len(janela_visivel),
            "cores_visiveis_janela":
                len(contador_janela),
            "cores_mais_frequentes_janela":
                cores_janela,
        },
    }


def analisar_legenda():
    """
    Baixa a legenda oficial usada pela
    própria interface RadarSC e extrai
    informações objetivas da imagem.

    Nesta etapa NÃO atribuímos valores dBZ
    automaticamente às cores.
    """
    try:
        r = requisicao_radar(
            URL_RADAR_LEGENDA
        )

        conteudo = r.content

        imagem = Image.open(
            io.BytesIO(conteudo)
        )

        formato = imagem.format
        modo = imagem.mode
        largura, altura = imagem.size

        rgba = imagem.convert("RGBA")

        pixels = list(rgba.getdata())

        contador = Counter(
            p
            for p in pixels
            if p[3] > 0
        )

        cores_frequentes = [
            {
                "rgba": list(cor),
                "pixels": qtd,
            }
            for cor, qtd
            in contador.most_common(50)
        ]

        return {
            "status": "online",
            "url_relativa":
                "img/legenda.png",
            "formato": formato,
            "modo_original": modo,
            "largura_px": largura,
            "altura_px": altura,
            "bytes": len(conteudo),
            "sha256":
                hashlib.sha256(
                    conteudo
                ).hexdigest(),
            "cores_distintas_visiveis":
                len(contador),
            "cores_mais_frequentes":
                cores_frequentes,
            "observacao":
                (
                    "Legenda oficial baixada; "
                    "valores dBZ ainda não "
                    "atribuídos automaticamente."
                ),
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "url_relativa":
                "img/legenda.png",
            "erro": str(erro),
        }


def baixar_e_analisar_quadro(nome):
    resposta = requisicao_radar(
        URL_RADAR_IMAGEM,
        params={
            "prod": 4,
            "radar": "COMP",
            "file": nome,
        },
    )

    conteudo = resposta.content

    return {
        "bytes": len(conteudo),
        "sha256":
            hashlib.sha256(
                conteudo
            ).hexdigest(),
        "imagem":
            analisar_png(conteudo),
    }


def buscar_radar():
    try:
        r = requisicao_radar(
            URL_RADAR_LISTA,
            params={
                "prod": 4,
                "radar": "COMP",
                "data": "",
            },
        )

        imagens = r.json()

        if not isinstance(imagens, list):
            raise ValueError(
                "Resposta do radar "
                "não é uma lista."
            )

        if not imagens:
            raise ValueError(
                "Radar não retornou imagens."
            )

        imagens = imagens[-7:]

        quadros = []

        for nome in imagens:
            try:
                data_utc = datetime.strptime(
                    nome[:14],
                    "%Y%m%d%H%M%S",
                ).replace(
                    tzinfo=ZoneInfo("UTC")
                )

                data_local = (
                    data_utc.astimezone(
                        ZoneInfo(
                            "America/Sao_Paulo"
                        )
                    )
                )

                resultado = (
                    baixar_e_analisar_quadro(
                        nome
                    )
                )

                quadros.append({
                    "arquivo": nome,
                    "horario_utc":
                        data_utc.isoformat(),
                    "horario_local":
                        data_local.isoformat(),
                    "download": "ok",
                    "bytes":
                        resultado["bytes"],
                    "sha256":
                        resultado["sha256"],
                    "imagem":
                        resultado["imagem"],
                })

            except Exception as erro:
                quadros.append({
                    "arquivo": nome,
                    "download": "erro",
                    "erro": str(erro),
                })

        validos = [
            q
            for q in quadros
            if q.get("download") == "ok"
        ]

        if not validos:
            raise ValueError(
                "Nenhum PNG válido."
            )

        ultimo = validos[-1]

        ultimo_utc = datetime.fromisoformat(
            ultimo["horario_utc"]
        )

        agora_utc = datetime.now(
            ZoneInfo("UTC")
        )

        idade = max(
            0,
            round(
                (
                    agora_utc
                    - ultimo_utc
                ).total_seconds()
                / 60,
                1,
            ),
        )

        fresco = idade <= 30

        dimensoes = {
            (
                q["imagem"]["largura_px"],
                q["imagem"]["altura_px"],
            )
            for q in validos
        }

        legenda = analisar_legenda()

        return {
            "status":
                "online"
                if (
                    fresco
                    and len(validos)
                    == len(imagens)
                )
                else "parcial",

            "fonte":
                (
                    "Defesa Civil de "
                    "Santa Catarina - RadarSC"
                ),

            "radar": "COMP",
            "produto": "C-MAX",
            "produto_codigo": 4,
            "extent": RADAR_EXTENT,

            "quantidade_quadros":
                len(imagens),

            "quadros_png_validos":
                len(validos),

            "todos_png_validos":
                len(validos)
                == len(imagens),

            "dimensoes_consistentes":
                len(dimensoes) == 1,

            "quadros": quadros,

            "ultimo_quadro": ultimo,

            "idade_ultimo_quadro_min":
                idade,

            "dados_frescos":
                fresco,

            "legenda_oficial":
                legenda,

            "analise_pixels":
                "diagnostico_rgba_concluido",

            "interpretacao_dbz":
                (
                    "legenda_em_analise"
                    if legenda.get("status")
                    == "online"
                    else
                    "aguardando_legenda"
                ),

            "analise_movimento":
                "aguardando_validacao_paleta",
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte":
                (
                    "Defesa Civil de "
                    "Santa Catarina - RadarSC"
                ),
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
            "status":
                "aguardando_integracao",
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
            "status":
                "sem_alerta_integrado",
            "fonte":
                (
                    "Defesa Civil - "
                    "integração futura"
                ),
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

    print(
        "dados.json criado com sucesso"
    )

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
