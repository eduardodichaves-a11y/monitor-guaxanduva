import json
import hashlib
import io
import math
from collections import Counter, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3
from PIL import Image


ARQUIVO = "dados.json"

# Coordenada pública aproximada do Comasa.
# NÃO representa endereço residencial.
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

URL_RADAR_LISTA = (
    URL_RADAR_SITE
    + "rest/radar/getUltimasImagens"
)

URL_RADAR_IMAGEM = (
    URL_RADAR_SITE
    + "rest/radar/getImagem"
)

URL_RADAR_LEGENDA = (
    URL_RADAR_SITE
    + "img/legenda.png"
)

# Extensão oficial COMP:
# [oeste, sul, leste, norte]
RADAR_EXTENT = [
    -58.0651279,
    -33.8163446,
    -46.4999942,
    -24.7653703,
]

# Cor que apareceu maciçamente nos PNGs,
# mas cujo significado meteorológico ainda
# NÃO foi comprovado.
RGB_CINZA_NAO_VALIDADO = (200, 200, 200)

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# UTILIDADES
# =========================================================

def agora_local():
    return datetime.now(FUSO_LOCAL)


def requisicao_normal(url, params=None):
    r = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent":
                "Monitor-Guaxanduva/1.0"
        },
    )

    r.raise_for_status()
    return r


def requisicao_radar(url, params=None):
    """
    verify=False SOMENTE para o SIFAP,
    devido ao problema já verificado na
    cadeia/certificado apresentado pelo
    serviço oficial.
    """

    r = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent":
                "Monitor-Guaxanduva/1.0"
        },
        verify=False,
    )

    r.raise_for_status()
    return r


def haversine_km(
    lat1,
    lon1,
    lat2,
    lon2,
):
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

    c = 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

    return raio * c


def rumo_graus(
    lat1,
    lon1,
    lat2,
    lon2,
):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)

    y = (
        math.sin(dl)
        * math.cos(p2)
    )

    x = (
        math.cos(p1)
        * math.sin(p2)
        - math.sin(p1)
        * math.cos(p2)
        * math.cos(dl)
    )

    return (
        math.degrees(
            math.atan2(y, x)
        )
        + 360
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
        (graus + 22.5)
        // 45
    ) % 8

    return nomes[indice]


# =========================================================
# PIXEL ↔ COORDENADA
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
        (longitude - oeste)
        / (leste - oeste)
        * (largura - 1)
    )

    y = round(
        (norte - latitude)
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
        + x / (largura - 1)
        * (leste - oeste)
    )

    latitude = (
        norte
        - y / (altura - 1)
        * (norte - sul)
    )

    return latitude, longitude


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
                    datetime
                    .fromisoformat(tempo)
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
# MARÉ
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

            if data.strip() != data_hoje:
                continue

            try:
                altura_m = float(
                    altura
                    .strip()
                    .replace(",", ".")
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
            key=lambda e:
                datetime.strptime(
                    e["hora"],
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
# LEGENDA OFICIAL
# =========================================================

def segmentos_de_linha(
    imagem,
    y,
):
    largura, altura = imagem.size

    if y < 0 or y >= altura:
        return []

    segmentos = []

    cor_atual = imagem.getpixel(
        (0, y)
    )

    inicio = 0

    for x in range(
        1,
        largura,
    ):
        cor = imagem.getpixel(
            (x, y)
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
                    list(cor_atual),
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
            list(cor_atual),
    })

    return segmentos


def extrair_paleta_oficial():
    try:
        r = requisicao_radar(
            URL_RADAR_LEGENDA
        )

        conteudo = r.content

        imagem = Image.open(
            io.BytesIO(conteudo)
        ).convert("RGBA")

        largura, altura = imagem.size

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
                "Faixa colorida da "
                "legenda não encontrada."
            )

        candidatos.sort(
            key=lambda item: (
                item["quantidade"],
                item["largura_total"],
            ),
            reverse=True,
        )

        melhor = candidatos[0]

        segmentos = melhor[
            "segmentos"
        ]

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
                "Quantidade inesperada "
                "de classes: "
                f"{len(segmentos)}"
            )

        classes = []

        for indice, segmento in enumerate(
            segmentos,
            start=1,
        ):
            classes.append({
                "classe":
                    indice,

                "rgb":
                    segmento[
                        "rgba"
                    ][:3],

                "dbz":
                    None,
            })

        return {
            "status":
                "online",

            "fonte":
                "legenda oficial RadarSC",

            "sha256":
                hashlib.sha256(
                    conteudo
                ).hexdigest(),

            "quantidade_classes":
                len(classes),

            "classes":
                classes,

            "dbz_numerico":
                "aguardando_validacao",
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "erro":
                str(erro),
        }


# =========================================================
# PALETA PNG
# =========================================================

def transparencia_por_indice(
    transparencia,
    indice,
):
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

    if isinstance(
        transparencia,
        (bytes, bytearray),
    ):
        if indice < len(
            transparencia
        ):
            return int(
                transparencia[indice]
            )

    return 255


def rgb_do_indice(
    paleta,
    indice,
):
    pos = indice * 3

    if (
        paleta is None
        or pos + 2 >= len(paleta)
    ):
        return None

    return (
        paleta[pos],
        paleta[pos + 1],
        paleta[pos + 2],
    )


def diagnosticar_paleta_png(
    imagem,
):
    largura, altura = imagem.size

    resultado = {
        "modo_original":
            imagem.mode,

        "largura_px":
            largura,

        "altura_px":
            altura,
    }

    if imagem.mode != "P":
        resultado["status"] = (
            "modo_inesperado"
        )

        return resultado

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

    total_visivel = 0
    total_transparente = 0
    total_cinza = 0
    total_candidato = 0

    for indice, pixels in sorted(
        contagem.items()
    ):
        rgb = rgb_do_indice(
            paleta,
            indice,
        )

        alpha = (
            transparencia_por_indice(
                transparencia,
                indice,
            )
        )

        visivel = alpha > 0

        cinza = (
            rgb
            == RGB_CINZA_NAO_VALIDADO
        )

        candidato = (
            visivel
            and not cinza
        )

        if visivel:
            total_visivel += pixels
        else:
            total_transparente += pixels

        if cinza:
            total_cinza += pixels

        if candidato:
            total_candidato += pixels

        itens.append({
            "indice_p":
                int(indice),

            "rgb":
                (
                    list(rgb)
                    if rgb
                    else None
                ),

            "alpha":
                alpha,

            "pixels":
                pixels,

            "visivel":
                visivel,

            "cinza_nao_validado":
                cinza,

            "candidato_meteorologico":
                candidato,
        })

    resultado.update({
        "status":
            "online",

        "total_pixels":
            largura * altura,

        "pixels_transparentes":
            total_transparente,

        "pixels_visiveis":
            total_visivel,

        "pixels_cinza_nao_validado":
            total_cinza,

        "pixels_candidatos_meteorologicos":
            total_candidato,

        "indices_usados":
            itens,

        "observacao": (
            "Cinza 200,200,200 foi "
            "deliberadamente excluído da "
            "interpretação meteorológica "
            "até validação."
        ),
    })

    return resultado


# =========================================================
# MÁSCARA DE ECOS CANDIDATOS
# =========================================================

def construir_mascara_candidata(
    imagem,
):
    """
    Retorna conjunto de coordenadas (x,y)
    consideradas candidatas a eco.

    Critérios:
    - PNG modo P;
    - alpha > 0;
    - RGB diferente de 200,200,200.

    Não atribui dBZ.
    """

    if imagem.mode != "P":
        return set(), {}

    largura, altura = imagem.size

    paleta = imagem.getpalette()

    transparencia = (
        imagem.info.get(
            "transparency"
        )
    )

    indices_candidatos = {}

    for indice in set(
        imagem.getdata()
    ):
        rgb = rgb_do_indice(
            paleta,
            indice,
        )

        alpha = (
            transparencia_por_indice(
                transparencia,
                indice,
            )
        )

        if (
            alpha > 0
            and rgb is not None
            and rgb
            != RGB_CINZA_NAO_VALIDADO
        ):
            indices_candidatos[
                indice
            ] = rgb

    mascara = set()

    pixels = imagem.load()

    for y in range(altura):
        for x in range(largura):
            indice = pixels[x, y]

            if indice in indices_candidatos:
                mascara.add(
                    (x, y)
                )

    return (
        mascara,
        indices_candidatos,
    )


# =========================================================
# COMPONENTES CONECTADOS
# =========================================================

def encontrar_componentes(
    mascara,
    largura,
    altura,
):
    """
    Agrupa pixels vizinhos usando
    conectividade de 8 direções.

    Componentes com menos de 3 pixels
    permanecem fora da lista principal
    para reduzir ruído pontual.

    Isso ainda NÃO significa que cada
    componente seja uma tempestade.
    """

    nao_visitados = set(
        mascara
    )

    componentes = []

    vizinhos = [
        (-1, -1),
        (0, -1),
        (1, -1),
        (-1, 0),
        (1, 0),
        (-1, 1),
        (0, 1),
        (1, 1),
    ]

    while nao_visitados:
        inicio = nao_visitados.pop()

        fila = deque(
            [inicio]
        )

        pontos = [
            inicio
        ]

        while fila:
            x, y = fila.popleft()

            for dx, dy in vizinhos:
                nx = x + dx
                ny = y + dy

                ponto = (
                    nx,
                    ny,
                )

                if ponto in nao_visitados:
                    nao_visitados.remove(
                        ponto
                    )

                    fila.append(
                        ponto
                    )

                    pontos.append(
                        ponto
                    )

        if len(pontos) >= 3:
            componentes.append(
                pontos
            )

    componentes.sort(
        key=len,
        reverse=True,
    )

    return componentes


# =========================================================
# GEOGRAFIA DE UM COMPONENTE
# =========================================================

def resumir_componente(
    pontos,
    imagem,
):
    largura, altura = imagem.size

    paleta = imagem.getpalette()

    xs = [
        p[0]
        for p in pontos
    ]

    ys = [
        p[1]
        for p in pontos
    ]

    centro_x = (
        sum(xs)
        / len(xs)
    )

    centro_y = (
        sum(ys)
        / len(ys)
    )

    lat_centro, lon_centro = (
        pixel_para_coordenada(
            centro_x,
            centro_y,
            largura,
            altura,
        )
    )

    distancia_centro = (
        haversine_km(
            LAT,
            LON,
            lat_centro,
            lon_centro,
        )
    )

    rumo_centro = (
        rumo_graus(
            LAT,
            LON,
            lat_centro,
            lon_centro,
        )
    )

    distancia_minima = None
    ponto_minimo = None

    cores = Counter()

    pixels = imagem.load()

    for x, y in pontos:
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

        if (
            distancia_minima is None
            or distancia
            < distancia_minima
        ):
            distancia_minima = (
                distancia
            )

            ponto_minimo = (
                x,
                y,
                lat,
                lon,
            )

        indice = pixels[x, y]

        rgb = rgb_do_indice(
            paleta,
            indice,
        )

        if rgb:
            cores[rgb] += 1

    cores_lista = [
        {
            "rgb":
                list(rgb),

            "pixels":
                quantidade,
        }
        for rgb, quantidade
        in cores.most_common()
    ]

    if ponto_minimo:
        (
            px,
            py,
            lat_min,
            lon_min,
        ) = ponto_minimo

        rumo_minimo = (
            rumo_graus(
                LAT,
                LON,
                lat_min,
                lon_min,
            )
        )

        ponto_proximo = {
            "pixel_x":
                px,

            "pixel_y":
                py,

            "latitude":
                round(
                    lat_min,
                    5,
                ),

            "longitude":
                round(
                    lon_min,
                    5,
                ),

            "distancia_comasa_km":
                round(
                    distancia_minima,
                    2,
                ),

            "direcao_graus":
                round(
                    rumo_minimo,
                    1,
                ),

            "direcao_cardinal":
                ponto_cardinal(
                    rumo_minimo
                ),
        }

    else:
        ponto_proximo = None

    return {
        "pixels":
            len(pontos),

        "centroide": {
            "pixel_x":
                round(
                    centro_x,
                    1,
                ),

            "pixel_y":
                round(
                    centro_y,
                    1,
                ),

            "latitude":
                round(
                    lat_centro,
                    5,
                ),

            "longitude":
                round(
                    lon_centro,
                    5,
                ),

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
                ponto_cardinal(
                    rumo_centro
                ),
        },

        "ponto_mais_proximo_comasa":
            ponto_proximo,

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

        "cores":
            cores_lista,

        "dbz":
            None,

        "classificacao":
            "candidato_a_area_de_eco",
    }


# =========================================================
# ANÁLISE ESPACIAL COMPLETA
# =========================================================

def analisar_espacialmente(
    imagem,
):
    largura, altura = imagem.size

    mascara, indices = (
        construir_mascara_candidata(
            imagem
        )
    )

    x_comasa, y_comasa = (
        coordenada_para_pixel(
            LON,
            LAT,
            largura,
            altura,
        )
    )

    if not mascara:
        return {
            "status":
                "sem_pixels_candidatos",

            "pixel_comasa": {
                "x":
                    x_comasa,

                "y":
                    y_comasa,
            },

            "pixels_candidatos":
                0,

            "componentes":
                [],
        }

    # Contagem de pixels por distância.
    raios = {
        10: 0,
        25: 0,
        50: 0,
        100: 0,
    }

    eco_mais_proximo = None

    for x, y in mascara:
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

        for raio in raios:
            if distancia <= raio:
                raios[raio] += 1

        if (
            eco_mais_proximo is None
            or distancia
            < eco_mais_proximo[
                "_distancia"
            ]
        ):
            direcao = (
                rumo_graus(
                    LAT,
                    LON,
                    lat,
                    lon,
                )
            )

            eco_mais_proximo = {
                "_distancia":
                    distancia,

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
            }

    if eco_mais_proximo:
        eco_mais_proximo.pop(
            "_distancia",
            None,
        )

    componentes_brutos = (
        encontrar_componentes(
            mascara,
            largura,
            altura,
        )
    )

    componentes = []

    # Guardamos até os 30 maiores
    # componentes no JSON.
    for numero, pontos in enumerate(
        componentes_brutos[:30],
        start=1,
    ):
        resumo = resumir_componente(
            pontos,
            imagem,
        )

        resumo["id_quadro"] = (
            numero
        )

        componentes.append(
            resumo
        )

    componentes_por_distancia = (
        sorted(
            componentes,
            key=lambda c:
                c[
                    "ponto_mais_proximo_comasa"
                ][
                    "distancia_comasa_km"
                ],
        )
    )

    return {
        "status":
            "diagnostico_espacial_ativo",

        "metodo":
            "componentes_conectados_8_vizinhos",

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

        "pixels_candidatos":
            len(mascara),

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
            eco_mais_proximo,

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
            len(componentes_brutos),

        "maiores_componentes":
            componentes,

        "componentes_mais_proximos_comasa":
            componentes_por_distancia[:10],

        "observacao": (
            "Componentes são candidatos "
            "geométricos a áreas de eco. "
            "Ainda não representam células "
            "meteorológicas individualmente "
            "confirmadas."
        ),
    }


# =========================================================
# DOWNLOAD DO QUADRO
# =========================================================

def baixar_quadro(nome):
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
        io.BytesIO(conteudo)
    )

    largura, altura = imagem.size

    diagnostico_paleta = (
        diagnosticar_paleta_png(
            imagem
        )
    )

    analise_espacial = (
        analisar_espacialmente(
            imagem
        )
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

        "modo_png_original":
            imagem.mode,

        "diagnostico_paleta_png":
            diagnostico_paleta,

        "analise_espacial":
            analise_espacial,
    }


# =========================================================
# RADAR
# =========================================================

def buscar_radar():
    try:
        legenda = (
            extrair_paleta_oficial()
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
                "não é lista."
            )

        if not imagens:
            raise ValueError(
                "Radar não retornou "
                "imagens."
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
                        nome
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

                    **resultado,
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
            q
            for q in quadros
            if q.get("download")
            == "ok"
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

        idade = max(
            0,
            round(
                (
                    datetime.now(UTC)
                    - ultimo_utc
                )
                .total_seconds()
                / 60,
                1,
            ),
        )

        fresco = idade <= 30

        dimensoes = {
            (
                q["largura_px"],
                q["altura_px"],
            )
            for q in validos
        }

        # Série espacial dos sete quadros.
        serie_espacial = []

        for quadro in validos:
            analise = quadro.get(
                "analise_espacial",
                {},
            )

            eco = analise.get(
                "eco_mais_proximo"
            )

            serie_espacial.append({
                "horario_local":
                    quadro.get(
                        "horario_local"
                    ),

                "pixels_candidatos":
                    analise.get(
                        "pixels_candidatos"
                    ),

                "componentes":
                    analise.get(
                        "quantidade_componentes_3px_ou_mais"
                    ),

                "eco_mais_proximo":
                    eco,

                "pixels_por_raio":
                    analise.get(
                        "pixels_por_raio"
                    ),
            })

        return {
            "status":
                (
                    "online"
                    if (
                        fresco
                        and len(validos)
                        == len(imagens)
                    )
                    else "parcial"
                ),

            "fonte": (
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
                len(dimensoes) == 1,

            "idade_ultimo_quadro_min":
                idade,

            "dados_frescos":
                fresco,

            "legenda_oficial":
                legenda,

            "metodo_eco": {
                "status":
                    "experimental_validacao",

                "fundo":
                    "alpha_zero_excluido",

                "cinza_200_200_200":
                    "excluido_ate_validacao",

                "demais_pixels_visiveis":
                    "candidatos_meteorologicos",

                "dbz":
                    "nao_atribuido",
            },

            "serie_espacial":
                serie_espacial,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "analise_geografica": {
                "status":
                    "ativa",

                "referencia": (
                    "Comasa - coordenada "
                    "pública aproximada"
                ),

                "ultimo":
                    ultimo.get(
                        "analise_espacial"
                    ),
            },

            # NÃO liberamos movimento ainda.
            # Primeiro veremos se os
            # componentes formados são
            # espacialmente coerentes.
            "analise_movimento": {
                "status":
                    "aguardando_validacao_"
                    "dos_componentes",

                "tendencia":
                    None,

                "velocidade_kmh":
                    None,

                "direcao":
                    None,
            },

            "interpretacao_dbz":
                "aguardando_validacao_"
                "numerica",

            "eta": {
                "status":
                    "bloqueado",

                "janela_chegada":
                    None,

                "motivo": (
                    "ETA somente após "
                    "rastreamento confiável "
                    "da mesma área de eco "
                    "entre quadros e somente "
                    "com radar fresco."
                ),
            },
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "fonte": (
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

            "fonte": (
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
