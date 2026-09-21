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

# Extensão oficial do mosaico COMP.
# [oeste, sul, leste, norte]
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


def requisicao_normal(url, params=None):
    resposta = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "Monitor-Guaxanduva/1.0"
        },
    )
    resposta.raise_for_status()
    return resposta


def requisicao_radar(url, params=None):
    """
    O servidor oficial SIFAP apresentou problema
    de cadeia de certificado no GitHub Actions.

    verify=False fica restrito ao SIFAP.
    """
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


def haversine_km(lat1, lon1, lat2, lon2):
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

    indice = int(
        (graus + 22.5) // 45
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
        r = requisicao_normal(
            url,
            parametros,
        )

        resposta = r.json()

        atual = resposta.get("current", {})
        horario = resposta.get("hourly", {})
        diario = resposta.get("daily", {})

        agora = agora_local()
        indice = None

        for i, tempo in enumerate(
            horario.get("time", [])
        ):
            try:
                momento = (
                    datetime
                    .fromisoformat(tempo)
                    .replace(tzinfo=FUSO_LOCAL)
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
            diario.get("time", [])
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

            "proximos_7_dias": dias,
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "fonte": "Open-Meteo",
            "erro": str(erro),
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
            partes = linha.strip().split(";")

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

def segmentos_de_linha(
    imagem_rgba,
    y,
):
    largura, altura = imagem_rgba.size

    if y < 0 or y >= altura:
        return []

    segmentos = []

    cor_atual = imagem_rgba.getpixel(
        (0, y)
    )

    inicio = 0

    for x in range(1, largura):
        cor = imagem_rgba.getpixel(
            (x, y)
        )

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
    """
    Extrai os 16 blocos cromáticos da
    legenda oficial.

    Nenhum valor numérico de dBZ é
    inventado nesta etapa.
    """

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
            segmentos = segmentos_de_linha(
                imagem,
                y,
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
                    "y": y,
                    "segmentos": relevantes,
                    "quantidade":
                        len(relevantes),
                    "largura_total":
                        sum(
                            s["largura"]
                            for s in relevantes
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

        segmentos = melhor["segmentos"]

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
                "classe": indice,
                "rgb":
                    segmento["rgba"][:3],
                "x_inicio":
                    segmento["x_inicio"],
                "x_fim":
                    segmento["x_fim"],
                "largura_px":
                    segmento["largura"],
                "dbz": None,
            })

        return {
            "status": "online",
            "fonte":
                "legenda oficial RadarSC",
            "url_relativa":
                "img/legenda.png",
            "sha256":
                hashlib.sha256(
                    conteudo
                ).hexdigest(),
            "largura_px": largura,
            "altura_px": altura,
            "linha_paleta_y":
                melhor["y"],
            "quantidade_classes":
                len(classes),
            "classes": classes,
            "dbz_numerico":
                "aguardando_validacao",
            "observacao": (
                "16 blocos cromáticos "
                "extraídos diretamente da "
                "legenda oficial. Valores "
                "numéricos de dBZ ainda não "
                "foram inferidos."
            ),
        }

    except Exception as erro:
        return {
            "status": "indisponivel",
            "erro": str(erro),
        }


# =========================================================
# DIAGNÓSTICO DA PALETA INTERNA DO PNG
# =========================================================

def transparencia_por_indice(
    transparencia,
    indice,
):
    """
    Interpreta o chunk tRNS exposto pelo
    Pillow.

    Pode ser:
    - inteiro: um único índice transparente;
    - bytes: alpha individual por índice;
    - ausente: alpha 255.
    """

    if transparencia is None:
        return 255

    if isinstance(transparencia, int):
        if indice == transparencia:
            return 0

        return 255

    if isinstance(
        transparencia,
        (bytes, bytearray),
    ):
        if indice < len(transparencia):
            return int(
                transparencia[indice]
            )

        return 255

    return 255


def diagnosticar_paleta_png(conteudo):
    """
    Investiga o PNG ORIGINAL em modo P.

    Não converte primeiro para RGBA.

    Assim preservamos:
    - índice de paleta;
    - PLTE;
    - tRNS;
    - frequência real de cada índice.
    """

    imagem = Image.open(
        io.BytesIO(conteudo)
    )

    largura, altura = imagem.size
    modo_original = imagem.mode

    diagnostico = {
        "status": "online",
        "metodo":
            "P_PLTE_tRNS_indices_originais",
        "modo_original":
            modo_original,
        "largura_px":
            largura,
        "altura_px":
            altura,
        "total_pixels":
            largura * altura,
    }

    if modo_original != "P":
        diagnostico.update({
            "status":
                "modo_inesperado",
            "observacao": (
                "O PNG não chegou em modo P. "
                "Nenhuma interpretação de "
                "índices foi realizada."
            ),
        })

        return diagnostico

    paleta_bruta = imagem.getpalette()

    if paleta_bruta is None:
        diagnostico.update({
            "status":
                "sem_paleta",
            "observacao":
                "PLTE não disponível.",
        })

        return diagnostico

    transparencia = imagem.info.get(
        "transparency"
    )

    contagem = Counter(
        imagem.getdata()
    )

    indices_usados = []

    pixels_transparentes = 0
    pixels_visiveis = 0

    for indice, quantidade in sorted(
        contagem.items()
    ):
        pos = indice * 3

        if pos + 2 >= len(paleta_bruta):
            rgb = None

        else:
            rgb = [
                paleta_bruta[pos],
                paleta_bruta[pos + 1],
                paleta_bruta[pos + 2],
            ]

        alpha = transparencia_por_indice(
            transparencia,
            indice,
        )

        visivel = (
            alpha > 0
        )

        if visivel:
            pixels_visiveis += quantidade

        else:
            pixels_transparentes += quantidade

        indices_usados.append({
            "indice_p":
                int(indice),

            "rgb":
                rgb,

            "alpha":
                alpha,

            "visivel":
                visivel,

            "pixels":
                quantidade,

            "percentual_total":
                round(
                    quantidade
                    / (largura * altura)
                    * 100,
                    6,
                ),
        })

    indices_visiveis = [
        item
        for item in indices_usados
        if item["visivel"]
    ]

    indices_transparentes = [
        item
        for item in indices_usados
        if not item["visivel"]
    ]

    indices_visiveis_ordenados = sorted(
        indices_visiveis,
        key=lambda item:
            item["pixels"],
        reverse=True,
    )

    diagnostico.update({
        "quantidade_indices_usados":
            len(indices_usados),

        "quantidade_indices_visiveis":
            len(indices_visiveis),

        "quantidade_indices_transparentes":
            len(indices_transparentes),

        "pixels_visiveis":
            pixels_visiveis,

        "pixels_transparentes":
            pixels_transparentes,

        "percentual_visivel":
            round(
                pixels_visiveis
                / (largura * altura)
                * 100,
                6,
            ),

        "indices_usados":
            indices_usados,

        "indices_visiveis_por_frequencia":
            indices_visiveis_ordenados,

        "transparencia_tipo":
            (
                type(transparencia).__name__
                if transparencia is not None
                else None
            ),

        "transparencia_tamanho":
            (
                len(transparencia)
                if isinstance(
                    transparencia,
                    (bytes, bytearray),
                )
                else None
            ),

        "observacao": (
            "Diagnóstico direto do PNG "
            "indexado. Nenhum índice foi "
            "convertido em dBZ nesta etapa."
        ),
    })

    return diagnostico


# =========================================================
# ANÁLISE ESPACIAL DIAGNÓSTICA
# =========================================================

def diagnosticar_indices_perto_comasa(
    conteudo,
):
    """
    Examina quais índices P aparecem nas
    proximidades da coordenada pública
    aproximada do Comasa.

    Ainda NÃO chama esses pixels de chuva.
    """

    imagem = Image.open(
        io.BytesIO(conteudo)
    )

    largura, altura = imagem.size

    x_comasa, y_comasa = (
        coordenada_para_pixel(
            LON,
            LAT,
            largura,
            altura,
        )
    )

    resultado = {
        "pixel_comasa": {
            "x": x_comasa,
            "y": y_comasa,
            "latitude_aproximada": LAT,
            "longitude_aproximada": LON,
        },

        "modo_original":
            imagem.mode,
    }

    if imagem.mode != "P":
        resultado["status"] = (
            "modo_incompativel"
        )

        return resultado

    paleta_bruta = imagem.getpalette()
    transparencia = imagem.info.get(
        "transparency"
    )

    # Janela de 11 x 11 pixels.
    raio = 5

    contagem_local = Counter()

    for y in range(
        max(0, y_comasa - raio),
        min(altura, y_comasa + raio + 1),
    ):
        for x in range(
            max(0, x_comasa - raio),
            min(largura, x_comasa + raio + 1),
        ):
            indice = imagem.getpixel(
                (x, y)
            )

            contagem_local[indice] += 1

    indices = []

    for indice, quantidade in sorted(
        contagem_local.items()
    ):
        pos = indice * 3

        rgb = [
            paleta_bruta[pos],
            paleta_bruta[pos + 1],
            paleta_bruta[pos + 2],
        ]

        alpha = transparencia_por_indice(
            transparencia,
            indice,
        )

        indices.append({
            "indice_p": int(indice),
            "rgb": rgb,
            "alpha": alpha,
            "visivel": alpha > 0,
            "pixels_janela_11x11":
                quantidade,
        })

    indice_central = imagem.getpixel(
        (x_comasa, y_comasa)
    )

    pos = indice_central * 3

    rgb_central = [
        paleta_bruta[pos],
        paleta_bruta[pos + 1],
        paleta_bruta[pos + 2],
    ]

    alpha_central = (
        transparencia_por_indice(
            transparencia,
            indice_central,
        )
    )

    resultado.update({
        "status":
            "diagnostico_concluido",

        "janela":
            "11x11",

        "pixel_central": {
            "indice_p":
                int(indice_central),
            "rgb":
                rgb_central,
            "alpha":
                alpha_central,
            "visivel":
                alpha_central > 0,
        },

        "indices_na_janela":
            indices,

        "interpretacao_meteorologica":
            "ainda_nao_atribuida",
    })

    return resultado


# =========================================================
# DOWNLOAD DE UM QUADRO
# =========================================================

def baixar_quadro(nome):
    resposta = requisicao_radar(
        URL_RADAR_IMAGEM,
        params={
            "prod": 4,
            "radar": "COMP",
            "file": nome,
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
            conteudo
        )
    )

    diagnostico_comasa = (
        diagnosticar_indices_perto_comasa(
            conteudo
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

        "diagnostico_comasa":
            diagnostico_comasa,
    }


# =========================================================
# RADAR COMPLETO
# =========================================================

def buscar_radar():
    try:
        legenda = (
            extrair_paleta_oficial()
        )

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
                data_utc = (
                    datetime.strptime(
                        nome[:14],
                        "%Y%m%d%H%M%S",
                    )
                    .replace(tzinfo=UTC)
                )

                data_local = (
                    data_utc.astimezone(
                        FUSO_LOCAL
                    )
                )

                resultado = (
                    baixar_quadro(nome)
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

        ultimo_utc = (
            datetime.fromisoformat(
                ultimo["horario_utc"]
            )
        )

        agora_utc = datetime.now(UTC)

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
                q["largura_px"],
                q["altura_px"],
            )
            for q in validos
        }

        # Resumo das paletas observadas
        # nos sete quadros.
        resumo_indices = {}

        for quadro in validos:
            diagnostico = quadro.get(
                "diagnostico_paleta_png",
                {},
            )

            for item in diagnostico.get(
                "indices_usados",
                [],
            ):
                indice = str(
                    item["indice_p"]
                )

                if indice not in resumo_indices:
                    resumo_indices[indice] = {
                        "indice_p":
                            item["indice_p"],
                        "rgb":
                            item["rgb"],
                        "alpha":
                            item["alpha"],
                        "visivel":
                            item["visivel"],
                        "quadros_em_que_aparece":
                            0,
                        "pixels_somados":
                            0,
                    }

                resumo_indices[indice][
                    "quadros_em_que_aparece"
                ] += 1

                resumo_indices[indice][
                    "pixels_somados"
                ] += item["pixels"]

        resumo_lista = sorted(
            resumo_indices.values(),
            key=lambda item:
                item["indice_p"],
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

            "fonte": (
                "Defesa Civil de "
                "Santa Catarina - RadarSC"
            ),

            "radar": "COMP",
            "produto": "C-MAX",
            "produto_codigo": 4,

            "extent":
                RADAR_EXTENT,

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

            "investigacao_paleta_png": {
                "status":
                    "ativa",

                "objetivo": (
                    "Identificar a paleta "
                    "PLTE/tRNS realmente usada "
                    "nos PNGs C-MAX antes de "
                    "atribuir classes de "
                    "refletividade."
                ),

                "metodo": (
                    "indices_P_PLTE_tRNS"
                ),

                "indices_observados_7_quadros":
                    resumo_lista,

                "dbz":
                    "nao_atribuido",

                "movimento":
                    "bloqueado_ate_validacao",

                "eta":
                    "bloqueado_ate_validacao",
            },

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "analise_geografica": {
                "status":
                    "georreferencia_validada_"
                    "mas_ecos_nao_classificados",

                "referencia": (
                    "Comasa - coordenada "
                    "pública aproximada"
                ),

                "pixel_comasa":
                    ultimo
                    .get(
                        "diagnostico_comasa",
                        {},
                    )
                    .get(
                        "pixel_comasa"
                    ),

                "diagnostico_local":
                    ultimo.get(
                        "diagnostico_comasa"
                    ),
            },

            "analise_movimento": {
                "status":
                    "bloqueada",

                "tendencia":
                    "nao_calculada",

                "motivo": (
                    "A paleta interna real do "
                    "PNG ainda está sendo "
                    "validada. O resultado "
                    "aproximando/afastando do "
                    "teste anterior foi "
                    "descartado."
                ),
            },

            "interpretacao_dbz":
                "aguardando_correspondencia_"
                "PLTE_legenda",

            "eta": {
                "status":
                    "bloqueado",

                "motivo": (
                    "Não calcular ETA antes "
                    "de validar quais índices "
                    "P representam ecos "
                    "meteorológicos."
                ),
            },
        }

    except Exception as erro:
        return {
            "status": "indisponivel",

            "fonte": (
                "Defesa Civil de "
                "Santa Catarina - RadarSC"
            ),

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

            "fonte": (
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
