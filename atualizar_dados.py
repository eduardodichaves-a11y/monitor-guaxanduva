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

URL_MARE_CSV = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)

URL_RADAR_BASE = (
    "https://sifap.defesacivil.sc.gov.br/"
    "radarsc/rest/radar/"
)

URL_RADAR_LISTA = (
    URL_RADAR_BASE
    + "getUltimasImagens"
)

URL_RADAR_IMAGEM = (
    URL_RADAR_BASE
    + "getImagem"
)


# Coordenada pública aproximada do Comasa.
# NÃO representa endereço residencial.
LAT = -26.27
LON = -48.81


# Extensão geográfica oficial utilizada
# pela própria interface RadarSC para COMP.
RADAR_EXTENT = [
    -58.0651279,   # oeste
    -33.8163446,   # sul
    -46.4999942,   # leste
    -24.7653703,   # norte
]


# O servidor SIFAP/RadarSC apresenta
# problema conhecido na cadeia HTTPS.
# Desabilitamos apenas o aviso gerado
# pelas requisições específicas ao radar.
urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


def buscar_previsao():

    url = (
        "https://api.open-meteo.com/"
        "v1/forecast"
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

        tempos = horario.get(
            "time",
            [],
        )

        agora = datetime.now(
            ZoneInfo(
                "America/Sao_Paulo"
            )
        )

        indice = None

        for i, tempo in enumerate(
            tempos
        ):

            try:

                momento = (
                    datetime.fromisoformat(
                        tempo
                    )
                )

                momento = momento.replace(
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

        datas = diario.get(
            "time",
            [],
        )

        chuva_total = diario.get(
            "precipitation_sum",
            [],
        )

        probabilidade = diario.get(
            "precipitation_probability_max",
            [],
        )

        vento_max = diario.get(
            "wind_speed_10m_max",
            [],
        )

        rajada_max = diario.get(
            "wind_gusts_10m_max",
            [],
        )


        for i, data in enumerate(
            datas
        ):

            def diario_valor(lista):

                try:
                    return lista[i]

                except Exception:
                    return None


            dias.append({

                "data":
                    data,

                "probabilidade_chuva_pct":
                    diario_valor(
                        probabilidade
                    ),

                "precipitacao_total_mm":
                    diario_valor(
                        chuva_total
                    ),

                "vento_max_kmh":
                    diario_valor(
                        vento_max
                    ),

                "rajada_max_kmh":
                    diario_valor(
                        rajada_max
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

            linha = linha.strip()

            if not linha:
                continue

            partes = linha.split(";")

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

            hora_evento = (
                datetime.strptime(
                    evento["hora"],
                    "%H:%M",
                )
            )

            minutos_evento = (
                hora_evento.hour * 60
                + hora_evento.minute
            )

            if (
                minutos_evento
                <= agora_minutos
            ):

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

    oeste = RADAR_EXTENT[0]

    sul = RADAR_EXTENT[1]

    leste = RADAR_EXTENT[2]

    norte = RADAR_EXTENT[3]


    x = (
        (longitude - oeste)
        / (leste - oeste)
        * (largura - 1)
    )


    # Imagens têm origem no canto
    # superior esquerdo.
    y = (
        (norte - latitude)
        / (norte - sul)
        * (altura - 1)
    )


    x = int(
        round(x)
    )

    y = int(
        round(y)
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


def analisar_png(
    conteudo
):

    imagem = Image.open(
        io.BytesIO(
            conteudo
        )
    )

    formato = imagem.format

    largura, altura = imagem.size

    modo_original = imagem.mode


    # Convertemos para RGBA apenas para
    # análise. O arquivo original permanece
    # intacto.
    rgba = imagem.convert(
        "RGBA"
    )


    pixels = list(
        rgba.getdata()
    )


    total_pixels = len(
        pixels
    )


    pixels_transparentes = sum(
        1
        for pixel in pixels
        if pixel[3] == 0
    )


    pixels_visiveis = (
        total_pixels
        - pixels_transparentes
    )


    pixels_semitransparentes = sum(
        1
        for pixel in pixels
        if 0 < pixel[3] < 255
    )


    cores_visiveis = Counter(
        pixel
        for pixel in pixels
        if pixel[3] > 0
    )


    cores_mais_frequentes = []

    for cor, quantidade in (
        cores_visiveis
        .most_common(20)
    ):

        cores_mais_frequentes.append({

            "rgba": [
                int(cor[0]),
                int(cor[1]),
                int(cor[2]),
                int(cor[3]),
            ],

            "pixels":
                quantidade,
        })


    if total_pixels > 0:

        percentual_visivel = round(
            (
                pixels_visiveis
                / total_pixels
            )
            * 100,
            4,
        )

    else:

        percentual_visivel = 0


    x_comasa, y_comasa = (
        coordenada_para_pixel(
            LON,
            LAT,
            largura,
            altura,
        )
    )


    pixel_comasa = rgba.getpixel(
        (
            x_comasa,
            y_comasa,
        )
    )


    # Pequena janela de 11x11 pixels
    # em torno da referência aproximada
    # do Comasa.
    raio = 5

    x0 = max(
        0,
        x_comasa - raio,
    )

    x1 = min(
        largura - 1,
        x_comasa + raio,
    )

    y0 = max(
        0,
        y_comasa - raio,
    )

    y1 = min(
        altura - 1,
        y_comasa + raio,
    )


    janela = []

    for y in range(
        y0,
        y1 + 1,
    ):

        for x in range(
            x0,
            x1 + 1,
        ):

            janela.append(
                rgba.getpixel(
                    (x, y)
                )
            )


    janela_visiveis = [
        pixel
        for pixel in janela
        if pixel[3] > 0
    ]


    janela_cores = Counter(
        janela_visiveis
    )


    janela_mais_frequentes = []

    for cor, quantidade in (
        janela_cores
        .most_common(10)
    ):

        janela_mais_frequentes.append({

            "rgba": [
                int(cor[0]),
                int(cor[1]),
                int(cor[2]),
                int(cor[3]),
            ],

            "pixels":
                quantidade,
        })


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
            total_pixels,

        "pixels_transparentes":
            pixels_transparentes,

        "pixels_semitransparentes":
            pixels_semitransparentes,

        "pixels_visiveis":
            pixels_visiveis,

        "percentual_visivel":
            percentual_visivel,

        "cores_visiveis_distintas":
            len(
                cores_visiveis
            ),

        "cores_mais_frequentes":
            cores_mais_frequentes,

        "comasa": {

            "longitude_aproximada":
                LON,

            "latitude_aproximada":
                LAT,

            "pixel_x":
                x_comasa,

            "pixel_y":
                y_comasa,

            "pixel_rgba": [
                int(pixel_comasa[0]),
                int(pixel_comasa[1]),
                int(pixel_comasa[2]),
                int(pixel_comasa[3]),
            ],

            "janela_px":
                "11x11",

            "pixels_visiveis_janela":
                len(
                    janela_visiveis
                ),

            "cores_visiveis_janela":
                len(
                    janela_cores
                ),

            "cores_mais_frequentes_janela":
                janela_mais_frequentes,
        },
    }


def baixar_e_analisar_quadro(
    nome
):

    resposta = requests.get(

        URL_RADAR_IMAGEM,

        params={
            "prod":
                4,

            "radar":
                "COMP",

            "file":
                nome,
        },

        timeout=30,

        headers={
            "User-Agent":
                "Monitor-Guaxanduva/1.0"
        },

        # Exceção restrita ao RadarSC.
        verify=False,
    )


    resposta.raise_for_status()


    conteudo = resposta.content


    sha256 = hashlib.sha256(
        conteudo
    ).hexdigest()


    analise = analisar_png(
        conteudo
    )


    return {

        "bytes":
            len(conteudo),

        "sha256":
            sha256,

        "imagem":
            analise,
    }


def buscar_radar():

    try:

        r = requests.get(

            URL_RADAR_LISTA,

            params={
                "prod":
                    4,

                "radar":
                    "COMP",

                "data":
                    "",
            },

            timeout=30,

            headers={
                "User-Agent":
                    "Monitor-Guaxanduva/1.0"
            },

            verify=False,
        )


        r.raise_for_status()


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
                        resultado[
                            "bytes"
                        ],

                    "sha256":
                        resultado[
                            "sha256"
                        ],

                    "imagem":
                        resultado[
                            "imagem"
                        ],
                })


            except Exception as erro_quadro:

                quadros.append({

                    "arquivo":
                        nome,

                    "download":
                        "erro",

                    "erro":
                        str(
                            erro_quadro
                        ),
                })


        quadros_validos = [

            quadro

            for quadro in quadros

            if quadro.get(
                "download"
            ) == "ok"
        ]


        if not quadros_validos:

            raise ValueError(
                "Nenhum PNG do radar "
                "foi analisado com sucesso."
            )


        ultimo = (
            quadros_validos[-1]
        )


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


        idade_minutos = (
            agora_utc
            - ultimo_utc
        ).total_seconds() / 60


        idade_minutos = max(
            0,
            round(
                idade_minutos,
                1,
            ),
        )


        atualizado = (
            idade_minutos <= 30
        )


        todos_analisados = (
            len(
                quadros_validos
            )
            == len(
                imagens
            )
        )


        dimensoes = set()

        for quadro in quadros_validos:

            imagem = quadro.get(
                "imagem",
                {},
            )

            dimensoes.add(
                (
                    imagem.get(
                        "largura_px"
                    ),
                    imagem.get(
                        "altura_px"
                    ),
                )
            )


        dimensoes_consistentes = (
            len(dimensoes) == 1
        )


        return {

            "status":
                (
                    "online"
                    if (
                        atualizado
                        and todos_analisados
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
                RADAR_EXTENT,

            "quantidade_quadros":
                len(imagens),

            "quadros_png_validos":
                len(
                    quadros_validos
                ),

            "todos_png_validos":
                todos_analisados,

            "dimensoes_consistentes":
                dimensoes_consistentes,

            "quadros":
                quadros,

            "ultimo_quadro":
                ultimo,

            "idade_ultimo_quadro_min":
                idade_minutos,

            "dados_frescos":
                atualizado,

            "analise_pixels":
                "diagnostico_rgba_concluido",

            "interpretacao_dbz":
                "aguardando_validacao_paleta",

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
