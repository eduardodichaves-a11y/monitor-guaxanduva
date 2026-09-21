import json
import hashlib
import io
import math
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3
from PIL import Image


ARQUIVO = "dados.json"

# Coordenada PÚBLICA APROXIMADA do Comasa.
# Não representa endereço residencial.
LAT = -26.27
LON = -48.81

FUSO_LOCAL = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

URL_MARE_CSV = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)

URL_RADAR_SITE = (
    "https://sifap.defesacivil.sc.gov.br/radarsc/"
)

URL_RADAR_BASE = (
    URL_RADAR_SITE
    + "rest/radar/"
)

URL_RADAR_LISTA = (
    URL_RADAR_BASE
    + "getUltimasImagens"
)

URL_RADAR_IMAGEM = (
    URL_RADAR_BASE
    + "getImagem"
)

URL_RADAR_LEGENDA = (
    URL_RADAR_SITE
    + "img/legenda.png"
)

# Extensão geográfica oficial do produto COMP
# obtida do código da própria interface RadarSC:
#
# [oeste, sul, leste, norte]
#
RADAR_EXTENT = [
    -58.0651279,
    -33.8163446,
    -46.4999942,
    -24.7653703,
]

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# UTILIDADES
# =========================================================

def agora_local():
    return datetime.now(FUSO_LOCAL)


def requisicao_normal(
    url,
    params=None,
):
    resposta = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent":
                "Monitor-Guaxanduva/1.0"
        },
    )

    resposta.raise_for_status()

    return resposta


def requisicao_radar(
    url,
    params=None,
):
    """
    O servidor oficial SIFAP apresentou
    problema de cadeia de certificado
    durante os testes no GitHub Actions.

    O verify=False fica restrito SOMENTE
    às chamadas desse servidor oficial.
    """

    resposta = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent":
                "Monitor-Guaxanduva/1.0"
        },
        verify=False,
    )

    resposta.raise_for_status()

    return resposta


def haversine_km(
    lat1,
    lon1,
    lat2,
    lon2,
):
    """
    Distância geodésica aproximada entre
    duas coordenadas.
    """

    raio_terra = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(
        lat2 - lat1
    )

    dlambda = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return raio_terra * c


def rumo_graus(
    lat1,
    lon1,
    lat2,
    lon2,
):
    """
    Azimute inicial do ponto 1
    para o ponto 2.
    """

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dlambda = math.radians(
        lon2 - lon1
    )

    y = (
        math.sin(dlambda)
        * math.cos(phi2)
    )

    x = (
        math.cos(phi1)
        * math.sin(phi2)
        - math.sin(phi1)
        * math.cos(phi2)
        * math.cos(dlambda)
    )

    angulo = math.degrees(
        math.atan2(y, x)
    )

    return (
        angulo + 360
    ) % 360


def ponto_cardinal(graus):
    if graus is None:
        return None

    nomes = [
        "N",
        "NE",
        "L",
        "SE",
        "S",
        "SO",
        "O",
        "NO",
    ]

    indice = int(
        (
            graus + 22.5
        )
        // 45
    ) % 8

    return nomes[indice]


# =========================================================
# CONVERSÃO RADAR: PIXEL ↔ COORDENADA
# =========================================================

def coordenada_para_pixel(
    longitude,
    latitude,
    largura,
    altura,
):
    oeste, sul, leste, norte = (
        RADAR_EXTENT
    )

    x = round(
        (
            longitude - oeste
        )
        / (
            leste - oeste
        )
        * (
            largura - 1
        )
    )

    y = round(
        (
            norte - latitude
        )
        / (
            norte - sul
        )
        * (
            altura - 1
        )
    )

    x = max(
        0,
        min(
            largura - 1,
            x,
        ),
    )

    y = max(
        0,
        min(
            altura - 1,
            y,
        ),
    )

    return x, y


def pixel_para_coordenada(
    x,
    y,
    largura,
    altura,
):
    oeste, sul, leste, norte = (
        RADAR_EXTENT
    )

    longitude = (
        oeste
        + (
            x
            / (
                largura - 1
            )
        )
        * (
            leste - oeste
        )
    )

    latitude = (
        norte
        - (
            y
            / (
                altura - 1
            )
        )
        * (
            norte - sul
        )
    )

    return (
        latitude,
        longitude,
    )


# =========================================================
# OPEN-METEO
# =========================================================

def buscar_previsao():
    url = (
        "https://api.open-meteo.com/v1/forecast"
    )

    parametros = {
        "latitude":
            LAT,

        "longitude":
            LON,

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

        "forecast_days":
            7,

        "timezone":
            "America/Sao_Paulo",
    }

    try:
        r = requisicao_normal(
            url,
            parametros,
        )

        resposta = r.json()

        atual = resposta.get(
            "current",
            {},
        )

        horario = resposta.get(
            "hourly",
            {},
        )

        diario = resposta.get(
            "daily",
            {},
        )

        agora = agora_local()

        indice = None

        for i, tempo in enumerate(
            horario.get(
                "time",
                [],
            )
        ):
            try:
                momento = (
                    datetime.fromisoformat(
                        tempo
                    )
                    .replace(
                        tzinfo=FUSO_LOCAL
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

        for i, data in enumerate(
            diario.get(
                "time",
                [],
            )
        ):

            def dv(nome):
                try:
                    return diario.get(
                        nome,
                        [],
                    )[i]

                except Exception:
                    return None

            dias.append({
                "data":
                    data,

                "probabilidade_chuva_pct":
                    dv(
                        "precipitation_probability_max"
                    ),

                "precipitacao_total_mm":
                    dv(
                        "precipitation_sum"
                    ),

                "vento_max_kmh":
                    dv(
                        "wind_speed_10m_max"
                    ),

                "rajada_max_kmh":
                    dv(
                        "wind_gusts_10m_max"
                    ),
            })

        return {
            "status":
                "online",

            "fonte":
                "Open-Meteo",

            "modelo":
                "Best Match",

            "atual": {
                "horario":
                    atual.get(
                        "time"
                    ),

                "precipitacao_mm":
                    atual.get(
                        "precipitation"
                    ),

                "vento_kmh":
                    atual.get(
                        "wind_speed_10m"
                    ),

                "direcao_graus":
                    atual.get(
                        "wind_direction_10m"
                    ),

                "rajada_kmh":
                    atual.get(
                        "wind_gusts_10m"
                    ),
            },

            "proxima_hora": {
                "horario":
                    valor(
                        horario.get(
                            "time",
                            [],
                        )
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

            "proximos_7_dias":
                dias,
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "fonte":
                "Open-Meteo",

            "erro":
                str(erro),
        }


# =========================================================
# MARÉ EPAGRI/CIRAM
# =========================================================

def buscar_mare():
    try:
        r = requisicao_normal(
            URL_MARE_CSV
        )

        r.encoding = "ISO-8859-1"

        agora = agora_local()

        data_hoje = agora.strftime(
            "%d/%m/%Y"
        )

        eventos = []

        for linha in r.text.splitlines():
            partes = (
                linha
                .strip()
                .split(";")
            )

            if len(partes) != 3:
                continue

            data, hora, altura = partes

            if (
                data.strip()
                != data_hoje
            ):
                continue

            try:
                altura_m = float(
                    altura
                    .strip()
                    .replace(
                        ",",
                        ".",
                    )
                )

                datetime.strptime(
                    hora.strip(),
                    "%H:%M",
                )

            except ValueError:
                continue

            eventos.append({
                "hora":
                    hora.strip(),

                "altura_m":
                    altura_m,
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
            h = datetime.strptime(
                evento["hora"],
                "%H:%M",
            )

            minutos = (
                h.hour * 60
                + h.minute
            )

            if minutos <= agora_minutos:
                anterior = evento

            elif proximo is None:
                proximo = evento

        return {
            "status":
                "online",

            "fonte":
                "EPAGRI/CIRAM",

            "tipo":
                "tabua_de_mare_prevista",

            "local":
                "Joinville",

            "data":
                data_hoje,

            "eventos":
                eventos,

            "anterior":
                anterior,

            "proximo":
                proximo,
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "fonte":
                "EPAGRI/CIRAM",

            "tipo":
                "tabua_de_mare_prevista",

            "erro":
                str(erro),
        }


# =========================================================
# LEGENDA OFICIAL DO RADAR
# =========================================================

def segmentos_de_linha(
    imagem_rgba,
    y,
):
    largura, altura = (
        imagem_rgba.size
    )

    if (
        y < 0
        or y >= altura
    ):
        return []

    segmentos = []

    cor_atual = (
        imagem_rgba.getpixel(
            (0, y)
        )
    )

    inicio = 0

    for x in range(
        1,
        largura,
    ):
        cor = (
            imagem_rgba.getpixel(
                (x, y)
            )
        )

        if cor != cor_atual:
            segmentos.append({
                "x_inicio":
                    inicio,

                "x_fim":
                    x - 1,

                "largura":
                    x - inicio,

                "rgba":
                    list(
                        cor_atual
                    ),
            })

            inicio = x
            cor_atual = cor

    segmentos.append({
        "x_inicio":
            inicio,

        "x_fim":
            largura - 1,

        "largura":
            largura - inicio,

        "rgba":
            list(
                cor_atual
            ),
    })

    return segmentos


def extrair_paleta_oficial():
    """
    Descobre dinamicamente as classes
    cromáticas da legenda oficial.

    NÃO atribui valores dBZ ainda.

    A ordem encontrada na legenda é
    preservada:
    classe 1 = extremo de maior
    refletividade visual;
    classe 16 = extremo de menor
    refletividade visual.

    Essa interpretação ordinal será
    validada separadamente da numeração
    exata em dBZ.
    """

    try:
        r = requisicao_radar(
            URL_RADAR_LEGENDA
        )

        conteudo = r.content

        imagem = Image.open(
            io.BytesIO(
                conteudo
            )
        ).convert("RGBA")

        largura, altura = (
            imagem.size
        )

        candidatos = []

        for y in range(altura):
            segmentos = (
                segmentos_de_linha(
                    imagem,
                    y,
                )
            )

            relevantes = [
                s
                for s in segmentos
                if (
                    s["largura"] >= 5
                    and s["rgba"][3] > 0
                    and s["rgba"][:3]
                    not in (
                        [255, 255, 255],
                        [0, 0, 0],
                    )
                )
            ]

            if len(relevantes) >= 10:
                candidatos.append({
                    "y":
                        y,

                    "segmentos":
                        relevantes,

                    "quantidade":
                        len(relevantes),

                    "largura_total":
                        sum(
                            s["largura"]
                            for s
                            in relevantes
                        ),
                })

        if not candidatos:
            raise ValueError(
                "Faixa colorida da legenda "
                "não encontrada."
            )

        candidatos.sort(
            key=lambda item: (
                item["quantidade"],
                item["largura_total"],
            ),
            reverse=True,
        )

        melhor = candidatos[0]

        segmentos = (
            melhor["segmentos"]
        )

        # O experimento anterior confirmou
        # 16 blocos na legenda.
        #
        # Se houver segmentos espúrios,
        # mantemos os 16 principais pela
        # faixa horizontal contínua.
        #
        if len(segmentos) != 16:
            segmentos = sorted(
                segmentos,
                key=lambda s:
                    s["x_inicio"],
            )

            segmentos = [
                s
                for s in segmentos
                if s["largura"] >= 10
            ]

        if len(segmentos) != 16:
            raise ValueError(
                "Quantidade inesperada de "
                "classes na legenda: "
                f"{len(segmentos)}"
            )

        classes = []

        mapa_rgb = {}

        for indice, segmento in enumerate(
            segmentos,
            start=1,
        ):
            rgb = tuple(
                segmento["rgba"][:3]
            )

            classe = {
                "classe":
                    indice,

                "rgb":
                    list(rgb),

                "x_inicio":
                    segmento[
                        "x_inicio"
                    ],

                "x_fim":
                    segmento[
                        "x_fim"
                    ],

                "largura_px":
                    segmento[
                        "largura"
                    ],

                "dbz":
                    None,
            }

            classes.append(
                classe
            )

            mapa_rgb[rgb] = indice

        return {
            "status":
                "online",

            "fonte":
                "legenda oficial RadarSC",

            "url_relativa":
                "img/legenda.png",

            "sha256":
                hashlib.sha256(
                    conteudo
                ).hexdigest(),

            "largura_px":
                largura,

            "altura_px":
                altura,

            "linha_paleta_y":
                melhor["y"],

            "quantidade_classes":
                len(classes),

            "classes":
                classes,

            "mapa_rgb":
                mapa_rgb,

            "dbz_numerico":
                "aguardando_validacao",

            "observacao":
                (
                    "Paleta extraída diretamente "
                    "da legenda oficial. "
                    "Nenhum valor dBZ foi "
                    "inferido ou inventado."
                ),
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "erro":
                str(erro),

            "mapa_rgb":
                {},
        }


# =========================================================
# ANÁLISE GEOGRÁFICA DOS ECOS
# =========================================================

def analisar_ecos(
    conteudo,
    mapa_rgb,
):
    """
    Localiza somente pixels cuja cor RGB
    pertence exatamente à paleta oficial.

    Assim, pixels transparentes e outros
    elementos não são confundidos com eco.

    Nesta etapa usamos classes ordinais.
    Ainda NÃO transformamos classe em dBZ.
    """

    imagem = Image.open(
        io.BytesIO(
            conteudo
        )
    ).convert("RGBA")

    largura, altura = (
        imagem.size
    )

    pixel_comasa = (
        coordenada_para_pixel(
            LON,
            LAT,
            largura,
            altura,
        )
    )

    x_comasa, y_comasa = (
        pixel_comasa
    )

    total_ecos = 0

    contagem_classes = Counter()

    eco_mais_proximo = None

    eco_mais_forte = None

    # Para não recalcular trigonometria
    # desnecessariamente em pixels que não
    # pertencem à paleta, primeiro testamos
    # a cor.
    for y in range(altura):
        for x in range(largura):
            r, g, b, a = (
                imagem.getpixel(
                    (x, y)
                )
            )

            if a == 0:
                continue

            rgb = (
                r,
                g,
                b,
            )

            classe = (
                mapa_rgb.get(
                    rgb
                )
            )

            if classe is None:
                continue

            total_ecos += 1

            contagem_classes[
                classe
            ] += 1

            lat, lon = (
                pixel_para_coordenada(
                    x,
                    y,
                    largura,
                    altura,
                )
            )

            distancia = (
                haversine_km(
                    LAT,
                    LON,
                    lat,
                    lon,
                )
            )

            direcao = (
                rumo_graus(
                    LAT,
                    LON,
                    lat,
                    lon,
                )
            )

            candidato = {
                "pixel_x":
                    x,

                "pixel_y":
                    y,

                "latitude":
                    round(
                        lat,
                        5,
                    ),

                "longitude":
                    round(
                        lon,
                        5,
                    ),

                "distancia_comasa_km":
                    round(
                        distancia,
                        2,
                    ),

                "direcao_graus":
                    round(
                        direcao,
                        1,
                    ),

                "direcao_cardinal":
                    ponto_cardinal(
                        direcao
                    ),

                "classe_refletividade":
                    classe,

                "rgb":
                    [
                        r,
                        g,
                        b,
                    ],

                "dbz":
                    None,
            }

            if (
                eco_mais_proximo is None
                or distancia
                < eco_mais_proximo[
                    "_distancia"
                ]
            ):
                eco_mais_proximo = {
                    "_distancia":
                        distancia,

                    **candidato,
                }

            # Classe 1 corresponde ao
            # extremo mais intenso da
            # paleta visual extraída.
            if (
                eco_mais_forte is None
                or classe
                < eco_mais_forte[
                    "_classe"
                ]
            ):
                eco_mais_forte = {
                    "_classe":
                        classe,

                    **candidato,
                }

    if eco_mais_proximo:
        eco_mais_proximo.pop(
            "_distancia",
            None,
        )

    if eco_mais_forte:
        eco_mais_forte.pop(
            "_classe",
            None,
        )

    classes_presentes = []

    for classe in sorted(
        contagem_classes
    ):
        classes_presentes.append({
            "classe":
                classe,

            "pixels":
                contagem_classes[
                    classe
                ],
        })

    # Verificação local ao redor do Comasa.
    #
    # Aproximadamente 10 km é usado SOMENTE
    # como área diagnóstica. Não é limiar de
    # alerta de enchente.
    ecos_ate_10km = 0
    classe_mais_forte_10km = None

    if total_ecos > 0:
        for y in range(altura):
            for x in range(largura):
                r, g, b, a = (
                    imagem.getpixel(
                        (x, y)
                    )
                )

                if a == 0:
                    continue

                classe = mapa_rgb.get(
                    (
                        r,
                        g,
                        b,
                    )
                )

                if classe is None:
                    continue

                lat, lon = (
                    pixel_para_coordenada(
                        x,
                        y,
                        largura,
                        altura,
                    )
                )

                distancia = (
                    haversine_km(
                        LAT,
                        LON,
                        lat,
                        lon,
                    )
                )

                if distancia <= 10:
                    ecos_ate_10km += 1

                    if (
                        classe_mais_forte_10km
                        is None
                        or classe
                        < classe_mais_forte_10km
                    ):
                        classe_mais_forte_10km = (
                            classe
                        )

    return {
        "largura_px":
            largura,

        "altura_px":
            altura,

        "pixel_comasa": {
            "x":
                x_comasa,

            "y":
                y_comasa,

            "latitude_aproximada":
                LAT,

            "longitude_aproximada":
                LON,
        },

        "pixels_eco_identificados":
            total_ecos,

        "classes_presentes":
            classes_presentes,

        "eco_mais_proximo":
            eco_mais_proximo,

        "eco_mais_forte":
            eco_mais_forte,

        "area_10km": {
            "pixels_eco":
                ecos_ate_10km,

            "classe_mais_forte":
                classe_mais_forte_10km,

            "observacao":
                (
                    "Raio diagnóstico de 10 km; "
                    "não representa limiar oficial "
                    "de risco ou inundação."
                ),
        },

        "dbz":
            "aguardando_validacao_da_escala",
    }


# =========================================================
# QUADROS DO RADAR
# =========================================================

def baixar_quadro(
    nome,
    mapa_rgb,
):
    resposta = requisicao_radar(
        URL_RADAR_IMAGEM,
        params={
            "prod":
                4,

            "radar":
                "COMP",

            "file":
                nome,
        },
    )

    conteudo = resposta.content

    if not conteudo.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        raise ValueError(
            "Resposta não é PNG válido."
        )

    imagem = Image.open(
        io.BytesIO(
            conteudo
        )
    )

    largura, altura = (
        imagem.size
    )

    return {
        "bytes":
            len(conteudo),

        "sha256":
            hashlib.sha256(
                conteudo
            ).hexdigest(),

        "largura_px":
            largura,

        "altura_px":
            altura,

        "ecos":
            analisar_ecos(
                conteudo,
                mapa_rgb,
            ),
    }


# =========================================================
# TENDÊNCIA TEMPORAL DOS ECOS
# =========================================================

def analisar_tendencia(
    quadros_validos,
):
    """
    Primeira análise temporal conservadora.

    Compara a distância do eco mais próximo
    em quadros consecutivos.

    NÃO calcula ETA ainda.

    Uma célula pode nascer, dissipar ou ser
    substituída por outra; por isso esta
    tendência ainda não é tratada como
    rastreamento de uma célula individual.
    """

    serie = []

    for quadro in quadros_validos:
        eco = (
            quadro
            .get(
                "ecos",
                {}
            )
            .get(
                "eco_mais_proximo"
            )
        )

        if not eco:
            continue

        serie.append({
            "horario_local":
                quadro.get(
                    "horario_local"
                ),

            "distancia_km":
                eco.get(
                    "distancia_comasa_km"
                ),

            "direcao_cardinal":
                eco.get(
                    "direcao_cardinal"
                ),

            "classe":
                eco.get(
                    "classe_refletividade"
                ),
        })

    if len(serie) < 2:
        return {
            "status":
                "dados_insuficientes",

            "serie":
                serie,

            "tendencia":
                "indeterminada",

            "eta":
                None,
        }

    primeiro = serie[0]
    ultimo = serie[-1]

    diferenca = (
        ultimo["distancia_km"]
        - primeiro["distancia_km"]
    )

    if diferenca <= -2:
        tendencia = "aproximando"

    elif diferenca >= 2:
        tendencia = "afastando"

    else:
        tendencia = "praticamente_estavel"

    return {
        "status":
            "diagnostico_inicial",

        "serie":
            serie,

        "distancia_inicial_km":
            primeiro[
                "distancia_km"
            ],

        "distancia_final_km":
            ultimo[
                "distancia_km"
            ],

        "variacao_distancia_km":
            round(
                diferenca,
                2,
            ),

        "tendencia":
            tendencia,

        "eta":
            None,

        "observacao":
            (
                "Tendência baseada no eco mais "
                "próximo em cada quadro. Ainda "
                "não representa rastreamento "
                "confirmado da mesma célula."
            ),
    }


# =========================================================
# RADAR COMPLETO
# =========================================================

def buscar_radar():
    try:
        paleta = (
            extrair_paleta_oficial()
        )

        if (
            paleta.get("status")
            != "online"
        ):
            raise ValueError(
                "Paleta oficial indisponível: "
                + str(
                    paleta.get(
                        "erro"
                    )
                )
            )

        mapa_rgb = (
            paleta.get(
                "mapa_rgb",
                {},
            )
        )

        r = requisicao_radar(
            URL_RADAR_LISTA,
            params={
                "prod":
                    4,

                "radar":
                    "COMP",

                "data":
                    "",
            },
        )

        imagens = r.json()

        if not isinstance(
            imagens,
            list,
        ):
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
                data_utc = (
                    datetime.strptime(
                        nome[:14],
                        "%Y%m%d%H%M%S",
                    )
                    .replace(
                        tzinfo=UTC
                    )
                )

                data_local = (
                    data_utc.astimezone(
                        FUSO_LOCAL
                    )
                )

                resultado = (
                    baixar_quadro(
                        nome,
                        mapa_rgb,
                    )
                )

                quadros.append({
                    "arquivo":
                        nome,

                    "horario_utc":
                        data_utc.isoformat(),

                    "horario_local":
                        data_local.isoformat(),

                    "download":
                        "ok",

                    "bytes":
                        resultado[
                            "bytes"
                        ],

                    "sha256":
                        resultado[
                            "sha256"
                        ],

                    "largura_px":
                        resultado[
                            "largura_px"
                        ],

                    "altura_px":
                        resultado[
                            "altura_px"
                        ],

                    "ecos":
                        resultado[
                            "ecos"
                        ],
                })

            except Exception as erro:
                quadros.append({
                    "arquivo":
                        nome,

                    "download":
                        "erro",

                    "erro":
                        str(erro),
                })

        validos = [
            quadro
            for quadro in quadros
            if (
                quadro.get(
                    "download"
                )
                == "ok"
            )
        ]

        if not validos:
            raise ValueError(
                "Nenhum PNG válido."
            )

        ultimo = validos[-1]

        ultimo_utc = (
            datetime.fromisoformat(
                ultimo[
                    "horario_utc"
                ]
            )
        )

        agora_utc = datetime.now(
            UTC
        )

        idade = max(
            0,
            round(
                (
                    agora_utc
                    - ultimo_utc
                )
                .total_seconds()
                / 60,
                1,
            ),
        )

        fresco = (
            idade <= 30
        )

        dimensoes = {
            (
                quadro[
                    "largura_px"
                ],
                quadro[
                    "altura_px"
                ],
            )
            for quadro
            in validos
        }

        tendencia = (
            analisar_tendencia(
                validos
            )
        )

        # mapa_rgb usa tuplas como chaves e
        # não pode ir diretamente para JSON.
        paleta_publica = {
            chave:
                valor
            for chave, valor
            in paleta.items()
            if chave != "mapa_rgb"
        }

        return {
            "status":
                (
                    "online"
                    if (
                        fresco
                        and len(validos)
                        == len(imagens)
                    )
                    else
                    "parcial"
                ),

            "fonte":
                (
                    "Defesa Civil de "
                    "Santa Catarina - RadarSC"
                ),

            "radar":
                "COMP",

            "produto":
                "C-MAX",

            "produto_codigo":
                4,

            "extent":
                RADAR_EXTENT,

            "quantidade_quadros":
                len(imagens),

            "quadros_png_validos":
                len(validos),

            "todos_png_validos":
                (
                    len(validos)
                    == len(imagens)
                ),

            "dimensoes_consistentes":
                (
                    len(dimensoes)
                    == 1
                ),

            "idade_ultimo_quadro_min":
                idade,

            "dados_frescos":
                fresco,

            "paleta_oficial":
                paleta_publica,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "analise_geografica":
                {
                    "status":
                        "ativa",

                    "metodo":
                        (
                            "pixel_radar_para_"
                            "coordenada_geografica"
                        ),

                    "referencia":
                        (
                            "Comasa - "
                            "coordenada pública "
                            "aproximada"
                        ),

                    "ultimo_eco_mais_proximo":
                        (
                            ultimo
                            .get(
                                "ecos",
                                {}
                            )
                            .get(
                                "eco_mais_proximo"
                            )
                        ),

                    "ultimo_eco_mais_forte":
                        (
                            ultimo
                            .get(
                                "ecos",
                                {}
                            )
                            .get(
                                "eco_mais_forte"
                            )
                        ),

                    "area_10km":
                        (
                            ultimo
                            .get(
                                "ecos",
                                {}
                            )
                            .get(
                                "area_10km"
                            )
                        ),
                },

            "analise_movimento":
                tendencia,

            "interpretacao_dbz":
                "aguardando_validacao_numerica",

            "eta":
                {
                    "status":
                        "ainda_nao_calculado",

                    "motivo":
                        (
                            "Primeiro validar "
                            "localização e tendência "
                            "dos ecos entre quadros."
                        ),
                },
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "fonte":
                (
                    "Defesa Civil de "
                    "Santa Catarina - RadarSC"
                ),

            "radar":
                "COMP",

            "produto":
                "C-MAX",

            "produto_codigo":
                4,

            "dados_frescos":
                False,

            "erro":
                str(erro),
        }


# =========================================================
# PROGRAMA PRINCIPAL
# =========================================================

def main():
    agora = agora_local()

    previsao = (
        buscar_previsao()
    )

    mare = (
        buscar_mare()
    )

    radar = (
        buscar_radar()
    )

    dados = {
        "monitor":
            "Monitor Guaxanduva",

        "local":
            "Comasa - Joinville/SC",

        "gerado_em":
            agora.isoformat(),

        "chuva": {
            "status":
                "aguardando_integracao",

            "fonte":
                "CEMADEN",

            "leitura_mm":
                None,

            "acumulado_1h_mm":
                None,

            "acumulado_24h_mm":
                None,
        },

        "mare":
            mare,

        "rio": {
            "nome":
                "Rio Guaxanduva",

            "status":
                "sem_sensor_publico_confirmado",

            "nivel_m":
                None,
        },

        "previsao":
            previsao,

        "radar":
            radar,

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
            "defesa_civil":
                "199",

            "bombeiros":
                "193",
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
