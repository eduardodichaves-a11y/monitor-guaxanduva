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

URL_RADAR = "https://sifap.defesacivil.sc.gov.br/radarsc/"

URL_RADAR_LISTA = URL_RADAR + "rest/radar/getUltimasImagens"
URL_RADAR_IMAGEM = URL_RADAR + "rest/radar/getImagem"
URL_RADAR_LEGENDA = URL_RADAR + "img/legenda.png"

RADAR_EXTENT = [
    -58.0651279,
    -33.8163446,
    -46.4999942,
    -24.7653703,
]

RGB_CINZA_NAO_VALIDADO = (200, 200, 200)

urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# UTILIDADES
# =========================================================

def agora_local():
    return datetime.now(FUSO_LOCAL)


def get_normal(url, params=None):
    r = requests.get(
        url,
        params=params,
        timeout=30,
        headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
    )
    r.raise_for_status()
    return r


def get_radar(url, params=None):
    # verify=False apenas no SIFAP/RadarSC,
    # devido ao problema de certificado já verificado.
    r = requests.get(
        url,
        params=params,
        timeout=30,
        headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
        verify=False,
    )
    r.raise_for_status()
    return r


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088

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

    return r * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )


def rumo_graus(lat1, lon1, lat2, lon2):
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


def ponto_cardinal(graus):
    if graus is None:
        return None

    nomes = [
        "N", "NE", "L", "SE",
        "S", "SO", "O", "NO",
    ]

    return nomes[
        int((graus + 22.5) // 45) % 8
    ]


def diferenca_angular(a, b):
    if a is None or b is None:
        return None

    return abs(
        (a - b + 180) % 360 - 180
    )


# =========================================================
# PIXEL / GEOGRAFIA
# =========================================================

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

    return (
        max(0, min(largura - 1, x)),
        max(0, min(altura - 1, y)),
    )


def pixel_para_coordenada(
    x,
    y,
    largura,
    altura,
):
    oeste, sul, leste, norte = RADAR_EXTENT

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
    try:
        url = "https://api.open-meteo.com/v1/forecast"

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

        resposta = get_normal(
            url,
            params,
        ).json()

        atual = resposta.get("current", {})
        hourly = resposta.get("hourly", {})
        daily = resposta.get("daily", {})

        agora = agora_local()
        indice = None

        for i, tempo in enumerate(
            hourly.get("time", [])
        ):
            try:
                momento = datetime.fromisoformat(
                    tempo
                ).replace(
                    tzinfo=FUSO_LOCAL
                )

                if momento > agora:
                    indice = i
                    break
            except Exception:
                pass

        def hv(nome):
            if indice is None:
                return None

            lista = hourly.get(nome, [])

            if indice >= len(lista):
                return None

            return lista[indice]

        dias = []

        for i, data in enumerate(
            daily.get("time", [])
        ):
            def dv(nome):
                lista = daily.get(nome, [])
                return (
                    lista[i]
                    if i < len(lista)
                    else None
                )

            dias.append({
                "data": data,
                "probabilidade_chuva_pct":
                    dv("precipitation_probability_max"),
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
                    atual.get("wind_direction_10m"),
                "rajada_kmh":
                    atual.get("wind_gusts_10m"),
            },

            "proxima_hora": {
                "horario":
                    hv("time"),
                "probabilidade_chuva_pct":
                    hv("precipitation_probability"),
                "precipitacao_mm":
                    hv("precipitation"),
                "vento_kmh":
                    hv("wind_speed_10m"),
                "direcao_graus":
                    hv("wind_direction_10m"),
                "rajada_kmh":
                    hv("wind_gusts_10m"),
            },

            "proximos_7_dias": dias,
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte": "Open-Meteo",
            "erro": str(erro),
        }


# =========================================================
# MARÉ
# =========================================================

def buscar_mare():
    try:
        r = get_normal(URL_MARE_CSV)
        r.encoding = "ISO-8859-1"

        agora = agora_local()
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
                "Nenhum evento de maré para "
                + data_hoje
            )

        eventos.sort(
            key=lambda e: datetime.strptime(
                e["hora"],
                "%H:%M",
            )
        )

        agora_min = (
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

            minutos = h.hour * 60 + h.minute

            if minutos <= agora_min:
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


# =========================================================
# LEGENDA OFICIAL
# =========================================================

def segmentos_de_linha(imagem, y):
    largura, altura = imagem.size

    if y < 0 or y >= altura:
        return []

    segmentos = []
    cor_atual = imagem.getpixel((0, y))
    inicio = 0

    for x in range(1, largura):
        cor = imagem.getpixel((x, y))

        if cor != cor_atual:
            segmentos.append({
                "x_inicio": inicio,
                "x_fim": x - 1,
                "largura": x - inicio,
                "rgba": list(cor_atual),
            })

            inicio = x
            cor_atual = cor

    segmentos.append({
        "x_inicio": inicio,
        "x_fim": largura - 1,
        "largura": largura - inicio,
        "rgba": list(cor_atual),
    })

    return segmentos


def extrair_paleta_oficial():
    try:
        conteudo = get_radar(
            URL_RADAR_LEGENDA
        ).content

        imagem = Image.open(
            io.BytesIO(conteudo)
        ).convert("RGBA")

        candidatos = []

        for y in range(imagem.size[1]):
            segmentos = segmentos_de_linha(
                imagem,
                y,
            )

            relevantes = [
                s for s in segmentos
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
                    "y": y,
                    "segmentos": relevantes,
                    "quantidade": len(relevantes),
                    "largura_total": sum(
                        s["largura"]
                        for s in relevantes
                    ),
                })

        if not candidatos:
            raise ValueError(
                "Faixa da legenda não encontrada."
            )

        candidatos.sort(
            key=lambda x: (
                x["quantidade"],
                x["largura_total"],
            ),
            reverse=True,
        )

        segmentos = sorted(
            candidatos[0]["segmentos"],
            key=lambda s: s["x_inicio"],
        )

        if len(segmentos) != 16:
            segmentos = [
                s for s in segmentos
                if s["largura"] >= 10
            ]

        if len(segmentos) != 16:
            raise ValueError(
                "Quantidade inesperada de classes: "
                + str(len(segmentos))
            )

        classes = []

        for n, s in enumerate(
            segmentos,
            start=1,
        ):
            classes.append({
                "classe": n,
                "rgb": s["rgba"][:3],
                "dbz": None,
            })

        return {
            "status": "online",
            "fonte": "legenda oficial RadarSC",
            "sha256":
                hashlib.sha256(conteudo).hexdigest(),
            "quantidade_classes":
                len(classes),
            "classes":
                classes,
            "dbz_numerico":
                "aguardando_validacao",
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "erro": str(erro),
        }


# =========================================================
# PNG INDEXADO
# =========================================================

def transparencia_por_indice(
    transparencia,
    indice,
):
    if transparencia is None:
        return 255

    if isinstance(transparencia, int):
        return (
            0
            if indice == transparencia
            else 255
        )

    if isinstance(
        transparencia,
        (bytes, bytearray),
    ):
        if indice < len(transparencia):
            return int(transparencia[indice])

    return 255


def rgb_do_indice(paleta, indice):
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


def diagnosticar_paleta_png(imagem):
    largura, altura = imagem.size

    if imagem.mode != "P":
        return {
            "status": "modo_inesperado",
            "modo_original": imagem.mode,
            "largura_px": largura,
            "altura_px": altura,
        }

    paleta = imagem.getpalette()
    transparencia = imagem.info.get(
        "transparency"
    )

    contagem = Counter(imagem.getdata())

    itens = []
    transparente = 0
    visivel = 0
    cinza = 0
    candidato = 0

    for indice, quantidade in sorted(
        contagem.items()
    ):
        rgb = rgb_do_indice(
            paleta,
            indice,
        )

        alpha = transparencia_por_indice(
            transparencia,
            indice,
        )

        eh_visivel = alpha > 0
        eh_cinza = (
            rgb == RGB_CINZA_NAO_VALIDADO
        )

        eh_candidato = (
            eh_visivel
            and not eh_cinza
        )

        if eh_visivel:
            visivel += quantidade
        else:
            transparente += quantidade

        if eh_cinza:
            cinza += quantidade

        if eh_candidato:
            candidato += quantidade

        itens.append({
            "indice_p": int(indice),
            "rgb":
                list(rgb)
                if rgb else None,
            "alpha": alpha,
            "pixels": quantidade,
            "visivel": eh_visivel,
            "cinza_nao_validado": eh_cinza,
            "candidato_meteorologico":
                eh_candidato,
        })

    return {
        "status": "online",
        "modo_original": imagem.mode,
        "largura_px": largura,
        "altura_px": altura,
        "total_pixels": largura * altura,
        "pixels_transparentes": transparente,
        "pixels_visiveis": visivel,
        "pixels_cinza_nao_validado": cinza,
        "pixels_candidatos_meteorologicos":
            candidato,
        "indices_usados": itens,
    }


def construir_mascara_candidata(imagem):
    if imagem.mode != "P":
        return set(), {}

    paleta = imagem.getpalette()
    transparencia = imagem.info.get(
        "transparency"
    )

    indices = {}

    for indice in set(imagem.getdata()):
        rgb = rgb_do_indice(
            paleta,
            indice,
        )

        alpha = transparencia_por_indice(
            transparencia,
            indice,
        )

        if (
            alpha > 0
            and rgb is not None
            and rgb != RGB_CINZA_NAO_VALIDADO
        ):
            indices[indice] = rgb

    mascara = set()
    px = imagem.load()
    largura, altura = imagem.size

    for y in range(altura):
        for x in range(largura):
            if px[x, y] in indices:
                mascara.add((x, y))

    return mascara, indices


# =========================================================
# COMPONENTES CONECTADOS
# =========================================================

def encontrar_componentes(mascara):
    restantes = set(mascara)
    componentes = []

    vizinhos = (
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),            (1, 0),
        (-1, 1),  (0, 1),  (1, 1),
    )

    while restantes:
        inicio = restantes.pop()
        fila = deque([inicio])
        pontos = [inicio]

        while fila:
            x, y = fila.popleft()

            for dx, dy in vizinhos:
                p = (x + dx, y + dy)

                if p in restantes:
                    restantes.remove(p)
                    fila.append(p)
                    pontos.append(p)

        if len(pontos) >= 3:
            componentes.append(pontos)

    componentes.sort(
        key=len,
        reverse=True,
    )

    return componentes


def resumir_componente(
    pontos,
    imagem,
    numero,
):
    largura, altura = imagem.size
    paleta = imagem.getpalette()
    px = imagem.load()

    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]

    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)

    lat_c, lon_c = pixel_para_coordenada(
        cx,
        cy,
        largura,
        altura,
    )

    distancia_c = haversine_km(
        LAT,
        LON,
        lat_c,
        lon_c,
    )

    rumo_c = rumo_graus(
        LAT,
        LON,
        lat_c,
        lon_c,
    )

    minimo = None
    cores = Counter()

    for x, y in pontos:
        lat, lon = pixel_para_coordenada(
            x,
            y,
            largura,
            altura,
        )

        d = haversine_km(
            LAT,
            LON,
            lat,
            lon,
        )

        if (
            minimo is None
            or d < minimo[0]
        ):
            minimo = (
                d, x, y, lat, lon
            )

        rgb = rgb_do_indice(
            paleta,
            px[x, y],
        )

        if rgb:
            cores[rgb] += 1

    d, x, y, lat, lon = minimo

    rumo_min = rumo_graus(
        LAT,
        LON,
        lat,
        lon,
    )

    return {
        "id_quadro": numero,
        "pixels": len(pontos),

        "centroide": {
            "pixel_x": round(cx, 1),
            "pixel_y": round(cy, 1),
            "latitude": round(lat_c, 5),
            "longitude": round(lon_c, 5),
            "distancia_comasa_km":
                round(distancia_c, 2),
            "direcao_graus":
                round(rumo_c, 1),
            "direcao_cardinal":
                ponto_cardinal(rumo_c),
        },

        "ponto_mais_proximo_comasa": {
            "pixel_x": x,
            "pixel_y": y,
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
            "distancia_comasa_km":
                round(d, 2),
            "direcao_graus":
                round(rumo_min, 1),
            "direcao_cardinal":
                ponto_cardinal(rumo_min),
        },

        "caixa_pixels": {
            "x_min": min(xs),
            "x_max": max(xs),
            "y_min": min(ys),
            "y_max": max(ys),
        },

        "cores": [
            {
                "rgb": list(rgb),
                "pixels": quantidade,
            }
            for rgb, quantidade
            in cores.most_common()
        ],

        "dbz": None,
        "classificacao":
            "candidato_a_area_de_eco",
    }


def analisar_espacialmente(imagem):
    largura, altura = imagem.size

    mascara, indices = (
        construir_mascara_candidata(imagem)
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
            "status": "sem_pixels_candidatos",
            "pixel_comasa": {
                "x": x_comasa,
                "y": y_comasa,
            },
            "pixels_candidatos": 0,
            "quantidade_componentes_3px_ou_mais":
                0,
            "maiores_componentes": [],
            "componentes_mais_proximos_comasa":
                [],
        }

    raios = {
        10: 0,
        25: 0,
        50: 0,
        100: 0,
    }

    eco_mais_proximo = None

    for x, y in mascara:
        lat, lon = pixel_para_coordenada(
            x,
            y,
            largura,
            altura,
        )

        d = haversine_km(
            LAT,
            LON,
            lat,
            lon,
        )

        for raio in raios:
            if d <= raio:
                raios[raio] += 1

        if (
            eco_mais_proximo is None
            or d < eco_mais_proximo["_d"]
        ):
            rumo = rumo_graus(
                LAT,
                LON,
                lat,
                lon,
            )

            eco_mais_proximo = {
                "_d": d,
                "pixel_x": x,
                "pixel_y": y,
                "latitude": round(lat, 5),
                "longitude": round(lon, 5),
                "distancia_comasa_km":
                    round(d, 2),
                "direcao_graus":
                    round(rumo, 1),
                "direcao_cardinal":
                    ponto_cardinal(rumo),
            }

    eco_mais_proximo.pop("_d", None)

    brutos = encontrar_componentes(
        mascara
    )

    # 40 maiores: aumenta a chance de manter
    # a mesma área entre quadros sem explodir
    # o tamanho do JSON.
    componentes = [
        resumir_componente(
            pontos,
            imagem,
            numero,
        )
        for numero, pontos in enumerate(
            brutos[:40],
            start=1,
        )
    ]

    proximos = sorted(
        componentes,
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
            "x": x_comasa,
            "y": y_comasa,
            "latitude_aproximada": LAT,
            "longitude_aproximada": LON,
        },

        "pixels_candidatos":
            len(mascara),

        "indices_candidatos": [
            {
                "indice_p": i,
                "rgb": list(rgb),
            }
            for i, rgb
            in sorted(indices.items())
        ],

        "eco_mais_proximo":
            eco_mais_proximo,

        "pixels_por_raio": {
            "ate_10_km": raios[10],
            "ate_25_km": raios[25],
            "ate_50_km": raios[50],
            "ate_100_km": raios[100],
        },

        "quantidade_componentes_3px_ou_mais":
            len(brutos),

        "maiores_componentes":
            componentes,

        "componentes_mais_proximos_comasa":
            proximos[:10],
    }


# =========================================================
# RASTREAMENTO TEMPORAL - NOVO #114
# =========================================================

def distancia_centroides(c1, c2):
    a = c1["centroide"]
    b = c2["centroide"]

    return haversine_km(
        a["latitude"],
        a["longitude"],
        b["latitude"],
        b["longitude"],
    )


def sobreposicao_caixas(c1, c2):
    a = c1["caixa_pixels"]
    b = c2["caixa_pixels"]

    x1 = max(a["x_min"], b["x_min"])
    y1 = max(a["y_min"], b["y_min"])
    x2 = min(a["x_max"], b["x_max"])
    y2 = min(a["y_max"], b["y_max"])

    if x2 < x1 or y2 < y1:
        return 0.0

    inter = (
        (x2 - x1 + 1)
        * (y2 - y1 + 1)
    )

    area_a = (
        (a["x_max"] - a["x_min"] + 1)
        * (a["y_max"] - a["y_min"] + 1)
    )

    area_b = (
        (b["x_max"] - b["x_min"] + 1)
        * (b["y_max"] - b["y_min"] + 1)
    )

    menor = min(area_a, area_b)

    if menor <= 0:
        return 0.0

    return inter / menor


def razao_tamanho(c1, c2):
    a = max(1, c1["pixels"])
    b = max(1, c2["pixels"])

    return min(a, b) / max(a, b)


def pontuar_correspondencia(
    anterior,
    atual,
    minutos,
):
    """
    Pontuação conservadora para decidir se
    dois componentes podem representar a
    continuidade da mesma área de eco.

    Não é uma identificação meteorológica
    definitiva; é rastreamento geométrico.
    """

    if minutos <= 0:
        return None

    distancia = distancia_centroides(
        anterior,
        atual,
    )

    velocidade = (
        distancia
        / (minutos / 60)
    )

    # Rejeita deslocamentos incompatíveis
    # com nosso rastreamento de 10 min.
    if velocidade > 150:
        return None

    tamanho = razao_tamanho(
        anterior,
        atual,
    )

    sobreposicao = sobreposicao_caixas(
        anterior,
        atual,
    )

    # Distância é o critério principal.
    # Componentes muito distantes não casam.
    if distancia > 25:
        return None

    # Mudança de tamanho absurda sem
    # sobreposição é fraca evidência.
    if (
        tamanho < 0.15
        and sobreposicao == 0
    ):
        return None

    score_distancia = max(
        0,
        1 - distancia / 25,
    )

    score = (
        score_distancia * 0.55
        + tamanho * 0.25
        + min(1, sobreposicao) * 0.20
    )

    return {
        "score": score,
        "distancia_km": distancia,
        "velocidade_kmh": velocidade,
        "razao_tamanho": tamanho,
        "sobreposicao_caixas": sobreposicao,
    }


def casar_quadros(
    quadro_anterior,
    quadro_atual,
):
    analise_a = quadro_anterior.get(
        "analise_espacial",
        {},
    )

    analise_b = quadro_atual.get(
        "analise_espacial",
        {},
    )

    comps_a = analise_a.get(
        "maiores_componentes",
        [],
    )

    comps_b = analise_b.get(
        "maiores_componentes",
        [],
    )

    if not comps_a or not comps_b:
        return []

    ta = datetime.fromisoformat(
        quadro_anterior["horario_utc"]
    )

    tb = datetime.fromisoformat(
        quadro_atual["horario_utc"]
    )

    minutos = (
        tb - ta
    ).total_seconds() / 60

    candidatos = []

    for a in comps_a:
        for b in comps_b:
            p = pontuar_correspondencia(
                a,
                b,
                minutos,
            )

            if p is None:
                continue

            candidatos.append({
                "a": a,
                "b": b,
                **p,
            })

    candidatos.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    usados_a = set()
    usados_b = set()
    pares = []

    for c in candidatos:
        ida = c["a"]["id_quadro"]
        idb = c["b"]["id_quadro"]

        if (
            ida in usados_a
            or idb in usados_b
        ):
            continue

        # Score mínimo conservador.
        if c["score"] < 0.38:
            continue

        usados_a.add(ida)
        usados_b.add(idb)

        ca = c["a"]["centroide"]
        cb = c["b"]["centroide"]

        direcao_mov = rumo_graus(
            ca["latitude"],
            ca["longitude"],
            cb["latitude"],
            cb["longitude"],
        )

        dist_comasa_a = ca[
            "distancia_comasa_km"
        ]

        dist_comasa_b = cb[
            "distancia_comasa_km"
        ]

        variacao_comasa = (
            dist_comasa_b
            - dist_comasa_a
        )

        if variacao_comasa < -1:
            tendencia = "aproximando"
        elif variacao_comasa > 1:
            tendencia = "afastando"
        else:
            tendencia = "estavel"

        pares.append({
            "componente_anterior": ida,
            "componente_atual": idb,

            "score":
                round(c["score"], 3),

            "intervalo_min":
                round(minutos, 1),

            "deslocamento_centroide_km":
                round(
                    c["distancia_km"],
                    2,
                ),

            "velocidade_estimada_kmh":
                round(
                    c["velocidade_kmh"],
                    1,
                ),

            "direcao_movimento_graus":
                round(direcao_mov, 1),

            "direcao_movimento_cardinal":
                ponto_cardinal(
                    direcao_mov
                ),

            "razao_tamanho":
                round(
                    c["razao_tamanho"],
                    3,
                ),

            "sobreposicao_caixas":
                round(
                    c["sobreposicao_caixas"],
                    3,
                ),

            "distancia_comasa_anterior_km":
                dist_comasa_a,

            "distancia_comasa_atual_km":
                dist_comasa_b,

            "variacao_distancia_comasa_km":
                round(
                    variacao_comasa,
                    2,
                ),

            "tendencia_relativa_comasa":
                tendencia,

            "centroide_anterior":
                ca,

            "centroide_atual":
                cb,
        })

    return pares


def construir_rastreamento(quadros):
    """
    Constrói correspondências entre pares
    consecutivos e tenta formar trilhas.

    Para esta versão, movimento é apenas
    diagnóstico. ETA continua bloqueado
    até verificarmos o resultado real.
    """

    if len(quadros) < 2:
        return {
            "status":
                "dados_insuficientes",
            "pares_quadros":
                [],
            "trilhas":
                [],
        }

    pares_quadros = []

    for i in range(
        1,
        len(quadros),
    ):
        anterior = quadros[i - 1]
        atual = quadros[i]

        pares = casar_quadros(
            anterior,
            atual,
        )

        pares_quadros.append({
            "de":
                anterior["horario_local"],
            "para":
                atual["horario_local"],
            "correspondencias":
                pares,
            "quantidade":
                len(pares),
        })

    # Criação das trilhas.
    trilhas = []
    proximo_id = 1

    # mapa:
    # (indice_quadro, id_componente) -> trilha
    mapa = {}

    for i, bloco in enumerate(
        pares_quadros,
        start=1,
    ):
        for par in bloco[
            "correspondencias"
        ]:
            id_a = par[
                "componente_anterior"
            ]

            id_b = par[
                "componente_atual"
            ]

            chave_a = (
                i - 1,
                id_a,
            )

            chave_b = (
                i,
                id_b,
            )

            trilha = mapa.get(
                chave_a
            )

            if trilha is None:
                trilha = {
                    "id_trilha":
                        proximo_id,
                    "passos": [],
                }

                proximo_id += 1
                trilhas.append(trilha)

            trilha["passos"].append({
                "de":
                    bloco["de"],
                "para":
                    bloco["para"],
                **par,
            })

            mapa[chave_a] = trilha
            mapa[chave_b] = trilha

    resumos = []

    for trilha in trilhas:
        passos = trilha["passos"]

        if not passos:
            continue

        velocidades = [
            p["velocidade_estimada_kmh"]
            for p in passos
        ]

        scores = [
            p["score"]
            for p in passos
        ]

        aproximando = sum(
            1 for p in passos
            if p[
                "tendencia_relativa_comasa"
            ] == "aproximando"
        )

        afastando = sum(
            1 for p in passos
            if p[
                "tendencia_relativa_comasa"
            ] == "afastando"
        )

        estavel = (
            len(passos)
            - aproximando
            - afastando
        )

        ultimo = passos[-1]

        if aproximando > afastando:
            tendencia = "aproximando"
        elif afastando > aproximando:
            tendencia = "afastando"
        else:
            tendencia = "indeterminada"

        confianca_geometrica = (
            sum(scores) / len(scores)
        )

        # Exigimos pelo menos 2 transições
        # para chamar algo de trilha temporal.
        elegivel = len(passos) >= 2

        resumos.append({
            "id_trilha":
                trilha["id_trilha"],

            "transicoes":
                len(passos),

            "elegivel_para_analise":
                elegivel,

            "score_medio":
                round(
                    confianca_geometrica,
                    3,
                ),

            "velocidade_media_kmh":
                round(
                    sum(velocidades)
                    / len(velocidades),
                    1,
                ),

            "tendencia_relativa_comasa":
                tendencia,

            "passos_aproximando":
                aproximando,

            "passos_afastando":
                afastando,

            "passos_estaveis":
                estavel,

            "ultima_distancia_comasa_km":
                ultimo[
                    "distancia_comasa_atual_km"
                ],

            "ultima_direcao_movimento":
                ultimo[
                    "direcao_movimento_cardinal"
                ],

            "passos":
                passos,
        })

    resumos.sort(
        key=lambda t: (
            t["elegivel_para_analise"],
            t["transicoes"],
            t["score_medio"],
        ),
        reverse=True,
    )

    elegiveis = [
        t for t in resumos
        if t["elegivel_para_analise"]
    ]

    aproximando = [
        t for t in elegiveis
        if t[
            "tendencia_relativa_comasa"
        ] == "aproximando"
    ]

    aproximando.sort(
        key=lambda t: (
            t["ultima_distancia_comasa_km"],
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
                2,
        },

        "pares_quadros":
            pares_quadros,

        "quantidade_trilhas":
            len(resumos),

        "quantidade_trilhas_elegiveis":
            len(elegiveis),

        "trilhas":
            resumos[:20],

        "trilha_principal_diagnostica":
            principal,

        "observacao": (
            "Rastreamento geométrico ainda "
            "não autoriza previsão de chegada. "
            "Resultado deve ser validado antes "
            "de liberar ETA."
        ),
    }


# =========================================================
# DOWNLOAD DO RADAR
# =========================================================

def baixar_quadro(nome):
    r = get_radar(
        URL_RADAR_IMAGEM,
        params={
            "prod": 4,
            "radar": "COMP",
            "file": nome,
        },
    )

    conteudo = r.content

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

    return {
        "bytes": len(conteudo),

        "sha256":
            hashlib.sha256(
                conteudo
            ).hexdigest(),

        "largura_px": largura,
        "altura_px": altura,

        "modo_png_original":
            imagem.mode,

        "diagnostico_paleta_png":
            diagnosticar_paleta_png(
                imagem
            ),

        "analise_espacial":
            analisar_espacialmente(
                imagem
            ),
    }


def buscar_radar():
    try:
        legenda = extrair_paleta_oficial()

        resposta = get_radar(
            URL_RADAR_LISTA,
            params={
                "prod": 4,
                "radar": "COMP",
                "data": "",
            },
        )

        imagens = resposta.json()

        if not isinstance(imagens, list):
            raise ValueError(
                "Resposta do radar não é lista."
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
                    tzinfo=UTC
                )

                data_local = (
                    data_utc.astimezone(
                        FUSO_LOCAL
                    )
                )

                resultado = baixar_quadro(
                    nome
                )

                quadros.append({
                    "arquivo": nome,
                    "horario_utc":
                        data_utc.isoformat(),
                    "horario_local":
                        data_local.isoformat(),
                    "download": "ok",
                    **resultado,
                })

            except Exception as erro:
                quadros.append({
                    "arquivo": nome,
                    "download": "erro",
                    "erro": str(erro),
                })

        validos = [
            q for q in quadros
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

        idade = max(
            0,
            round(
                (
                    datetime.now(UTC)
                    - ultimo_utc
                ).total_seconds()
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

        serie = []

        for q in validos:
            a = q.get(
                "analise_espacial",
                {},
            )

            serie.append({
                "horario_local":
                    q["horario_local"],
                "pixels_candidatos":
                    a.get(
                        "pixels_candidatos"
                    ),
                "componentes":
                    a.get(
                        "quantidade_componentes_3px_ou_mais"
                    ),
                "eco_mais_proximo":
                    a.get(
                        "eco_mais_proximo"
                    ),
                "pixels_por_raio":
                    a.get(
                        "pixels_por_raio"
                    ),
            })

        rastreamento = (
            construir_rastreamento(
                validos
            )
        )

        principal = rastreamento.get(
            "trilha_principal_diagnostica"
        )

        # Movimento continua experimental.
        # Não o transformamos em alerta ainda.
        if principal:
            analise_movimento = {
                "status":
                    "diagnostico_disponivel",

                "metodo":
                    "rastreamento_de_componentes",

                "trilha_id":
                    principal["id_trilha"],

                "transicoes":
                    principal["transicoes"],

                "score_medio":
                    principal["score_medio"],

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

                "validado_para_eta":
                    False,
            }
        else:
            analise_movimento = {
                "status":
                    "sem_trilha_elegivel",
                "validado_para_eta":
                    False,
            }

        if not fresco:
            eta_motivo = (
                "Radar desatualizado: "
                f"{idade} min. "
                "ETA não pode ser calculado."
            )
        elif not principal:
            eta_motivo = (
                "Nenhuma trilha temporal "
                "elegível foi identificada."
            )
        else:
            eta_motivo = (
                "Há rastreamento experimental, "
                "mas o algoritmo ainda precisa "
                "ser validado antes de liberar ETA."
            )

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

            "fonte":
                "Defesa Civil de Santa Catarina - RadarSC",

            "radar": "COMP",
            "produto": "C-MAX",
            "produto_codigo": 4,
            "extent": RADAR_EXTENT,

            "quantidade_quadros":
                len(imagens),

            "quadros_png_validos":
                len(validos),

            "todos_png_validos":
                len(validos) == len(imagens),

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
                serie,

            "rastreamento_temporal":
                rastreamento,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "analise_geografica": {
                "status": "ativa",

                "referencia":
                    "Comasa - coordenada pública aproximada",

                "ultimo":
                    ultimo.get(
                        "analise_espacial"
                    ),
            },

            "analise_movimento":
                analise_movimento,

            "interpretacao_dbz":
                "aguardando_validacao_numerica",

            "eta": {
                "status": "bloqueado",
                "janela_chegada": None,
                "motivo": eta_motivo,
            },
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


# =========================================================
# PROGRAMA PRINCIPAL
# =========================================================

def main():
    agora = agora_local()

    previsao = buscar_previsao()
    mare = buscar_mare()
    radar = buscar_radar()

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
