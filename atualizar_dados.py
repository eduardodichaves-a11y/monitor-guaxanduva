import io
import json
import math
import hashlib
from collections import Counter, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import urllib3
from PIL import Image


ARQUIVO = "dados.json"

# Coordenada pública aproximada do Comasa.
# Não representa endereço residencial.
LAT = -26.27
LON = -48.81

FUSO = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")

MARE = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)

RADAR = "https://sifap.defesacivil.sc.gov.br/radarsc/"
LISTA = RADAR + "rest/radar/getUltimasImagens"
IMAGEM = RADAR + "rest/radar/getImagem"
LEGENDA = RADAR + "img/legenda.png"

# Extensão geográfica oficial usada pelo produto COMP.
EXT = [
    -58.0651279,
    -33.8163446,
    -46.4999942,
    -24.7653703,
]

# Cor ainda não validada como eco meteorológico.
CINZA = (200, 200, 200)

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# UTILIDADES
# =========================================================

def agora():
    return datetime.now(FUSO)


def get(url, params=None, radar=False):
    r = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "Monitor-Guaxanduva/1.0"
        },
        verify=False if radar else True,
    )
    r.raise_for_status()
    return r


def hav(lat1, lon1, lat2, lon2):
    """
    Distância de Haversine em quilômetros.
    """
    raio = 6371.0088

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return (
        raio
        * 2
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a),
        )
    )


def rumo(lat1, lon1, lat2, lon2):
    """
    Rumo geográfico em graus:
    0=N, 90=L, 180=S, 270=O.
    """
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)

    y = math.sin(dl) * math.cos(p2)

    x = (
        math.cos(p1) * math.sin(p2)
        - math.sin(p1)
        * math.cos(p2)
        * math.cos(dl)
    )

    return (
        math.degrees(math.atan2(y, x))
        + 360
    ) % 360


def cardinal(graus):
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

    return nomes[
        int((graus + 22.5) // 45) % 8
    ]


def difang(a, b):
    """
    Menor diferença angular entre dois rumos.
    """
    return abs(
        (a - b + 180) % 360 - 180
    )


def px2geo(x, y, largura, altura):
    oeste, sul, leste, norte = EXT

    lat = (
        norte
        - y / (altura - 1)
        * (norte - sul)
    )

    lon = (
        oeste
        + x / (largura - 1)
        * (leste - oeste)
    )

    return lat, lon


def geo2px(lon, lat, largura, altura):
    oeste, sul, leste, norte = EXT

    x = round(
        (lon - oeste)
        / (leste - oeste)
        * (largura - 1)
    )

    y = round(
        (norte - lat)
        / (norte - sul)
        * (altura - 1)
    )

    x = max(
        0,
        min(largura - 1, x),
    )

    y = max(
        0,
        min(altura - 1, y),
    )

    return x, y


def local_xy(lat0, lon0, lat, lon):
    """
    Converte latitude/longitude para um plano local
    aproximado em quilômetros.
    """
    y = (lat - lat0) * 111.32

    x = (
        (lon - lon0)
        * 111.32
        * math.cos(
            math.radians(
                (lat + lat0) / 2
            )
        )
    )

    return x, y


def media_angular_ponderada(valores):
    """
    valores = [(angulo_graus, peso), ...]
    """
    if not valores:
        return None

    sx = 0.0
    sy = 0.0

    for angulo, peso in valores:
        rad = math.radians(angulo)

        sx += math.sin(rad) * peso
        sy += math.cos(rad) * peso

    if (
        abs(sx) < 1e-12
        and abs(sy) < 1e-12
    ):
        return None

    return (
        math.degrees(
            math.atan2(sx, sy)
        )
        + 360
    ) % 360


# =========================================================
# PREVISÃO
# =========================================================

def buscar_previsao():
    try:
        params = {
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

        dados = get(
            "https://api.open-meteo.com/v1/forecast",
            params,
        ).json()

        atual = dados.get(
            "current",
            {},
        )

        horario = dados.get(
            "hourly",
            {},
        )

        diario = dados.get(
            "daily",
            {},
        )

        indice = None

        for i, texto in enumerate(
            horario.get("time", [])
        ):
            try:
                momento = (
                    datetime
                    .fromisoformat(texto)
                    .replace(tzinfo=FUSO)
                )

                if momento > agora():
                    indice = i
                    break

            except Exception:
                pass

        def hv(chave):
            valores = horario.get(
                chave,
                [],
            )

            if (
                indice is not None
                and indice < len(valores)
            ):
                return valores[indice]

            return None

        dias = []

        for i, data in enumerate(
            diario.get("time", [])
        ):
            def dv(chave):
                valores = diario.get(
                    chave,
                    [],
                )

                if i < len(valores):
                    return valores[i]

                return None

            dias.append({
                "data": data,
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
            "status": "online",
            "fonte": "Open-Meteo",
            "modelo": "Best Match",

            "atual": {
                "horario":
                    atual.get("time"),

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
                    hv("time"),

                "probabilidade_chuva_pct":
                    hv(
                        "precipitation_probability"
                    ),

                "precipitacao_mm":
                    hv(
                        "precipitation"
                    ),

                "vento_kmh":
                    hv(
                        "wind_speed_10m"
                    ),

                "direcao_graus":
                    hv(
                        "wind_direction_10m"
                    ),

                "rajada_kmh":
                    hv(
                        "wind_gusts_10m"
                    ),
            },

            "proximos_7_dias": dias,
        }

    except Exception as e:
        return {
            "status": "indisponivel",
            "fonte": "Open-Meteo",
            "erro": str(e),
        }


# =========================================================
# MARÉ
# =========================================================

def buscar_mare():
    try:
        resposta = get(MARE)
        resposta.encoding = "ISO-8859-1"

        atual = agora()
        data_hoje = atual.strftime(
            "%d/%m/%Y"
        )

        eventos = []

        for linha in resposta.text.splitlines():
            partes = linha.strip().split(";")

            if (
                len(partes) != 3
                or partes[0].strip()
                != data_hoje
            ):
                continue

            try:
                altura = float(
                    partes[2]
                    .strip()
                    .replace(",", ".")
                )

                datetime.strptime(
                    partes[1].strip(),
                    "%H:%M",
                )

            except Exception:
                continue

            eventos.append({
                "hora":
                    partes[1].strip(),

                "altura_m":
                    altura,
            })

        if not eventos:
            raise ValueError(
                "Nenhum evento de maré para "
                + data_hoje
            )

        eventos.sort(
            key=lambda x:
                datetime.strptime(
                    x["hora"],
                    "%H:%M",
                )
        )

        minuto_atual = (
            atual.hour * 60
            + atual.minute
        )

        anterior = None
        proximo = None

        for evento in eventos:
            momento = datetime.strptime(
                evento["hora"],
                "%H:%M",
            )

            minuto = (
                momento.hour * 60
                + momento.minute
            )

            if minuto <= minuto_atual:
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

    except Exception as e:
        return {
            "status": "indisponivel",
            "fonte": "EPAGRI/CIRAM",
            "tipo": "tabua_de_mare_prevista",
            "erro": str(e),
        }


# =========================================================
# LEGENDA OFICIAL DO RADAR
# =========================================================

def legenda():
    try:
        bruto = get(
            LEGENDA,
            radar=True,
        ).content

        imagem = Image.open(
            io.BytesIO(bruto)
        ).convert("RGBA")

        melhor = []

        for y in range(imagem.height):
            segmentos = []

            cor = imagem.getpixel(
                (0, y)
            )

            inicio = 0

            for x in range(
                1,
                imagem.width,
            ):
                atual = imagem.getpixel(
                    (x, y)
                )

                if atual != cor:
                    largura = x - inicio

                    if (
                        largura >= 10
                        and cor[3] > 0
                        and cor[:3]
                        not in (
                            (255, 255, 255),
                            (0, 0, 0),
                        )
                    ):
                        segmentos.append(
                            (
                                inicio,
                                x - 1,
                                cor,
                            )
                        )

                    inicio = x
                    cor = atual

            largura = (
                imagem.width
                - inicio
            )

            if (
                largura >= 10
                and cor[3] > 0
                and cor[:3]
                not in (
                    (255, 255, 255),
                    (0, 0, 0),
                )
            ):
                segmentos.append(
                    (
                        inicio,
                        imagem.width - 1,
                        cor,
                    )
                )

            if (
                len(segmentos)
                > len(melhor)
            ):
                melhor = segmentos

        classes = []

        for i, segmento in enumerate(
            melhor[:16]
        ):
            classes.append({
                "classe": i + 1,
                "rgb":
                    list(
                        segmento[2][:3]
                    ),
                "dbz": None,
            })

        return {
            "status": "online",
            "fonte":
                "legenda oficial RadarSC",

            "sha256":
                hashlib
                .sha256(bruto)
                .hexdigest(),

            "quantidade_classes":
                len(classes),

            "classes":
                classes,

            "dbz_numerico":
                "aguardando_validacao",
        }

    except Exception as e:
        return {
            "status": "indisponivel",
            "erro": str(e),
        }


# =========================================================
# PNG INDEXADO
# =========================================================

def alpha_idx(transparencia, indice):
    if transparencia is None:
        return 255

    if isinstance(
        transparencia,
        int,
    ):
        return (
            0
            if indice == transparencia
            else 255
        )

    if (
        isinstance(
            transparencia,
            (bytes, bytearray),
        )
        and indice
        < len(transparencia)
    ):
        return int(
            transparencia[indice]
        )

    return 255


def rgb_idx(paleta, indice):
    pos = indice * 3

    if (
        paleta
        and pos + 2
        < len(paleta)
    ):
        return tuple(
            paleta[
                pos:pos + 3
            ]
        )

    return None


def diagnostico(imagem):
    if imagem.mode != "P":
        return {
            "status": "modo_inesperado",
            "modo_original":
                imagem.mode,
        }

    paleta = imagem.getpalette()

    transparencia = (
        imagem.info.get(
            "transparency"
        )
    )

    contagem = Counter(
        imagem.getdata()
    )

    itens = []

    visiveis = 0
    transparentes = 0
    cinza = 0
    candidatos = 0

    for indice, quantidade in sorted(
        contagem.items()
    ):
        rgb = rgb_idx(
            paleta,
            indice,
        )

        alpha = alpha_idx(
            transparencia,
            indice,
        )

        visivel = alpha > 0
        eh_cinza = rgb == CINZA

        candidato = (
            visivel
            and not eh_cinza
        )

        if visivel:
            visiveis += quantidade
        else:
            transparentes += quantidade

        if eh_cinza:
            cinza += quantidade

        if candidato:
            candidatos += quantidade

        itens.append({
            "indice_p":
                int(indice),

            "rgb":
                list(rgb)
                if rgb
                else None,

            "alpha":
                alpha,

            "pixels":
                quantidade,

            "visivel":
                visivel,

            "cinza_nao_validado":
                eh_cinza,

            "candidato_meteorologico":
                candidato,
        })

    return {
        "status": "online",
        "modo_original":
            imagem.mode,

        "largura_px":
            imagem.width,

        "altura_px":
            imagem.height,

        "total_pixels":
            imagem.width
            * imagem.height,

        "pixels_transparentes":
            transparentes,

        "pixels_visiveis":
            visiveis,

        "pixels_cinza_nao_validado":
            cinza,

        "pixels_candidatos_meteorologicos":
            candidatos,

        "indices_usados":
            itens,
    }


def mascara(imagem):
    if imagem.mode != "P":
        return set(), {}

    paleta = imagem.getpalette()

    transparencia = (
        imagem.info.get(
            "transparency"
        )
    )

    indices = {}

    for indice in set(
        imagem.getdata()
    ):
        rgb = rgb_idx(
            paleta,
            indice,
        )

        if (
            alpha_idx(
                transparencia,
                indice,
            ) > 0
            and rgb is not None
            and rgb != CINZA
        ):
            indices[indice] = rgb

    pixels = imagem.load()

    pontos = {
        (x, y)

        for y in range(
            imagem.height
        )

        for x in range(
            imagem.width
        )

        if pixels[x, y]
        in indices
    }

    return pontos, indices


# =========================================================
# COMPONENTES CONECTADOS
# =========================================================

def componentes(mascara_pixels):
    restantes = set(
        mascara_pixels
    )

    resultado = []

    vizinhos = (
        (-1, -1),
        (0, -1),
        (1, -1),
        (-1, 0),
        (1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
    )

    while restantes:
        inicio = restantes.pop()

        fila = deque([inicio])
        pontos = [inicio]

        while fila:
            x, y = fila.popleft()

            for dx, dy in vizinhos:
                ponto = (
                    x + dx,
                    y + dy,
                )

                if ponto in restantes:
                    restantes.remove(
                        ponto
                    )

                    fila.append(
                        ponto
                    )

                    pontos.append(
                        ponto
                    )

        if len(pontos) >= 3:
            resultado.append(
                pontos
            )

    return sorted(
        resultado,
        key=len,
        reverse=True,
    )


def resumo_comp(
    pontos,
    imagem,
    numero,
):
    xs = [
        p[0]
        for p in pontos
    ]

    ys = [
        p[1]
        for p in pontos
    ]

    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    lat, lon = px2geo(
        cx,
        cy,
        imagem.width,
        imagem.height,
    )

    distancia_centro = hav(
        LAT,
        LON,
        lat,
        lon,
    )

    rumo_centro = rumo(
        LAT,
        LON,
        lat,
        lon,
    )

    paleta = imagem.getpalette()
    pixels = imagem.load()

    cores = Counter()
    mais_proximo = None

    for x, y in pontos:
        la, lo = px2geo(
            x,
            y,
            imagem.width,
            imagem.height,
        )

        distancia = hav(
            LAT,
            LON,
            la,
            lo,
        )

        if (
            mais_proximo is None
            or distancia
            < mais_proximo[0]
        ):
            mais_proximo = (
                distancia,
                x,
                y,
                la,
                lo,
            )

        rgb = rgb_idx(
            paleta,
            pixels[x, y],
        )

        if rgb:
            cores[rgb] += 1

    (
        distancia,
        x,
        y,
        la,
        lo,
    ) = mais_proximo

    rumo_minimo = rumo(
        LAT,
        LON,
        la,
        lo,
    )

    return {
        "id_quadro":
            numero,

        "pixels":
            len(pontos),

        "centroide": {
            "pixel_x":
                round(cx, 1),

            "pixel_y":
                round(cy, 1),

            "latitude":
                round(lat, 5),

            "longitude":
                round(lon, 5),

            "distancia_comasa_km":
                round(
                    distancia_centro,
                    2,
                ),

            "direcao_graus":
                round(
                    rumo_centro,
                    1,
                ),

            "direcao_cardinal":
                cardinal(
                    rumo_centro
                ),
        },

        "ponto_mais_proximo_comasa": {
            "pixel_x":
                x,

            "pixel_y":
                y,

            "latitude":
                round(la, 5),

            "longitude":
                round(lo, 5),

            "distancia_comasa_km":
                round(
                    distancia,
                    2,
                ),

            "direcao_graus":
                round(
                    rumo_minimo,
                    1,
                ),

            "direcao_cardinal":
                cardinal(
                    rumo_minimo
                ),
        },

        "caixa_pixels": {
            "x_min":
                min(xs),

            "x_max":
                max(xs),

            "y_min":
                min(ys),

            "y_max":
                max(ys),
        },

        "cores": [
            {
                "rgb":
                    list(cor),

                "pixels":
                    quantidade,
            }

            for cor, quantidade
            in cores.most_common()
        ],

        "dbz": None,

        "classificacao":
            "candidato_a_area_de_eco",
    }


def analisar(imagem):
    pontos, indices = mascara(
        imagem
    )

    xc, yc = geo2px(
        LON,
        LAT,
        imagem.width,
        imagem.height,
    )

    if not pontos:
        return {
            "status":
                "sem_pixels_candidatos",

            "pixel_comasa": {
                "x": xc,
                "y": yc,
            },

            "pixels_candidatos":
                0,

            "quantidade_componentes_3px_ou_mais":
                0,

            "maiores_componentes":
                [],

            "componentes_mais_proximos_comasa":
                [],
        }

    raios = {
        10: 0,
        25: 0,
        50: 0,
        100: 0,
    }

    eco = None

    for x, y in pontos:
        la, lo = px2geo(
            x,
            y,
            imagem.width,
            imagem.height,
        )

        distancia = hav(
            LAT,
            LON,
            la,
            lo,
        )

        for raio in raios:
            if distancia <= raio:
                raios[raio] += 1

        if (
            eco is None
            or distancia < eco["_d"]
        ):
            direcao = rumo(
                LAT,
                LON,
                la,
                lo,
            )

            eco = {
                "_d":
                    distancia,

                "pixel_x":
                    x,

                "pixel_y":
                    y,

                "latitude":
                    round(la, 5),

                "longitude":
                    round(lo, 5),

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
                    cardinal(
                        direcao
                    ),
            }

    if eco:
        eco.pop(
            "_d",
            None,
        )

    blocos = componentes(
        pontos
    )

    resumos = [
        resumo_comp(
            componente,
            imagem,
            i,
        )

        for i, componente
        in enumerate(
            blocos[:40],
            1,
        )
    ]

    proximos = sorted(
        resumos,
        key=lambda c:
            c[
                "ponto_mais_proximo_comasa"
            ][
                "distancia_comasa_km"
            ],
    )

    return {
        "status":
            "diagnostico_espacial_ativo",

        "metodo":
            "componentes_conectados_8_vizinhos",

        "pixel_comasa": {
            "x":
                xc,

            "y":
                yc,

            "latitude_aproximada":
                LAT,

            "longitude_aproximada":
                LON,
        },

        "pixels_candidatos":
            len(pontos),

        "indices_candidatos": [
            {
                "indice_p":
                    indice,

                "rgb":
                    list(rgb),
            }

            for indice, rgb
            in sorted(
                indices.items()
            )
        ],

        "eco_mais_proximo":
            eco,

        "pixels_por_raio": {
            "ate_10_km":
                raios[10],

            "ate_25_km":
                raios[25],

            "ate_50_km":
                raios[50],

            "ate_100_km":
                raios[100],
        },

        "quantidade_componentes_3px_ou_mais":
            len(blocos),

        "maiores_componentes":
            resumos,

        "componentes_mais_proximos_comasa":
            proximos[:10],
    }


# =========================================================
# CASAMENTO ENTRE COMPONENTES
# =========================================================

def distc(a, b):
    ca = a["centroide"]
    cb = b["centroide"]

    return hav(
        ca["latitude"],
        ca["longitude"],
        cb["latitude"],
        cb["longitude"],
    )


def overlap(a, b):
    ca = a["caixa_pixels"]
    cb = b["caixa_pixels"]

    x1 = max(
        ca["x_min"],
        cb["x_min"],
    )

    y1 = max(
        ca["y_min"],
        cb["y_min"],
    )

    x2 = min(
        ca["x_max"],
        cb["x_max"],
    )

    y2 = min(
        ca["y_max"],
        cb["y_max"],
    )

    if (
        x2 < x1
        or y2 < y1
    ):
        return 0

    inter = (
        (x2 - x1 + 1)
        * (y2 - y1 + 1)
    )

    area_a = (
        (
            ca["x_max"]
            - ca["x_min"]
            + 1
        )
        * (
            ca["y_max"]
            - ca["y_min"]
            + 1
        )
    )

    area_b = (
        (
            cb["x_max"]
            - cb["x_min"]
            + 1
        )
        * (
            cb["y_max"]
            - cb["y_min"]
            + 1
        )
    )

    menor = min(
        area_a,
        area_b,
    )

    if menor <= 0:
        return 0

    return inter / menor


def pontuar(a, b, minutos):
    if minutos <= 0:
        return None

    distancia = distc(
        a,
        b,
    )

    velocidade = (
        distancia
        / (minutos / 60)
    )

    if (
        velocidade > 150
        or distancia > 25
    ):
        return None

    tamanho_a = max(
        1,
        a["pixels"],
    )

    tamanho_b = max(
        1,
        b["pixels"],
    )

    razao_tamanho = (
        min(
            tamanho_a,
            tamanho_b,
        )
        / max(
            tamanho_a,
            tamanho_b,
        )
    )

    sobreposicao = overlap(
        a,
        b,
    )

    if (
        razao_tamanho < 0.15
        and sobreposicao == 0
    ):
        return None

    score = (
        max(
            0,
            1 - distancia / 25,
        ) * 0.55

        + razao_tamanho
        * 0.25

        + min(
            1,
            sobreposicao,
        ) * 0.20
    )

    return {
        "score":
            score,

        "distancia_km":
            distancia,

        "velocidade_kmh":
            velocidade,

        "razao_tamanho":
            razao_tamanho,

        "sobreposicao_caixas":
            sobreposicao,
    }


def casar(quadro_a, quadro_b):
    componentes_a = (
        quadro_a
        .get(
            "analise_espacial",
            {},
        )
        .get(
            "maiores_componentes",
            [],
        )
    )

    componentes_b = (
        quadro_b
        .get(
            "analise_espacial",
            {},
        )
        .get(
            "maiores_componentes",
            [],
        )
    )

    if (
        not componentes_a
        or not componentes_b
    ):
        return []

    tempo_a = datetime.fromisoformat(
        quadro_a["horario_utc"]
    )

    tempo_b = datetime.fromisoformat(
        quadro_b["horario_utc"]
    )

    minutos = (
        tempo_b - tempo_a
    ).total_seconds() / 60

    candidatos = []

    for a in componentes_a:
        for b in componentes_b:
            resultado = pontuar(
                a,
                b,
                minutos,
            )

            if resultado:
                candidatos.append({
                    "a": a,
                    "b": b,
                    **resultado,
                })

    candidatos.sort(
        key=lambda x:
            x["score"],
        reverse=True,
    )

    usados_a = set()
    usados_b = set()

    saida = []

    for candidato in candidatos:
        a = candidato["a"]
        b = candidato["b"]

        ia = a["id_quadro"]
        ib = b["id_quadro"]

        if (
            ia in usados_a
            or ib in usados_b
            or candidato["score"]
            < 0.38
        ):
            continue

        usados_a.add(ia)
        usados_b.add(ib)

        ca = a["centroide"]
        cb = b["centroide"]

        direcao = rumo(
            ca["latitude"],
            ca["longitude"],
            cb["latitude"],
            cb["longitude"],
        )

        distancia_a = (
            ca[
                "distancia_comasa_km"
            ]
        )

        distancia_b = (
            cb[
                "distancia_comasa_km"
            ]
        )

        variacao = (
            distancia_b
            - distancia_a
        )

        if variacao < -1:
            tendencia = "aproximando"

        elif variacao > 1:
            tendencia = "afastando"

        else:
            tendencia = "estavel"

        saida.append({
            "componente_anterior":
                ia,

            "componente_atual":
                ib,

            "score":
                round(
                    candidato["score"],
                    3,
                ),

            "intervalo_min":
                round(
                    minutos,
                    1,
                ),

            "deslocamento_centroide_km":
                round(
                    candidato[
                        "distancia_km"
                    ],
                    2,
                ),

            "velocidade_estimada_kmh":
                round(
                    candidato[
                        "velocidade_kmh"
                    ],
                    1,
                ),

            "direcao_movimento_graus":
                round(
                    direcao,
                    1,
                ),

            "direcao_movimento_cardinal":
                cardinal(
                    direcao
                ),

            "razao_tamanho":
                round(
                    candidato[
                        "razao_tamanho"
                    ],
                    3,
                ),

            "sobreposicao_caixas":
                round(
                    candidato[
                        "sobreposicao_caixas"
                    ],
                    3,
                ),

            "distancia_comasa_anterior_km":
                distancia_a,

            "distancia_comasa_atual_km":
                distancia_b,

            "variacao_distancia_comasa_km":
                round(
                    variacao,
                    2,
                ),

            "tendencia_relativa_comasa":
                tendencia,

            "centroide_anterior":
                ca,

            "centroide_atual":
                cb,
        })

    return saida


# =========================================================
# RASTREAMENTO TEMPORAL
# =========================================================

def rastrear(quadros):
    if len(quadros) < 2:
        return {
            "status":
                "dados_insuficientes",

            "pares_quadros":
                [],

            "trilhas":
                [],
        }

    blocos = []

    for i in range(
        1,
        len(quadros),
    ):
        pares = casar(
            quadros[i - 1],
            quadros[i],
        )

        blocos.append({
            "de":
                quadros[
                    i - 1
                ][
                    "horario_local"
                ],

            "para":
                quadros[
                    i
                ][
                    "horario_local"
                ],

            "correspondencias":
                pares,

            "quantidade":
                len(pares),
        })

    trilhas = []
    mapa = {}
    proximo_id = 1

    for indice_bloco, bloco in enumerate(
        blocos,
        1,
    ):
        for passo in bloco[
            "correspondencias"
        ]:
            chave_anterior = (
                indice_bloco - 1,
                passo[
                    "componente_anterior"
                ],
            )

            chave_atual = (
                indice_bloco,
                passo[
                    "componente_atual"
                ],
            )

            trilha = mapa.get(
                chave_anterior
            )

            if trilha is None:
                trilha = {
                    "id_trilha":
                        proximo_id,

                    "passos":
                        [],
                }

                proximo_id += 1
                trilhas.append(
                    trilha
                )

            trilha[
                "passos"
            ].append({
                "de":
                    bloco["de"],

                "para":
                    bloco["para"],

                **passo,
            })

            mapa[
                chave_anterior
            ] = trilha

            mapa[
                chave_atual
            ] = trilha

    resumos = []

    for trilha in trilhas:
        passos = trilha[
            "passos"
        ]

        if not passos:
            continue

        aproximando = sum(
            passo[
                "tendencia_relativa_comasa"
            ] == "aproximando"

            for passo in passos
        )

        afastando = sum(
            passo[
                "tendencia_relativa_comasa"
            ] == "afastando"

            for passo in passos
        )

        if aproximando > afastando:
            tendencia = "aproximando"

        elif afastando > aproximando:
            tendencia = "afastando"

        else:
            tendencia = "indeterminada"

        resumos.append({
            "id_trilha":
                trilha["id_trilha"],

            "transicoes":
                len(passos),

            # #117:
            # análise de trajetória exige
            # pelo menos 3 transições.
            "elegivel_para_analise":
                len(passos) >= 3,

            "score_medio":
                round(
                    sum(
                        p["score"]
                        for p in passos
                    )
                    / len(passos),
                    3,
                ),

            "velocidade_media_kmh":
                round(
                    sum(
                        p[
                            "velocidade_estimada_kmh"
                        ]
                        for p in passos
                    )
                    / len(passos),
                    1,
                ),

            "tendencia_relativa_comasa":
                tendencia,

            "passos_aproximando":
                aproximando,

            "passos_afastando":
                afastando,

            "passos_estaveis":
                (
                    len(passos)
                    - aproximando
                    - afastando
                ),

            "ultima_distancia_comasa_km":
                passos[-1][
                    "distancia_comasa_atual_km"
                ],

            "ultima_direcao_movimento":
                passos[-1][
                    "direcao_movimento_cardinal"
                ],

            "passos":
                passos,
        })

    resumos.sort(
        key=lambda t: (
            t[
                "elegivel_para_analise"
            ],
            t["transicoes"],
            t["score_medio"],
        ),
        reverse=True,
    )

    elegiveis = [
        t
        for t in resumos
        if t[
            "elegivel_para_analise"
        ]
    ]

    aproximando = [
        t
        for t in elegiveis
        if t[
            "tendencia_relativa_comasa"
        ] == "aproximando"
    ]

    aproximando.sort(
        key=lambda t: (
            t[
                "ultima_distancia_comasa_km"
            ],
            -t["score_medio"],
        )
    )

    principal = (
        aproximando[0]
        if aproximando
        else (
            elegiveis[0]
            if elegiveis
            else None
        )
    )

    return {
        "status":
            "rastreamento_geometrico_experimental",

        "criterios": {
            "distancia_max_centroide_km":
                25,

            "velocidade_max_kmh":
                150,

            "score_minimo":
                0.38,

            "minimo_transicoes_trilha":
                3,
        },

        "pares_quadros":
            blocos,

        "quantidade_trilhas":
            len(resumos),

        "quantidade_trilhas_elegiveis":
            len(elegiveis),

        "trilhas":
            resumos[:20],

        "trilha_principal_diagnostica":
            principal,

        "observacao":
            (
                "Rastreamento geométrico "
                "experimental. O #117 avalia "
                "todas as trilhas elegíveis "
                "antes de produzir candidato "
                "experimental de ETA."
            ),
    }


# =========================================================
# #117
# TRAJETÓRIA MULTIVETORIAL + CORREDOR + ETA EXPERIMENTAL
# =========================================================

def analisar_interceptacao(
    trilha,
    radar_fresco,
    idade_radar,
    horario_ultimo_quadro,
):
    """
    Avaliação conservadora.

    IMPORTANTE:
    Mesmo quando existir um candidato de ETA,
    ele NÃO é considerado validado para uso
    operacional/público.
    """

    if (
        not trilha
        or trilha.get(
            "transicoes",
            0,
        ) < 3
    ):
        return {
            "status":
                "bloqueado",

            "intercepta_corredor":
                False,

            "candidato_eta":
                False,

            "validado_para_eta":
                False,

            "motivo":
                (
                    "São necessárias pelo "
                    "menos 3 transições para "
                    "analisar trajetória."
                ),

            "eta":
                None,
        }

    passos = trilha[
        "passos"
    ]

    recentes = passos[-3:]

    vetores = []
    rumos = []
    velocidades = []

    for passo in recentes:
        ca = passo[
            "centroide_anterior"
        ]

        cb = passo[
            "centroide_atual"
        ]

        dx, dy = local_xy(
            ca["latitude"],
            ca["longitude"],
            cb["latitude"],
            cb["longitude"],
        )

        deslocamento = math.hypot(
            dx,
            dy,
        )

        if deslocamento < 0.2:
            continue

        peso = max(
            0.01,
            passo.get(
                "score",
                0.01,
            ),
        )

        vetores.append(
            (
                dx,
                dy,
                peso,
            )
        )

        direcao = rumo(
            ca["latitude"],
            ca["longitude"],
            cb["latitude"],
            cb["longitude"],
        )

        rumos.append(
            (
                direcao,
                peso,
            )
        )

        velocidade = passo.get(
            "velocidade_estimada_kmh",
            0,
        )

        if (
            5
            <= velocidade
            <= 120
        ):
            velocidades.append(
                (
                    velocidade,
                    peso,
                )
            )

    if len(vetores) < 2:
        return {
            "status":
                "bloqueado",

            "intercepta_corredor":
                False,

            "candidato_eta":
                False,

            "validado_para_eta":
                False,

            "motivo":
                (
                    "Movimentos recentes "
                    "insuficientes para uma "
                    "trajetória estável."
                ),

            "eta":
                None,
        }

    soma_pesos = sum(
        v[2]
        for v in vetores
    )

    vx = sum(
        v[0] * v[2]
        for v in vetores
    ) / soma_pesos

    vy = sum(
        v[1] * v[2]
        for v in vetores
    ) / soma_pesos

    norma = math.hypot(
        vx,
        vy,
    )

    if norma < 0.2:
        return {
            "status":
                "bloqueado",

            "intercepta_corredor":
                False,

            "candidato_eta":
                False,

            "validado_para_eta":
                False,

            "motivo":
                (
                    "Vetor médio recente "
                    "pequeno demais para "
                    "projeção."
                ),

            "eta":
                None,
        }

    rumo_medio = (
        media_angular_ponderada(
            rumos
        )
    )

    if rumo_medio is None:
        return {
            "status":
                "bloqueado",

            "intercepta_corredor":
                False,

            "candidato_eta":
                False,

            "validado_para_eta":
                False,

            "motivo":
                (
                    "Não foi possível obter "
                    "um rumo médio confiável."
                ),

            "eta":
                None,
        }

    dispersoes = [
        difang(
            direcao,
            rumo_medio,
        )

        for direcao, _
        in rumos
    ]

    dispersao_max = max(
        dispersoes
    )

    dispersao_media = (
        sum(dispersoes)
        / len(dispersoes)
    )

    ultimo = passos[-1][
        "centroide_atual"
    ]

    # Plano local centrado no Comasa.
    px, py = local_xy(
        LAT,
        LON,
        ultimo["latitude"],
        ultimo["longitude"],
    )

    distancia_atual = math.hypot(
        px,
        py,
    )

    # Vetor médio unitário.
    ux = vx / norma
    uy = vy / norma

    # Vetor do eco atual até o Comasa.
    alvo_x = -px
    alvo_y = -py

    rumo_para_comasa = rumo(
        ultimo["latitude"],
        ultimo["longitude"],
        LAT,
        LON,
    )

    diferenca_angular = difang(
        rumo_medio,
        rumo_para_comasa,
    )

    # Quanto o alvo está à frente
    # do vetor de movimento.
    projecao_adiante = (
        alvo_x * ux
        + alvo_y * uy
    )

    # Distância perpendicular entre
    # Comasa e a linha projetada.
    distancia_lateral = abs(
        alvo_x * uy
        - alvo_y * ux
    )

    # Corredor conservador.
    corredor = 15.0

    aponta_para_frente = (
        projecao_adiante > 0
    )

    angulo_compativel = (
        diferenca_angular <= 40
    )

    direcao_estavel = (
        dispersao_max <= 45
    )

    intercepta = (
        aponta_para_frente
        and angulo_compativel
        and direcao_estavel
        and distancia_lateral
        <= corredor
    )

    if velocidades:
        soma_pesos_vel = sum(
            peso
            for _, peso
            in velocidades
        )

        velocidade_media = (
            sum(
                velocidade * peso
                for velocidade, peso
                in velocidades
            )
            / soma_pesos_vel
        )

    else:
        velocidade_media = 0

    # Tempo para o ponto de maior aproximação.
    if velocidade_media > 0:
        minutos_ponto_proximo = (
            projecao_adiante
            / velocidade_media
            * 60
        )
    else:
        minutos_ponto_proximo = None

    base = {
        "status":
            "diagnostico",

        "versao_metodo":
            "#117_multivetorial",

        "trilha_id":
            trilha.get(
                "id_trilha"
            ),

        "transicoes":
            trilha.get(
                "transicoes"
            ),

        "score_medio":
            trilha.get(
                "score_medio"
            ),

        "intercepta_corredor":
            intercepta,

        "candidato_eta":
            False,

        # IMPORTANTE:
        # permanece falso enquanto
        # o método estiver experimental.
        "validado_para_eta":
            False,

        "distancia_centroide_comasa_km":
            round(
                distancia_atual,
                2,
            ),

        "rumo_movimento_graus":
            round(
                rumo_medio,
                1,
            ),

        "rumo_movimento_cardinal":
            cardinal(
                rumo_medio
            ),

        "rumo_para_comasa_graus":
            round(
                rumo_para_comasa,
                1,
            ),

        "rumo_para_comasa_cardinal":
            cardinal(
                rumo_para_comasa
            ),

        "diferenca_angular_graus":
            round(
                diferenca_angular,
                1,
            ),

        "dispersao_direcao_media_graus":
            round(
                dispersao_media,
                1,
            ),

        "dispersao_direcao_max_graus":
            round(
                dispersao_max,
                1,
            ),

        "distancia_lateral_trajetoria_km":
            round(
                distancia_lateral,
                2,
            ),

        "corredor_tolerancia_km":
            corredor,

        "projecao_adiante_km":
            round(
                projecao_adiante,
                2,
            ),

        "velocidade_recente_media_kmh":
            round(
                velocidade_media,
                1,
            ),

        "radar_fresco":
            radar_fresco,

        "idade_radar_min":
            idade_radar,

        "horario_ultimo_quadro":
            horario_ultimo_quadro.isoformat(),

        "criterios": {
            "minimo_transicoes":
                3,

            "score_minimo":
                0.55,

            "diferenca_angular_max_graus":
                40,

            "dispersao_direcao_max_graus":
                45,

            "corredor_km":
                corredor,

            "velocidade_min_kmh":
                5,

            "velocidade_max_kmh":
                120,

            "horizonte_max_min":
                180,

            "idade_max_radar_min":
                30,
        },
    }

    if not radar_fresco:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Radar desatualizado: "
                    f"{idade_radar} min."
                ),

            "eta":
                None,
        }

    if (
        trilha.get(
            "score_medio",
            0,
        ) < 0.55
    ):
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Confiança geométrica "
                    "insuficiente."
                ),

            "eta":
                None,
        }

    if (
        trilha.get(
            "tendencia_relativa_comasa"
        )
        != "aproximando"
    ):
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Trilha não apresenta "
                    "aproximação persistente."
                ),

            "eta":
                None,
        }

    if not direcao_estavel:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Trajetória recente "
                    "instável ou em zigue-zague."
                ),

            "eta":
                None,
        }

    if not aponta_para_frente:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Comasa está atrás do "
                    "vetor de deslocamento."
                ),

            "eta":
                None,
        }

    if not angulo_compativel:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Vetor médio não aponta "
                    "suficientemente para "
                    "o Comasa."
                ),

            "eta":
                None,
        }

    if (
        distancia_lateral
        > corredor
    ):
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Trajetória projetada "
                    "passa fora do corredor "
                    "de 15 km do Comasa."
                ),

            "eta":
                None,
        }

    if velocidade_media < 5:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Velocidade insuficiente "
                    "para estimativa de ETA."
                ),

            "eta":
                None,
        }

    # =====================================================
    # ENTRADA NO CORREDOR DE 15 KM
    # =====================================================

    # Posição inicial r=(px,py)
    # trajetória r + u*s
    #
    # |r + u*s|² = corredor²
    #
    # s² + 2(r.u)s + |r|²-R² = 0

    produto = (
        px * ux
        + py * uy
    )

    c = (
        px * px
        + py * py
        - corredor * corredor
    )

    discriminante = (
        produto * produto
        - c
    )

    if distancia_atual <= corredor:
        distancia_entrada = 0.0

    elif discriminante < 0:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Linha projetada não "
                    "intercepta matematicamente "
                    "o corredor do Comasa."
                ),

            "eta":
                None,
        }

    else:
        raiz = math.sqrt(
            discriminante
        )

        s1 = (
            -produto
            - raiz
        )

        s2 = (
            -produto
            + raiz
        )

        positivos = [
            s
            for s in (s1, s2)
            if s >= 0
        ]

        if not positivos:
            return {
                **base,

                "status":
                    "bloqueado",

                "motivo":
                    (
                        "Interseção calculada "
                        "está atrás da direção "
                        "de deslocamento."
                    ),

                "eta":
                    None,
            }

        distancia_entrada = min(
            positivos
        )

    minutos_entrada = (
        distancia_entrada
        / velocidade_media
        * 60
    )

    if (
        minutos_entrada < 0
        or minutos_entrada > 180
    ):
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "Interseção fora da "
                    "janela experimental "
                    "de 0 a 180 minutos."
                ),

            "eta":
                None,
        }

    horario_entrada = (
        horario_ultimo_quadro
        + timedelta(
            minutes=minutos_entrada
        )
    )

    agora_utc = datetime.now(
        UTC
    )

    # Se o quadro é antigo e a projeção
    # aponta para um evento que já teria
    # ocorrido, a ETA não pode ser usada.
    if horario_entrada < agora_utc:
        return {
            **base,

            "status":
                "bloqueado",

            "motivo":
                (
                    "A projeção calculada "
                    "já estaria no passado "
                    "em relação ao horário "
                    "atual."
                ),

            "eta":
                None,
        }

    incerteza = max(
        10,
        min(
            30,
            round(
                minutos_entrada
                * 0.25
            ),
        ),
    )

    janela_inicio = (
        horario_entrada
        - timedelta(
            minutes=incerteza
        )
    )

    janela_fim = (
        horario_entrada
        + timedelta(
            minutes=incerteza
        )
    )

    if (
        trilha["transicoes"] >= 5
        and trilha["score_medio"]
        >= 0.70
        and diferenca_angular <= 20
        and dispersao_max <= 25
        and distancia_lateral <= 7.5
    ):
        confianca = "alta_experimental"

    elif (
        trilha["transicoes"] >= 4
        and trilha["score_medio"]
        >= 0.60
        and dispersao_max <= 35
    ):
        confianca = "moderada_experimental"

    else:
        confianca = "baixa_experimental"

    return {
        **base,

        "status":
            "candidato_eta_experimental",

        "candidato_eta":
            True,

        # Continua propositalmente FALSE.
        "validado_para_eta":
            False,

        "motivo":
            (
                "Trilha persistente, radar "
                "fresco e trajetória "
                "multivetorial compatível "
                "com o corredor do Comasa."
            ),

        "eta": {
            "referencia":
                "entrada_no_corredor_15_km",

            "minutos_desde_ultimo_quadro":
                round(
                    minutos_entrada
                ),

            "horario_central":
                horario_entrada
                .astimezone(FUSO)
                .isoformat(),

            "janela_inicio":
                janela_inicio
                .astimezone(FUSO)
                .isoformat(),

            "janela_fim":
                janela_fim
                .astimezone(FUSO)
                .isoformat(),

            "incerteza_min":
                incerteza,

            "confianca":
                confianca,

            "observacao":
                (
                    "Estimativa exclusivamente "
                    "experimental. Células podem "
                    "intensificar, dissipar, "
                    "acelerar ou mudar de direção."
                ),
        },
    }


def avaliar_todas_trilhas(
    rastreamento,
    radar_fresco,
    idade_radar,
    horario_ultimo_quadro,
):
    trilhas = (
        rastreamento.get(
            "trilhas",
            []
        )
    )

    elegiveis = [
        trilha
        for trilha in trilhas

        if trilha.get(
            "elegivel_para_analise"
        )
    ]

    avaliacoes = []

    for trilha in elegiveis:
        resultado = analisar_interceptacao(
            trilha,
            radar_fresco,
            idade_radar,
            horario_ultimo_quadro,
        )

        avaliacoes.append({
            "id_trilha":
                trilha[
                    "id_trilha"
                ],

            "transicoes":
                trilha[
                    "transicoes"
                ],

            "score_medio":
                trilha[
                    "score_medio"
                ],

            "ultima_distancia_comasa_km":
                trilha[
                    "ultima_distancia_comasa_km"
                ],

            "resultado":
                resultado,
        })

    candidatos = [
        item
        for item in avaliacoes

        if item[
            "resultado"
        ].get(
            "candidato_eta"
        )
    ]

    candidatos.sort(
        key=lambda item: (
            item[
                "resultado"
            ][
                "eta"
            ][
                "minutos_desde_ultimo_quadro"
            ],

            item[
                "resultado"
            ][
                "distancia_lateral_trajetoria_km"
            ],

            -item[
                "score_medio"
            ],
        )
    )

    selecionado = (
        candidatos[0]
        if candidatos
        else None
    )

    return {
        "status":
            "avaliacao_multiplas_trilhas",

        "quantidade_trilhas_avaliadas":
            len(avaliacoes),

        "quantidade_candidatos_eta":
            len(candidatos),

        "avaliacoes":
            avaliacoes,

        "candidato_selecionado":
            selecionado,

        "validado_para_eta":
            False,

        "observacao":
            (
                "Mesmo quando existe candidato, "
                "o ETA permanece experimental "
                "e não validado para publicação "
                "operacional."
            ),
    }


# =========================================================
# DOWNLOAD DO RADAR
# =========================================================

def baixar(nome):
    bruto = get(
        IMAGEM,
        {
            "prod": 4,
            "radar": "COMP",
            "file": nome,
        },
        True,
    ).content

    if not bruto.startswith(
        b"\x89PNG\r\n\x1a\n"
    ):
        raise ValueError(
            "Resposta não é PNG válido."
        )

    imagem = Image.open(
        io.BytesIO(bruto)
    )

    return {
        "bytes":
            len(bruto),

        "sha256":
            hashlib
            .sha256(bruto)
            .hexdigest(),

        "largura_px":
            imagem.width,

        "altura_px":
            imagem.height,

        "modo_png_original":
            imagem.mode,

        "diagnostico_paleta_png":
            diagnostico(
                imagem
            ),

        "analise_espacial":
            analisar(
                imagem
            ),
    }


# =========================================================
# RADAR
# =========================================================

def buscar_radar():
    try:
        leg = legenda()

        nomes = get(
            LISTA,
            {
                "prod": 4,
                "radar": "COMP",
                "data": "",
            },
            True,
        ).json()

        if (
            not isinstance(
                nomes,
                list,
            )
            or not nomes
        ):
            raise ValueError(
                "Radar não retornou "
                "lista de imagens."
            )

        nomes = nomes[-7:]

        quadros = []

        for nome in nomes:
            try:
                horario_utc = (
                    datetime.strptime(
                        nome[:14],
                        "%Y%m%d%H%M%S",
                    )
                    .replace(
                        tzinfo=UTC
                    )
                )

                horario_local = (
                    horario_utc
                    .astimezone(FUSO)
                )

                quadros.append({
                    "arquivo":
                        nome,

                    "horario_utc":
                        horario_utc
                        .isoformat(),

                    "horario_local":
                        horario_local
                        .isoformat(),

                    "download":
                        "ok",

                    **baixar(nome),
                })

            except Exception as e:
                quadros.append({
                    "arquivo":
                        nome,

                    "download":
                        "erro",

                    "erro":
                        str(e),
                })

        validos = [
            q
            for q in quadros
            if q.get(
                "download"
            ) == "ok"
        ]

        if not validos:
            raise ValueError(
                "Nenhum PNG válido."
            )

        ultimo = validos[-1]

        horario_ultimo = (
            datetime.fromisoformat(
                ultimo[
                    "horario_utc"
                ]
            )
        )

        idade = max(
            0,
            round(
                (
                    datetime.now(UTC)
                    - horario_ultimo
                )
                .total_seconds()
                / 60,
                1,
            ),
        )

        fresco = idade <= 30

        serie = []

        for quadro in validos:
            analise = quadro[
                "analise_espacial"
            ]

            serie.append({
                "horario_local":
                    quadro[
                        "horario_local"
                    ],

                "pixels_candidatos":
                    analise.get(
                        "pixels_candidatos"
                    ),

                "componentes":
                    analise.get(
                        "quantidade_componentes_3px_ou_mais"
                    ),

                "eco_mais_proximo":
                    analise.get(
                        "eco_mais_proximo"
                    ),

                "pixels_por_raio":
                    analise.get(
                        "pixels_por_raio"
                    ),
            })

        rastreamento = rastrear(
            validos
        )

        avaliacao = avaliar_todas_trilhas(
            rastreamento,
            fresco,
            idade,
            horario_ultimo,
        )

        selecionado = avaliacao.get(
            "candidato_selecionado"
        )

        # Mantemos uma trilha principal apenas
        # para diagnóstico e compatibilidade.
        principal = (
            rastreamento.get(
                "trilha_principal_diagnostica"
            )
        )

        movimento = {
            "status":
                "sem_trilha_elegivel",

            "validado_para_eta":
                False,

            "candidato_eta":
                False,
        }

        if principal:
            movimento = {
                "status":
                    "diagnostico_disponivel",

                "metodo":
                    (
                        "rastreamento_de_componentes"
                        "_multivetorial"
                    ),

                "trilha_id":
                    principal[
                        "id_trilha"
                    ],

                "transicoes":
                    principal[
                        "transicoes"
                    ],

                "score_medio":
                    principal[
                        "score_medio"
                    ],

                "tendencia":
                    principal[
                        "tendencia_relativa_comasa"
                    ],

                "velocidade_media_kmh":
                    principal[
                        "velocidade_media_kmh"
                    ],

                "distancia_atual_comasa_km":
                    principal[
                        "ultima_distancia_comasa_km"
                    ],

                "direcao_movimento":
                    principal[
                        "ultima_direcao_movimento"
                    ],

                # Nunca verdadeiro no #117.
                "validado_para_eta":
                    False,

                "candidato_eta":
                    bool(
                        selecionado
                    ),
            }

        if selecionado:
            inter = selecionado[
                "resultado"
            ]

        else:
            # Quando nenhuma trilha passa pelos
            # critérios, guardamos um diagnóstico
            # representativo da principal.
            if principal:
                inter = analisar_interceptacao(
                    principal,
                    fresco,
                    idade,
                    horario_ultimo,
                )

            else:
                inter = {
                    "status":
                        "bloqueado",

                    "intercepta_corredor":
                        False,

                    "candidato_eta":
                        False,

                    "validado_para_eta":
                        False,

                    "motivo":
                        (
                            "Nenhuma trilha "
                            "elegível disponível."
                        ),

                    "eta":
                        None,
                }

        eta = {
            "status":
                "bloqueado",

            "candidato":
                False,

            "validado":
                False,

            "janela_chegada":
                None,

            "motivo":
                inter.get(
                    "motivo"
                ),
        }

        if (
            selecionado
            and inter.get("eta")
        ):
            e = inter["eta"]

            eta = {
                "status":
                    "experimental_nao_publicar",

                "candidato":
                    True,

                "validado":
                    False,

                "trilha_id":
                    selecionado[
                        "id_trilha"
                    ],

                "estimativa_central":
                    e[
                        "horario_central"
                    ],

                "janela_chegada": {
                    "inicio":
                        e[
                            "janela_inicio"
                        ],

                    "fim":
                        e[
                            "janela_fim"
                        ],
                },

                "minutos_desde_ultimo_quadro":
                    e[
                        "minutos_desde_ultimo_quadro"
                    ],

                "confianca":
                    e[
                        "confianca"
                    ],

                "motivo":
                    inter[
                        "motivo"
                    ],

                "observacao":
                    e[
                        "observacao"
                    ],
            }

        return {
            "status":
                (
                    "online"
                    if (
                        fresco
                        and len(validos)
                        == len(nomes)
                    )
                    else "parcial"
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
                EXT,

            "quantidade_quadros":
                len(nomes),

            "quadros_png_validos":
                len(validos),

            "todos_png_validos":
                (
                    len(validos)
                    == len(nomes)
                ),

            "dimensoes_consistentes":
                len({
                    (
                        q["largura_px"],
                        q["altura_px"],
                    )

                    for q
                    in validos
                }) == 1,

            "horario_ultimo_quadro":
                ultimo[
                    "horario_local"
                ],

            "idade_ultimo_quadro_min":
                idade,

            "dados_frescos":
                fresco,

            "limite_frescor_min":
                30,

            "legenda_oficial":
                leg,

            "metodo_eco": {
                "status":
                    "experimental_validacao",

                "fundo":
                    "alpha_zero_excluido",

                "cinza_200_200_200":
                    (
                        "excluido_ate_validacao"
                    ),

                "demais_pixels_visiveis":
                    (
                        "candidatos_meteorologicos"
                    ),

                "dbz":
                    "nao_atribuido",
            },

            "serie_espacial":
                serie,

            "rastreamento_temporal":
                rastreamento,

            "avaliacao_trajetorias":
                avaliacao,

            "interceptacao_trajetoria":
                inter,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "analise_geografica": {
                "status":
                    "ativa",

                "referencia":
                    (
                        "Comasa - coordenada "
                        "pública aproximada"
                    ),

                "ultimo":
                    ultimo.get(
                        "analise_espacial"
                    ),
            },

            "analise_movimento":
                movimento,

            "interpretacao_dbz":
                (
                    "aguardando_validacao_numerica"
                ),

            "eta":
                eta,

            "seguranca_eta": {
                "status":
                    "experimental",

                "publicacao_automatica":
                    False,

                "validado_para_eta":
                    False,

                "regra":
                    (
                        "Nenhum ETA do #117 "
                        "deve ser tratado como "
                        "previsão operacional "
                        "antes de validação "
                        "observacional."
                    ),
            },
        }

    except Exception as e:
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
                str(e),
        }


# =========================================================
# ARQUIVO FINAL
# =========================================================

def main():
    dados = {
        "monitor":
            "Monitor Guaxanduva",

        "local":
            "Comasa - Joinville/SC",

        "gerado_em":
            agora().isoformat(),

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
            buscar_mare(),

        "rio": {
            "nome":
                "Rio Guaxanduva",

            "status":
                "sem_sensor_publico_confirmado",

            "nivel_m":
                None,
        },

        "previsao":
            buscar_previsao(),

        "radar":
            buscar_radar(),

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

    print(
        json.dumps(
            dados["radar"],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
