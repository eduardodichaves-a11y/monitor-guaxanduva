import json
import hashlib
import io
from collections import Counter, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import urllib3
from PIL import Image


ARQUIVO = "dados.json"

# Coordenada pública aproximada do Comasa.
# Não representa endereço residencial.
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

# Extensão geográfica oficial usada
# pela interface RadarSC para COMP.
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
    url = (
        "https://api.open-meteo.com/v1/forecast"
    )

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
                "User-Agent":
                    "Monitor-Guaxanduva/1.0"
            },
        )

        r.raise_for_status()

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

        agora = datetime.now(
            ZoneInfo(
                "America/Sao_Paulo"
            )
        )

        indice = None

        for i, tempo in enumerate(
            horario.get("time", [])
        ):
            try:
                momento = (
                    datetime.fromisoformat(
                        tempo
                    )
                    .replace(
                        tzinfo=ZoneInfo(
                            "America/Sao_Paulo"
                        )
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


def buscar_mare():
    try:
        r = requests.get(
            URL_MARE_CSV,
            timeout=30,
            headers={
                "User-Agent":
                    "Monitor-Guaxanduva/1.0"
            },
        )

        r.raise_for_status()

        r.encoding = "ISO-8859-1"

        agora = datetime.now(
            ZoneInfo(
                "America/Sao_Paulo"
            )
        )

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


def analisar_png(conteudo):
    imagem = Image.open(
        io.BytesIO(conteudo)
    )

    formato = imagem.format
    modo_original = imagem.mode
    largura, altura = imagem.size

    rgba = imagem.convert("RGBA")

    pixels = list(
        rgba.getdata()
    )

    transparentes = sum(
        1
        for p in pixels
        if p[3] == 0
    )

    semitransparentes = sum(
        1
        for p in pixels
        if 0 < p[3] < 255
    )

    visiveis = [
        p
        for p in pixels
        if p[3] > 0
    ]

    contador = Counter(
        visiveis
    )

    cores = [
        {
            "rgba":
                list(cor),

            "pixels":
                quantidade,
        }
        for cor, quantidade
        in contador.most_common(30)
    ]

    x, y = coordenada_para_pixel(
        LON,
        LAT,
        largura,
        altura,
    )

    pixel_central = rgba.getpixel(
        (x, y)
    )

    raio = 5

    janela = []

    for py in range(
        max(
            0,
            y - raio,
        ),
        min(
            altura,
            y + raio + 1,
        ),
    ):
        for px in range(
            max(
                0,
                x - raio,
            ),
            min(
                largura,
                x + raio + 1,
            ),
        ):
            janela.append(
                rgba.getpixel(
                    (px, py)
                )
            )

    janela_visivel = [
        p
        for p in janela
        if p[3] > 0
    ]

    contador_janela = Counter(
        janela_visivel
    )

    cores_janela = [
        {
            "rgba":
                list(cor),

            "pixels":
                quantidade,
        }
        for cor, quantidade
        in contador_janela.most_common(
            10
        )
    ]

    total = largura * altura

    return {
        "formato":
            formato,

        "modo_original":
            modo_original,

        "largura_px":
            largura,

        "altura_px":
            altura,

        "total_pixels":
            total,

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
            "longitude_aproximada":
                LON,

            "latitude_aproximada":
                LAT,

            "pixel_x":
                x,

            "pixel_y":
                y,

            "pixel_rgba":
                list(pixel_central),

            "janela_px":
                "11x11",

            "pixels_visiveis_janela":
                len(janela_visivel),

            "cores_visiveis_janela":
                len(contador_janela),

            "cores_mais_frequentes_janela":
                cores_janela,
        },
    }


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

    for x in range(
        1,
        largura,
    ):
        cor = imagem_rgba.getpixel(
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


def analisar_geometria_legenda(
    imagem_rgba
):
    largura, altura = imagem_rgba.size

    linhas = []

    for y in range(altura):
        segmentos = segmentos_de_linha(
            imagem_rgba,
            y,
        )

        relevantes = [
            segmento
            for segmento in segmentos
            if (
                segmento["largura"] >= 5
                and segmento["rgba"][3] > 0
                and segmento["rgba"][:3]
                not in (
                    [255, 255, 255],
                    [0, 0, 0],
                )
            )
        ]

        cores = {
            tuple(
                segmento["rgba"]
            )
            for segmento
            in relevantes
        }

        largura_colorida = sum(
            segmento["largura"]
            for segmento
            in relevantes
        )

        linhas.append({
            "y":
                y,

            "quantidade_segmentos":
                len(relevantes),

            "cores_distintas":
                len(cores),

            "largura_colorida_px":
                largura_colorida,

            "segmentos":
                relevantes,
        })

    linhas.sort(
        key=lambda item: (
            item[
                "quantidade_segmentos"
            ],
            item[
                "cores_distintas"
            ],
            item[
                "largura_colorida_px"
            ],
        ),
        reverse=True,
    )

    melhores = linhas[:10]

    melhor = (
        melhores[0]
        if melhores
        else None
    )

    return {
        "largura_legenda_px":
            largura,

        "altura_legenda_px":
            altura,

        "melhor_linha":
            melhor,

        "top_10_linhas_candidatas":
            melhores,
    }


def pixel_escuro(pixel):
    """
    Detecta pixels escuros usados nos
    caracteres impressos da legenda.

    Trabalhamos com luminância, não com
    igualdade RGB, para incluir as bordas
    antialiasadas das letras e números.
    """
    r, g, b, a = pixel

    if a == 0:
        return False

    luminancia = (
        0.2126 * r
        + 0.7152 * g
        + 0.0722 * b
    )

    return luminancia < 150


def matriz_texto_legenda(
    imagem_rgba,
    y_inicio=13,
):
    """
    Converte a região inferior da legenda
    em desenho ASCII.

    # = pixel escuro
    . = fundo/outro pixel
    """
    largura, altura = imagem_rgba.size

    y_inicio = max(
        0,
        min(
            altura - 1,
            y_inicio,
        ),
    )

    linhas = []

    for y in range(
        y_inicio,
        altura,
    ):
        linha = []

        for x in range(largura):
            pixel = imagem_rgba.getpixel(
                (x, y)
            )

            linha.append(
                "#"
                if pixel_escuro(pixel)
                else "."
            )

        linhas.append(
            "".join(linha)
        )

    return {
        "y_inicio":
            y_inicio,

        "y_fim":
            altura - 1,

        "largura_px":
            largura,

        "altura_px":
            altura - y_inicio,

        "linhas":
            linhas,
    }


def componentes_texto_legenda(
    imagem_rgba,
    y_inicio=13,
):
    """
    Encontra grupos conectados de pixels
    escuros na parte inferior da legenda.

    Cada componente recebe:
    - bounding box
    - centro
    - quantidade de pixels
    - desenho ASCII próprio

    Isso permitirá reconstruir números
    sem OCR externo.
    """
    largura, altura = imagem_rgba.size

    y_inicio = max(
        0,
        min(
            altura - 1,
            y_inicio,
        ),
    )

    mascara = set()

    for y in range(
        y_inicio,
        altura,
    ):
        for x in range(largura):
            if pixel_escuro(
                imagem_rgba.getpixel(
                    (x, y)
                )
            ):
                mascara.add(
                    (x, y)
                )

    visitados = set()
    componentes = []

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

    for origem in sorted(
        mascara,
        key=lambda p: (
            p[0],
            p[1],
        ),
    ):
        if origem in visitados:
            continue

        fila = deque(
            [origem]
        )

        visitados.add(
            origem
        )

        pontos = []

        while fila:
            atual = fila.popleft()

            pontos.append(
                atual
            )

            x, y = atual

            for dx, dy in vizinhos:
                vizinho = (
                    x + dx,
                    y + dy,
                )

                if (
                    vizinho in mascara
                    and vizinho
                    not in visitados
                ):
                    visitados.add(
                        vizinho
                    )

                    fila.append(
                        vizinho
                    )

        xs = [
            ponto[0]
            for ponto in pontos
        ]

        ys = [
            ponto[1]
            for ponto in pontos
        ]

        x0 = min(xs)
        x1 = max(xs)
        y0 = min(ys)
        y1 = max(ys)

        largura_comp = (
            x1 - x0 + 1
        )

        altura_comp = (
            y1 - y0 + 1
        )

        # Pequenos ruídos isolados não
        # interessam para os caracteres.
        if len(pontos) < 2:
            continue

        conjunto = set(
            pontos
        )

        desenho = []

        for py in range(
            y0,
            y1 + 1,
        ):
            linha = []

            for px in range(
                x0,
                x1 + 1,
            ):
                linha.append(
                    "#"
                    if (
                        px,
                        py,
                    ) in conjunto
                    else "."
                )

            desenho.append(
                "".join(linha)
            )

        componentes.append({
            "x_inicio":
                x0,

            "x_fim":
                x1,

            "y_inicio":
                y0,

            "y_fim":
                y1,

            "largura_px":
                largura_comp,

            "altura_px":
                altura_comp,

            "centro_x":
                round(
                    (
                        x0
                        + x1
                    )
                    / 2,
                    1,
                ),

            "centro_y":
                round(
                    (
                        y0
                        + y1
                    )
                    / 2,
                    1,
                ),

            "pixels_escuros":
                len(pontos),

            "desenho":
                desenho,
        })

    componentes.sort(
        key=lambda item: (
            item["x_inicio"],
            item["y_inicio"],
        )
    )

    return {
        "y_inicio_analise":
            y_inicio,

        "quantidade_componentes":
            len(componentes),

        "componentes":
            componentes,
    }


def associar_componentes_blocos(
    geometria,
    componentes,
):
    """
    Para cada um dos 16 blocos da escala,
    informa quais componentes escuros estão
    mais próximos horizontalmente.

    Ainda NÃO tenta dizer qual algarismo é.
    """
    melhor = geometria.get(
        "melhor_linha"
    )

    if not melhor:
        return []

    blocos = melhor.get(
        "segmentos",
        [],
    )

    comps = componentes.get(
        "componentes",
        [],
    )

    resultado = []

    for indice, bloco in enumerate(
        blocos,
        start=1,
    ):
        centro_bloco = (
            bloco["x_inicio"]
            + bloco["x_fim"]
        ) / 2

        candidatos = []

        for comp in comps:
            distancia = abs(
                comp["centro_x"]
                - centro_bloco
            )

            # Janela deliberadamente ampla.
            # Nesta etapa queremos observar
            # a estrutura, não interpretar.
            if distancia <= 18:
                candidatos.append({
                    "distancia_centro_px":
                        round(
                            distancia,
                            1,
                        ),

                    "x_inicio":
                        comp["x_inicio"],

                    "x_fim":
                        comp["x_fim"],

                    "y_inicio":
                        comp["y_inicio"],

                    "y_fim":
                        comp["y_fim"],

                    "largura_px":
                        comp["largura_px"],

                    "altura_px":
                        comp["altura_px"],

                    "pixels_escuros":
                        comp["pixels_escuros"],

                    "desenho":
                        comp["desenho"],
                })

        candidatos.sort(
            key=lambda item:
                item[
                    "distancia_centro_px"
                ]
        )

        resultado.append({
            "indice_bloco":
                indice,

            "x_inicio_bloco":
                bloco["x_inicio"],

            "x_fim_bloco":
                bloco["x_fim"],

            "centro_x_bloco":
                round(
                    centro_bloco,
                    1,
                ),

            "rgba":
                bloco["rgba"],

            "componentes_proximos":
                candidatos,
        })

    return resultado


def analisar_legenda():
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

        rgba = imagem.convert(
            "RGBA"
        )

        pixels = list(
            rgba.getdata()
        )

        contador = Counter(
            p
            for p in pixels
            if p[3] > 0
        )

        cores_frequentes = [
            {
                "rgba":
                    list(cor),

                "pixels":
                    quantidade,
            }
            for cor, quantidade
            in contador.most_common(50)
        ]

        geometria = (
            analisar_geometria_legenda(
                rgba
            )
        )

        matriz_texto = (
            matriz_texto_legenda(
                rgba,
                y_inicio=13,
            )
        )

        componentes = (
            componentes_texto_legenda(
                rgba,
                y_inicio=13,
            )
        )

        associacao = (
            associar_componentes_blocos(
                geometria,
                componentes,
            )
        )

        return {
            "status":
                "online",

            "url_relativa":
                "img/legenda.png",

            "formato":
                formato,

            "modo_original":
                modo,

            "largura_px":
                largura,

            "altura_px":
                altura,

            "bytes":
                len(conteudo),

            "sha256":
                hashlib.sha256(
                    conteudo
                ).hexdigest(),

            "cores_distintas_visiveis":
                len(contador),

            "cores_mais_frequentes":
                cores_frequentes,

            "geometria":
                geometria,

            "leitura_caracteres": {
                "metodo":
                    (
                        "matriz_binaria_"
                        "componentes_conectados"
                    ),

                "limiar_luminancia":
                    150,

                "matriz_regiao_inferior":
                    matriz_texto,

                "componentes":
                    componentes,

                "associacao_com_blocos":
                    associacao,
            },

            "observacao":
                (
                    "Legenda oficial analisada "
                    "geometricamente e caracteres "
                    "inferiores convertidos para "
                    "matriz binária. Valores dBZ "
                    "ainda não atribuídos."
                ),
        }

    except Exception as erro:
        return {
            "status":
                "indisponivel",

            "url_relativa":
                "img/legenda.png",

            "erro":
                str(erro),
        }


def baixar_e_analisar_quadro(
    nome
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

    return {
        "bytes":
            len(conteudo),

        "sha256":
            hashlib.sha256(
                conteudo
            ).hexdigest(),

        "imagem":
            analisar_png(
                conteudo
            ),
    }


def buscar_radar():
    try:
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
                        tzinfo=ZoneInfo(
                            "UTC"
                        )
                    )
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
                    "arquivo":
                        nome,

                    "horario_utc":
                        data_utc.isoformat(),

                    "horario_local":
                        data_local.isoformat(),

                    "download":
                        "ok",

                    "bytes":
                        resultado["bytes"],

                    "sha256":
                        resultado["sha256"],

                    "imagem":
                        resultado["imagem"],
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
            if quadro.get(
                "download"
            ) == "ok"
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
                quadro[
                    "imagem"
                ][
                    "largura_px"
                ],

                quadro[
                    "imagem"
                ][
                    "altura_px"
                ],
            )
            for quadro
            in validos
        }

        legenda = (
            analisar_legenda()
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
                len(dimensoes) == 1,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

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
                    "caracteres_legenda_em_analise"
                    if legenda.get(
                        "status"
                    ) == "online"
                    else
                    "aguardando_legenda"
                ),

            "analise_movimento":
                "aguardando_validacao_paleta",
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


def main():
    agora = datetime.now(
        ZoneInfo(
            "America/Sao_Paulo"
        )
    )

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
