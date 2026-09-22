import io
import json
import math
import hashlib
import statistics
import re
from urllib.parse import urljoin
from collections import Counter, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
 
import requests
import urllib3
from PIL import Image
 
 
# =========================================================
# CONFIGURAÇÃO
# =========================================================
 
ARQUIVO = "dados.json"
HISTORICO_ARQUIVO = "historico_validacao.json"
HISTORICO_MAX_REGISTROS = 2880
 
# Coordenada pública aproximada do Comasa.
# NÃO representa endereço residencial.
LAT = -26.27
LON = -48.81
IBGE_JOINVILLE = "4209102"
INMET_ATUAL = "https://apiprevmet3.inmet.gov.br/estacao/proxima/"
CEMADEN_RECURSOS = "https://resources.cemaden.gov.br"
CEMADEN_PLUV_24H = CEMADEN_RECURSOS + "/dados/311_24.json"
 
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
 
# Extensão geográfica oficial do produto COMP.
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
    resposta = requests.get(
        url,
        params=params,
        timeout=30,
        headers={
            "User-Agent": "Monitor-Guaxanduva/1.0"
        },
        verify=False if radar else True,
    )
    resposta.raise_for_status()
    return resposta
 
 
def hav(lat1, lon1, lat2, lon2):
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
# HISTÓRICO DE AUTOVALIDAÇÃO #120 - RECUPERADO NA #128
# =========================================================

def carregar_historico_validacao():
    try:
        with open(HISTORICO_ARQUIVO, "r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
        if not isinstance(dados, dict):
            raise ValueError("Formato de histórico inválido.")
        registros = dados.get("registros", [])
        return registros if isinstance(registros, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        print("Aviso: histórico anterior não pôde ser lido: " + str(e))
        return []


def registrar_historico_validacao(dados):
    radar = dados.get("radar", {})
    validacao = radar.get("autovalidacao_preditiva") or {}
    rastreamento = radar.get("rastreamento_temporal") or {}
    avaliacao = radar.get("avaliacao_trajetorias") or {}
    registro = {
        "gerado_em": dados.get("gerado_em"),
        "versao": "#136",
        "horario_ultimo_quadro": radar.get("horario_ultimo_quadro"),
        "radar_status": radar.get("status"),
        "dados_frescos": radar.get("dados_frescos"),
        "idade_ultimo_quadro_min": radar.get("idade_ultimo_quadro_min"),
        "total_previsoes_testadas": validacao.get("total_previsoes_testadas"),
        "erro_medio_km": validacao.get("erro_medio_km"),
        "erro_mediano_km": validacao.get("erro_mediano_km"),
        "erro_maximo_km": validacao.get("erro_maximo_km"),
        "quantidade_trilhas": rastreamento.get("quantidade_trilhas"),
        "quantidade_trilhas_elegiveis": rastreamento.get("quantidade_trilhas_elegiveis"),
        "quantidade_candidatos_eta": avaliacao.get("quantidade_candidatos_eta"),
        "eta_validado": False,
        "publicacao_automatica_eta": False,
    }
    registros = carregar_historico_validacao()
    chave = registro.get("horario_ultimo_quadro")
    if chave:
        registros = [x for x in registros if x.get("horario_ultimo_quadro") != chave]
    registros.append(registro)
    registros = registros[-HISTORICO_MAX_REGISTROS:]
    erros = [x.get("erro_medio_km") for x in registros if isinstance(x.get("erro_medio_km"),(int,float))]
    historico = {
        "monitor": "Monitor Guaxanduva",
        "tipo": "historico_autovalidacao_preditiva_radar",
        "versao": "#136",
        "metodo": "projecao_retrospectiva_1_quadro_com_velocidade_media",
        "atualizado_em": dados.get("gerado_em"),
        "maximo_registros": HISTORICO_MAX_REGISTROS,
        "politica_retencao": "Mantém no máximo 2880 quadros únicos de radar; aproximadamente 30 dias se houver atualização a cada 15 minutos.",
        "limite_aprovacao_definido": False,
        "usado_para_liberar_eta": False,
        "validado_para_eta": False,
        "resumo": {
            "execucoes_registradas": len(registros),
            "execucoes_com_erro_medio": len(erros),
            "total_previsoes_testadas_somadas": sum(x.get("total_previsoes_testadas") or 0 for x in registros),
            "media_dos_erros_medios_km": round(sum(erros)/len(erros),2) if erros else None,
            "limite_aprovacao_definido": False,
            "usado_para_liberar_eta": False,
            "validado_para_eta": False,
        },
        "registros": registros,
    }
    with open(HISTORICO_ARQUIVO,"w",encoding="utf-8") as arquivo:
        json.dump(historico,arquivo,ensure_ascii=False,indent=2)
    return historico


# =========================================================
# OPEN-METEO
# =========================================================
 
def buscar_previsao():
    try:
        params = {
            "latitude": LAT,
            "longitude": LON,
 
            "current": (
                "temperature_2m,"
                "precipitation,"
                "wind_speed_10m,"
                "wind_direction_10m,"
                "wind_gusts_10m"
            ),
 
            "hourly": (
                "temperature_2m,"
                "precipitation_probability,"
                "precipitation,"
                "wind_speed_10m,"
                "wind_direction_10m,"
                "wind_gusts_10m"
            ),
 
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
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
 
            prob_max = dv(
                "precipitation_probability_max"
            )

            horarios_prob_max = []
            probs_horarias = horario.get(
                "precipitation_probability",
                [],
            )

            for j, texto_hora in enumerate(
                horario.get("time", [])
            ):
                try:
                    if not str(texto_hora).startswith(str(data)):
                        continue
                    if j >= len(probs_horarias):
                        continue
                    valor_prob = probs_horarias[j]
                    if (
                        valor_prob is not None
                        and prob_max is not None
                        and float(valor_prob) == float(prob_max)
                    ):
                        horarios_prob_max.append(
                            str(texto_hora)[11:16]
                        )
                except Exception:
                    pass

            dias.append({
                "data":
                    data,

                "temperatura_min_c":
                    dv(
                        "temperature_2m_min"
                    ),

                "temperatura_max_c":
                    dv(
                        "temperature_2m_max"
                    ),
 
                "probabilidade_chuva_pct":
                    prob_max,

                "horarios_probabilidade_max":
                    horarios_prob_max,
 
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

                "temperatura_c":
                    atual.get(
                        "temperature_2m"
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
                    hv("time"),

                "temperatura_c":
                    hv(
                        "temperature_2m"
                    ),
 
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
 
            "proximos_7_dias":
                dias,
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
 
    except Exception as e:
        return {
            "status":
                "indisponivel",
 
            "fonte":
                "EPAGRI/CIRAM",
 
            "tipo":
                "tabua_de_mare_prevista",
 
            "erro":
                str(e),
        }
 
 
# =========================================================
# #128 - INVESTIGAÇÃO DOCUMENTAL DO RADARSC
# =========================================================

def investigar_fonte_radarsc():
    """Procura evidência textual de dBZ/escala no HTML e JS oficiais.
    É diagnóstico documental: não atribui dBZ e não libera ETA.
    """
    resultado = {
        "status": "sem_evidencia_textual",
        "fonte": RADAR,
        "termos": ["dbz", "reflectivity", "refletividade", "c-max", "cmax"],
        "recursos_avaliados": [],
        "evidencias": [],
        "dbz_numerico_validado": False,
        "eta_liberado": False,
    }
    try:
        html = get(RADAR, radar=True).text
        recursos = [(RADAR, html)]
        scripts = re.findall(r'<script[^>]+src=["\\\']([^"\\\']+)["\\\']', html, flags=re.I)
        for src in scripts[:30]:
            url = urljoin(RADAR, src)
            try:
                texto = get(url, radar=True).text
                recursos.append((url, texto))
            except Exception as e:
                resultado["recursos_avaliados"].append({"url": url, "status": "erro", "erro": str(e)[:180]})
        for url, texto in recursos:
            baixo = texto.lower()
            achados = []
            for termo in resultado["termos"]:
                inicio = 0
                while len(achados) < 12:
                    pos = baixo.find(termo, inicio)
                    if pos < 0: break
                    a=max(0,pos-140); b=min(len(texto),pos+220)
                    trecho=re.sub(r'\\s+',' ',texto[a:b]).strip()
                    achados.append({"termo": termo, "trecho": trecho[:500]})
                    inicio=pos+len(termo)
            resultado["recursos_avaliados"].append({"url":url,"status":"ok","bytes_texto":len(texto),"ocorrencias_relevantes":len(achados)})
            for item in achados:
                resultado["evidencias"].append({"url":url,**item})
        if resultado["evidencias"]:
            resultado["status"]="evidencia_textual_encontrada_para_revisao"
        resultado["observacao"]="Trechos são evidência bruta para revisão; nenhuma associação RGB→dBZ é aceita automaticamente."
        return resultado
    except Exception as e:
        resultado["status"]="indisponivel"
        resultado["erro"]=str(e)
        return resultado


# =========================================================
# LEGENDA OFICIAL RADARSC
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
                "rgb": list(segmento[2][:3]),
                "x_inicio": segmento[0],
                "x_fim": segmento[1],
                "largura_px": segmento[1] - segmento[0] + 1,
                "dbz": None,
            })
 
        return {
            "status":
                "online",
 
            "fonte":
                "legenda oficial RadarSC",

            "dimensoes_px": {"largura": imagem.width, "altura": imagem.height},

            "diagnostico_128": "RGB e geometria extraídos diretamente da legenda oficial; dBZ continua sem atribuição até evidência textual oficial.",
 
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
            "status":
                "indisponivel",
 
            "erro":
                str(e),
        }
 
 
# =========================================================
# #127 - VALIDACAO CRUZADA LEGENDA x PALETA DO RADAR
# =========================================================
 
def validar_paleta_radar(legenda_oficial, quadros_validos):
    """
    #127
 
    Corrige a leitura do diagnostico de paleta dos PNGs e cruza as cores extraidas da legenda oficial com as paletas dos PNGs
    efetivamente recebidos do RadarSC. E uma validacao estrutural de cor:
    NAO atribui dBZ, NAO transforma pixel em chuva medida e NAO libera ETA.
    """
    classes = (
        legenda_oficial.get("classes", [])
        if isinstance(legenda_oficial, dict)
        else []
    )
 
    cores_legenda = {
        tuple(item.get("rgb", []))
        for item in classes
        if isinstance(item, dict)
        and len(item.get("rgb", [])) == 3
    }
 
    cores_legenda.discard(CINZA)
 
    if not cores_legenda:
        return {
            "status": "indisponivel",
            "validacao_estrutural": False,
            "motivo": "Legenda oficial sem classes RGB utilizaveis.",
            "dbz_numerico_validado": False,
            "eta_liberado": False,
        }
 
    por_quadro = []
    uniao_radar = set()
 
    for quadro in quadros_validos:
        diagnostico_png = (
            quadro.get("diagnostico_paleta_png")
            or quadro.get("diagnostico_png")
            or {}
        )
        indices = diagnostico_png.get("indices_usados") or []
 
        cores_quadro = {
            tuple(item.get("rgb", []))
            for item in indices
            if isinstance(item, dict)
            and item.get("visivel")
            and len(item.get("rgb", [])) == 3
        }
 
        uniao_radar.update(cores_quadro)
        correspondentes = cores_legenda & cores_quadro
 
        por_quadro.append({
            "arquivo": quadro.get("arquivo"),
            "classes_legenda_presentes": len(correspondentes),
            "classes_legenda_total": len(cores_legenda),
            "rgb_correspondentes": [
                list(cor)
                for cor in sorted(correspondentes)
            ],
        })
 
    correspondentes_uniao = cores_legenda & uniao_radar
    ausentes = cores_legenda - uniao_radar
 
    estrutural = bool(correspondentes_uniao)
 
    return {
        "status": (
            "compatibilidade_rgb_observada"
            if estrutural
            else "sem_correspondencia_rgb_observada"
        ),
        "validacao_estrutural": estrutural,
        "metodo": "intersecao_rgb_legenda_oficial_x_paletas_png_#127",
        "classes_legenda_total": len(cores_legenda),
        "classes_legenda_observadas": len(correspondentes_uniao),
        "rgb_observados": [
            list(cor)
            for cor in sorted(correspondentes_uniao)
        ],
        "rgb_legenda_ainda_nao_observados": [
            list(cor)
            for cor in sorted(ausentes)
        ],
        "quadros_avaliados": len(quadros_validos),
        "por_quadro": por_quadro,
        "dbz_numerico_validado": False,
        "eta_liberado": False,
        "regra_seguranca": (
            "Correspondencia RGB valida compatibilidade estrutural da paleta; "
            "nao valida valores numericos de dBZ, nao equivale a chuva medida "
            "e nao autoriza publicacao automatica de ETA."
        ),
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
            "status":
                "modo_inesperado",
 
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
        "status":
            "online",
 
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
# #133 - MÁSCARA OPERACIONAL SOMENTE COM CORES OFICIAIS
# =========================================================

def mascara_oficial_133(imagem, legenda_oficial):
    """Seleciona exclusivamente pixels cujo RGB coincide exatamente com
    uma classe extraída da legenda oficial RadarSC.

    Esta máscara passa a alimentar componentes, trilhas e autovalidação.
    Não converte cor em dBZ/mm/h e não libera ETA.
    """
    if imagem.mode != "P":
        return set(), {}, {}

    classes = (legenda_oficial or {}).get("classes") or []
    mapa_rgb_classe = {}
    for item in classes:
        if not isinstance(item, dict):
            continue
        rgb = item.get("rgb")
        classe = item.get("classe")
        if isinstance(rgb, list) and len(rgb) == 3 and classe is not None:
            mapa_rgb_classe[tuple(int(v) for v in rgb)] = int(classe)

    if not mapa_rgb_classe:
        return set(), {}, {}

    paleta = imagem.getpalette()
    transparencia = imagem.info.get("transparency")
    indices = {}
    classes_por_indice = {}

    for indice in set(imagem.getdata()):
        rgb = rgb_idx(paleta, indice)
        if (
            alpha_idx(transparencia, indice) > 0
            and rgb is not None
            and tuple(rgb) in mapa_rgb_classe
        ):
            indices[indice] = rgb
            classes_por_indice[indice] = mapa_rgb_classe[tuple(rgb)]

    pixels = imagem.load()
    pontos = {
        (x, y)
        for y in range(imagem.height)
        for x in range(imagem.width)
        if pixels[x, y] in indices
    }

    return pontos, indices, classes_por_indice
 
 
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
 
        "dbz":
            None,
 
        "classificacao":
            "candidato_a_area_de_eco",
    }
 
 
def analisar(imagem, legenda_oficial=None):
    pontos, indices, classes_por_indice = mascara_oficial_133(
        imagem,
        legenda_oficial,
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
                "sem_pixels_oficiais",
 
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
            "componentes_conectados_8_vizinhos_rgb_oficial_#133",

        "fonte_mascara":
            "somente_rgb_exato_da_legenda_oficial_radarsc",

        "dbz_numerico_validado":
            False,

        "eta_liberado":
            False,
 
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

                "classe_oficial":
                    classes_por_indice.get(indice),
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
# #118
# ASSINATURA DA CÉLULA
# =========================================================
 
def histograma_cores(componente):
    total = max(
        1,
        componente.get(
            "pixels",
            1,
        ),
    )
 
    hist = {}
 
    for item in componente.get(
        "cores",
        []
    ):
        rgb = tuple(
            item.get(
                "rgb",
                []
            )
        )
 
        if len(rgb) != 3:
            continue
 
        hist[rgb] = (
            item.get(
                "pixels",
                0,
            )
            / total
        )
 
    return hist
 
 
def similaridade_cores(a, b):
    """
    Interseção entre histogramas normalizados.
    1 = composição de cores muito semelhante.
    0 = sem cores compartilhadas.
    """
    ha = histograma_cores(a)
    hb = histograma_cores(b)
 
    if not ha or not hb:
        return 0.0
 
    cores = set(ha) | set(hb)
 
    return sum(
        min(
            ha.get(cor, 0),
            hb.get(cor, 0),
        )
        for cor in cores
    )
 
 
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
        return 0.0
 
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
        return 0.0
 
    return inter / menor
 
 
def assinatura_movimento(a, b, minutos):
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
 
    ca = a["centroide"]
    cb = b["centroide"]
 
    direcao = rumo(
        ca["latitude"],
        ca["longitude"],
        cb["latitude"],
        cb["longitude"],
    )
 
    return {
        "distancia_km":
            distancia,
 
        "velocidade_kmh":
            velocidade,
 
        "direcao_graus":
            direcao,
    }
 
 
def pontuar_identidade(
    a,
    b,
    minutos,
    direcao_anterior=None,
    velocidade_anterior=None,
):
    """
    #118
 
    O componente seguinte precisa ser compatível com:
 
    - posição;
    - tamanho;
    - caixa espacial;
    - assinatura de cores;
    - direção histórica;
    - velocidade histórica.
 
    Isso reduz trocas de identidade entre células próximas.
    """
 
    movimento = assinatura_movimento(
        a,
        b,
        minutos,
    )
 
    if movimento is None:
        return None
 
    distancia = movimento[
        "distancia_km"
    ]
 
    velocidade = movimento[
        "velocidade_kmh"
    ]
 
    direcao = movimento[
        "direcao_graus"
    ]
 
    # Limites físicos/conservadores.
    if (
        distancia > 25
        or velocidade > 150
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
 
    cores = similaridade_cores(
        a,
        b,
    )
 
    # Se mudou radicalmente de tamanho,
    # não sobrepõe e ainda perdeu assinatura
    # de cor, provavelmente não é a mesma célula.
    if (
        razao_tamanho < 0.15
        and sobreposicao == 0
        and cores < 0.20
    ):
        return None
 
    score_posicao = max(
        0.0,
        1 - distancia / 25,
    )
 
    score_tamanho = razao_tamanho
 
    score_sobreposicao = min(
        1.0,
        sobreposicao,
    )
 
    score_cores = min(
        1.0,
        cores,
    )
 
    # Base sem memória histórica.
    score = (
        score_posicao * 0.40
        + score_tamanho * 0.20
        + score_sobreposicao * 0.15
        + score_cores * 0.25
    )
 
    diferenca_direcao = None
    coerencia_direcao = None
 
    if direcao_anterior is not None:
        diferenca_direcao = difang(
            direcao,
            direcao_anterior,
        )
 
        # Guinada extrema: troca de identidade
        # muito provável.
        if diferenca_direcao > 100:
            return None
 
        coerencia_direcao = max(
            0.0,
            1 - diferenca_direcao / 100,
        )
 
        # A memória cinemática passa a ter peso
        # real no casamento.
        score = (
            score * 0.72
            + coerencia_direcao * 0.28
        )
 
        # Guinadas entre 60° e 100° não são
        # impossíveis, mas precisam pagar
        # penalidade forte.
        if diferenca_direcao > 60:
            score *= 0.70
 
        elif diferenca_direcao > 40:
            score *= 0.85
 
    diferenca_velocidade_pct = None
 
    if (
        velocidade_anterior is not None
        and velocidade_anterior >= 5
    ):
        diferenca_velocidade_pct = (
            abs(
                velocidade
                - velocidade_anterior
            )
            / velocidade_anterior
        )
 
        # Mudança brutal simultânea de velocidade
        # é outro indício de troca de célula.
        if diferenca_velocidade_pct > 2.0:
            score *= 0.65
 
        elif diferenca_velocidade_pct > 1.0:
            score *= 0.82
 
    return {
        "score":
            score,
 
        "distancia_km":
            distancia,
 
        "velocidade_kmh":
            velocidade,
 
        "direcao_graus":
            direcao,
 
        "razao_tamanho":
            razao_tamanho,
 
        "sobreposicao_caixas":
            sobreposicao,
 
        "similaridade_cores":
            cores,
 
        "diferenca_direcao_historica_graus":
            diferenca_direcao,
 
        "coerencia_direcao":
            coerencia_direcao,
 
        "diferenca_velocidade_historica_pct":
            diferenca_velocidade_pct,
    }
 
 
# =========================================================
# #118
# RASTREAMENTO COM MEMÓRIA TEMPORAL
# =========================================================
 
def componentes_quadro(quadro):
    return (
        quadro
        .get(
            "analise_espacial",
            {},
        )
        .get(
            "maiores_componentes",
            [],
        )
    )
 
 
def movimento_medio_trilha(passos):
    """
    Memória recente da trilha.
 
    Usa até os três últimos passos para evitar
    que um único deslocamento ruidoso domine
    a identidade da célula.
    """
 
    if not passos:
        return None, None
 
    recentes = passos[-3:]
 
    direcoes = []
    velocidades = []
 
    for passo in recentes:
        score = max(
            0.01,
            passo.get(
                "score",
                0.01,
            ),
        )
 
        direcoes.append(
            (
                passo[
                    "direcao_movimento_graus"
                ],
                score,
            )
        )
 
        velocidade = passo.get(
            "velocidade_estimada_kmh"
        )
 
        if velocidade is not None:
            velocidades.append(
                (
                    velocidade,
                    score,
                )
            )
 
    direcao = (
        media_angular_ponderada(
            direcoes
        )
        if direcoes
        else None
    )
 
    if velocidades:
        pesos = sum(
            peso
            for _, peso
            in velocidades
        )
 
        velocidade = (
            sum(
                valor * peso
                for valor, peso
                in velocidades
            )
            / pesos
        )
 
    else:
        velocidade = None
 
    return direcao, velocidade
 
 
def criar_passo(
    anterior,
    atual,
    avaliacao,
    horario_de,
    horario_para,
):
    ca = anterior[
        "centroide"
    ]
 
    cb = atual[
        "centroide"
    ]
 
    distancia_a = ca[
        "distancia_comasa_km"
    ]
 
    distancia_b = cb[
        "distancia_comasa_km"
    ]
 
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
 
    return {
        "de":
            horario_de,
 
        "para":
            horario_para,
 
        "componente_anterior":
            anterior[
                "id_quadro"
            ],
 
        "componente_atual":
            atual[
                "id_quadro"
            ],
 
        "score":
            round(
                avaliacao["score"],
                3,
            ),
 
        "deslocamento_centroide_km":
            round(
                avaliacao[
                    "distancia_km"
                ],
                2,
            ),
 
        "velocidade_estimada_kmh":
            round(
                avaliacao[
                    "velocidade_kmh"
                ],
                1,
            ),
 
        "direcao_movimento_graus":
            round(
                avaliacao[
                    "direcao_graus"
                ],
                1,
            ),
 
        "direcao_movimento_cardinal":
            cardinal(
                avaliacao[
                    "direcao_graus"
                ]
            ),
 
        "razao_tamanho":
            round(
                avaliacao[
                    "razao_tamanho"
                ],
                3,
            ),
 
        "sobreposicao_caixas":
            round(
                avaliacao[
                    "sobreposicao_caixas"
                ],
                3,
            ),
 
        "similaridade_cores":
            round(
                avaliacao[
                    "similaridade_cores"
                ],
                3,
            ),
 
        "diferenca_direcao_historica_graus":
            (
                round(
                    avaliacao[
                        "diferenca_direcao_historica_graus"
                    ],
                    1,
                )
                if avaliacao[
                    "diferenca_direcao_historica_graus"
                ]
                is not None
                else None
            ),
 
        "coerencia_direcao":
            (
                round(
                    avaliacao[
                        "coerencia_direcao"
                    ],
                    3,
                )
                if avaliacao[
                    "coerencia_direcao"
                ]
                is not None
                else None
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
    }
 
 
def rastrear(quadros):
    """
    #118
 
    Diferentemente do #117, o casamento não é
    mais decidido isoladamente entre cada par
    de quadros.
 
    Cada trilha carrega sua própria memória.
    """
 
    if len(quadros) < 2:
        return {
            "status":
                "dados_insuficientes",
 
            "versao":
                "#133_rgb_oficial_identidade_temporal",
 
            "trilhas":
                [],
        }
 
    trilhas = []
    ativas = {}
    proximo_id = 1
 
    diagnostico_quadros = []
 
    # =====================================================
    # PRIMEIRO PAR
    # =====================================================
 
    primeiro = quadros[0]
    segundo = quadros[1]
 
    comps_a = componentes_quadro(
        primeiro
    )
 
    comps_b = componentes_quadro(
        segundo
    )
 
    ta = datetime.fromisoformat(
        primeiro["horario_utc"]
    )
 
    tb = datetime.fromisoformat(
        segundo["horario_utc"]
    )
 
    minutos = (
        tb - ta
    ).total_seconds() / 60
 
    candidatos = []
 
    for a in comps_a:
        for b in comps_b:
            avaliacao = pontuar_identidade(
                a,
                b,
                minutos,
            )
 
            if (
                avaliacao
                and avaliacao["score"]
                >= 0.40
            ):
                candidatos.append(
                    (
                        avaliacao["score"],
                        a,
                        b,
                        avaliacao,
                    )
                )
 
    candidatos.sort(
        key=lambda x: x[0],
        reverse=True,
    )
 
    usados_a = set()
    usados_b = set()
 
    aceitos = 0
 
    for _, a, b, avaliacao in candidatos:
        ia = a["id_quadro"]
        ib = b["id_quadro"]
 
        if (
            ia in usados_a
            or ib in usados_b
        ):
            continue
 
        usados_a.add(ia)
        usados_b.add(ib)
 
        passo = criar_passo(
            a,
            b,
            avaliacao,
            primeiro["horario_local"],
            segundo["horario_local"],
        )
 
        trilha = {
            "id_trilha":
                proximo_id,
 
            "passos":
                [passo],
 
            "ultimo_componente":
                b,
 
            "ultimo_indice_quadro":
                1,
        }
 
        proximo_id += 1
 
        trilhas.append(
            trilha
        )
 
        ativas[
            b["id_quadro"]
        ] = trilha
 
        aceitos += 1
 
    diagnostico_quadros.append({
        "de":
            primeiro[
                "horario_local"
            ],
 
        "para":
            segundo[
                "horario_local"
            ],
 
        "candidatos":
            len(candidatos),
 
        "casamentos_aceitos":
            aceitos,
 
        "metodo":
            "assinatura_sem_historico_inicial",
    })
 
    # =====================================================
    # DEMAIS QUADROS
    # AGORA COM MEMÓRIA
    # =====================================================
 
    for indice in range(
        2,
        len(quadros),
    ):
        anterior_quadro = quadros[
            indice - 1
        ]
 
        atual_quadro = quadros[
            indice
        ]
 
        componentes_atuais = (
            componentes_quadro(
                atual_quadro
            )
        )
 
        ta = datetime.fromisoformat(
            anterior_quadro[
                "horario_utc"
            ]
        )
 
        tb = datetime.fromisoformat(
            atual_quadro[
                "horario_utc"
            ]
        )
 
        minutos = (
            tb - ta
        ).total_seconds() / 60
 
        candidatos = []
 
        # Somente trilhas que realmente chegaram
        # ao quadro anterior podem continuar.
        trilhas_continuaveis = [
            trilha
            for trilha in trilhas
            if trilha[
                "ultimo_indice_quadro"
            ] == indice - 1
        ]
 
        for trilha in trilhas_continuaveis:
            anterior = trilha[
                "ultimo_componente"
            ]
 
            direcao_memoria, velocidade_memoria = (
                movimento_medio_trilha(
                    trilha["passos"]
                )
            )
 
            for atual in componentes_atuais:
                avaliacao = pontuar_identidade(
                    anterior,
                    atual,
                    minutos,
                    direcao_anterior=
                        direcao_memoria,
                    velocidade_anterior=
                        velocidade_memoria,
                )
 
                if (
                    avaliacao
                    and avaliacao["score"]
                    >= 0.42
                ):
                    candidatos.append({
                        "score":
                            avaliacao[
                                "score"
                            ],
 
                        "trilha":
                            trilha,
 
                        "anterior":
                            anterior,
 
                        "atual":
                            atual,
 
                        "avaliacao":
                            avaliacao,
                    })
 
        candidatos.sort(
            key=lambda x:
                x["score"],
            reverse=True,
        )
 
        trilhas_usadas = set()
        componentes_usados = set()
 
        aceitos = 0
        rejeitados_conflito = 0
 
        for candidato in candidatos:
            trilha = candidato[
                "trilha"
            ]
 
            atual = candidato[
                "atual"
            ]
 
            tid = trilha[
                "id_trilha"
            ]
 
            cid = atual[
                "id_quadro"
            ]
 
            if (
                tid in trilhas_usadas
                or cid in componentes_usados
            ):
                rejeitados_conflito += 1
                continue
 
            passo = criar_passo(
                candidato[
                    "anterior"
                ],
 
                atual,
 
                candidato[
                    "avaliacao"
                ],
 
                anterior_quadro[
                    "horario_local"
                ],
 
                atual_quadro[
                    "horario_local"
                ],
            )
 
            trilha[
                "passos"
            ].append(
                passo
            )
 
            trilha[
                "ultimo_componente"
            ] = atual
 
            trilha[
                "ultimo_indice_quadro"
            ] = indice
 
            trilhas_usadas.add(
                tid
            )
 
            componentes_usados.add(
                cid
            )
 
            aceitos += 1
 
        # Componentes que não foram ligados a
        # trilhas antigas podem iniciar novas
        # trilhas usando o quadro imediatamente
        # anterior.
        comps_prev = componentes_quadro(
            anterior_quadro
        )
 
        candidatos_novos = []
 
        for a in comps_prev:
            for b in componentes_atuais:
                if (
                    b["id_quadro"]
                    in componentes_usados
                ):
                    continue
 
                avaliacao = pontuar_identidade(
                    a,
                    b,
                    minutos,
                )
 
                if (
                    avaliacao
                    and avaliacao["score"]
                    >= 0.45
                ):
                    candidatos_novos.append(
                        (
                            avaliacao["score"],
                            a,
                            b,
                            avaliacao,
                        )
                    )
 
        candidatos_novos.sort(
            key=lambda x: x[0],
            reverse=True,
        )
 
        anteriores_novos = set()
 
        for _, a, b, avaliacao in candidatos_novos:
            ia = a[
                "id_quadro"
            ]
 
            ib = b[
                "id_quadro"
            ]
 
            if (
                ia in anteriores_novos
                or ib in componentes_usados
            ):
                continue
 
            passo = criar_passo(
                a,
                b,
                avaliacao,
                anterior_quadro[
                    "horario_local"
                ],
                atual_quadro[
                    "horario_local"
                ],
            )
 
            trilha = {
                "id_trilha":
                    proximo_id,
 
                "passos":
                    [passo],
 
                "ultimo_componente":
                    b,
 
                "ultimo_indice_quadro":
                    indice,
            }
 
            proximo_id += 1
 
            trilhas.append(
                trilha
            )
 
            anteriores_novos.add(
                ia
            )
 
            componentes_usados.add(
                ib
            )
 
        diagnostico_quadros.append({
            "de":
                anterior_quadro[
                    "horario_local"
                ],
 
            "para":
                atual_quadro[
                    "horario_local"
                ],
 
            "trilhas_com_memoria":
                len(
                    trilhas_continuaveis
                ),
 
            "candidatos_com_memoria":
                len(candidatos),
 
            "casamentos_aceitos":
                aceitos,
 
            "conflitos_rejeitados":
                rejeitados_conflito,
 
            "novas_trilhas_iniciadas":
                len(
                    anteriores_novos
                ),
 
            "metodo":
                "identidade_temporal_com_memoria",
        })
 
    # =====================================================
    # RESUMO DAS TRILHAS
    # =====================================================
 
    resumos = []
 
    for trilha in trilhas:
        passos = trilha[
            "passos"
        ]
 
        if not passos:
            continue
 
        aproximando = sum(
            p[
                "tendencia_relativa_comasa"
            ] == "aproximando"
 
            for p in passos
        )
 
        afastando = sum(
            p[
                "tendencia_relativa_comasa"
            ] == "afastando"
 
            for p in passos
        )
 
        if aproximando > afastando:
            tendencia = "aproximando"
 
        elif afastando > aproximando:
            tendencia = "afastando"
 
        else:
            tendencia = "indeterminada"
 
        direcoes = [
            p[
                "direcao_movimento_graus"
            ]
            for p in passos
        ]
 
        if len(direcoes) >= 2:
            media_dir = (
                media_angular_ponderada(
                    [
                        (
                            p[
                                "direcao_movimento_graus"
                            ],
                            max(
                                0.01,
                                p["score"],
                            ),
                        )
                        for p in passos
                    ]
                )
            )
 
            dispersoes = [
                difang(
                    d,
                    media_dir,
                )
                for d in direcoes
            ]
 
            dispersao_media = (
                sum(dispersoes)
                / len(dispersoes)
            )
 
            dispersao_max = max(
                dispersoes
            )
 
        else:
            media_dir = (
                direcoes[0]
                if direcoes
                else None
            )
 
            dispersao_media = 0
            dispersao_max = 0
 
        scores = [
            p["score"]
            for p in passos
        ]
 
        velocidades = [
            p[
                "velocidade_estimada_kmh"
            ]
            for p in passos
        ]
 
        similaridades = [
            p[
                "similaridade_cores"
            ]
            for p in passos
        ]
 
        resumos.append({
            "id_trilha":
                trilha[
                    "id_trilha"
                ],
 
            "transicoes":
                len(passos),
 
            "elegivel_para_analise":
                len(passos) >= 3,
 
            "score_medio":
                round(
                    sum(scores)
                    / len(scores),
                    3,
                ),
 
            "velocidade_media_kmh":
                round(
                    sum(velocidades)
                    / len(velocidades),
                    1,
                ),
 
            "similaridade_cores_media":
                round(
                    sum(similaridades)
                    / len(similaridades),
                    3,
                ),
 
            "direcao_media_graus":
                (
                    round(
                        media_dir,
                        1,
                    )
                    if media_dir
                    is not None
                    else None
                ),
 
            "direcao_media_cardinal":
                cardinal(
                    media_dir
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
                "dispersao_direcao_max_graus"
            ],
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
            "rastreamento_identidade_temporal_experimental",
 
        "versao":
            "#118",
 
        "criterios": {
            "distancia_max_centroide_km":
                25,
 
            "velocidade_max_kmh":
                150,
 
            "score_inicial_minimo":
                0.40,
 
            "score_memoria_minimo":
                0.42,
 
            "guinada_rejeicao_graus":
                100,
 
            "guinada_penalidade_forte_graus":
                60,
 
            "minimo_transicoes_trilha":
                3,
 
            "assinatura_cores":
                True,
 
            "memoria_direcional":
                True,
 
            "memoria_velocidade":
                True,
        },
 
        "diagnostico_por_par":
            diagnostico_quadros,
 
        "quantidade_trilhas":
            len(resumos),
 
        "quantidade_trilhas_elegiveis":
            len(elegiveis),
 
        "trilhas":
            resumos[:30],
 
        "trilha_principal_diagnostica":
            principal,
 
        "observacao":
            (
                "O #118 mantém identidade temporal "
                "da célula usando posição, tamanho, "
                "sobreposição, assinatura de cores "
                "e memória cinemática. ETA continua "
                "experimental e não validado."
            ),
    }
 
 
# =========================================================
# TRAJETÓRIA MULTIVETORIAL
# =========================================================
 
def analisar_interceptacao(
    trilha,
    radar_fresco,
    idade_radar,
    horario_ultimo_quadro,
):
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
                    "São necessárias pelo menos "
                    "3 transições para analisar "
                    "trajetória."
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
                "Vetor médio recente pequeno demais.",
 
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
                "Rumo médio não disponível.",
 
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
 
    ux = vx / norma
    uy = vy / norma
 
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
 
    projecao_adiante = (
        alvo_x * ux
        + alvo_y * uy
    )
 
    distancia_lateral = abs(
        alvo_x * uy
        - alvo_y * ux
    )
 
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
 
    base = {
        "status":
            "diagnostico",
 
        "versao_metodo":
            "#133_rgb_oficial_identidade_temporal_multivetorial",
 
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
 
        "similaridade_cores_media":
            trilha.get(
                "similaridade_cores_media"
            ),
 
        "intercepta_corredor":
            intercepta,
 
        "candidato_eta":
            False,
 
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
            horario_ultimo_quadro
            .isoformat(),
 
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
                "Confiança geométrica insuficiente.",
 
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
                    "Trajetória recente instável "
                    "ou em zigue-zague."
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
                    "Comasa está atrás do vetor "
                    "de deslocamento."
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
                    "suficientemente para o Comasa."
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
                    "Trajetória projetada passa "
                    "fora do corredor de 15 km "
                    "do Comasa."
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
                    "Linha projetada não intercepta "
                    "matematicamente o corredor."
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
                        "Interseção está atrás da "
                        "direção de deslocamento."
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
                    "Interseção fora da janela "
                    "experimental de 180 minutos."
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
 
    if horario_entrada < agora_utc:
        return {
            **base,
 
            "status":
                "bloqueado",
 
            "motivo":
                (
                    "A projeção calculada já "
                    "estaria no passado."
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
        and trilha["score_medio"] >= 0.70
        and diferenca_angular <= 20
        and dispersao_max <= 25
        and distancia_lateral <= 7.5
    ):
        confianca = "alta_experimental"
 
    elif (
        trilha["transicoes"] >= 4
        and trilha["score_medio"] >= 0.60
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
                "Trilha persistente, radar fresco "
                "e trajetória multivetorial "
                "compatível com o corredor."
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
                    "intensificar, dissipar, acelerar "
                    "ou mudar de direção."
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
 
            "similaridade_cores_media":
                trilha.get(
                    "similaridade_cores_media"
                ),
 
            "dispersao_direcao_max_graus":
                trilha.get(
                    "dispersao_direcao_max_graus"
                ),
 
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
 
        "versao":
            "#118",
 
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
                "o ETA permanece experimental e "
                "não validado para publicação."
            ),
    }
 
 
# =========================================================


# =========================================================
# #134 - AUDITORIA FÍSICA PRELIMINAR DAS TRILHAS OFICIAIS
# =========================================================

def auditoria_fisica_trilhas_134(rastreamento):
    """Audita coerência cinemática das trilhas #133 sem liberar ETA."""
    trilhas = (rastreamento or {}).get("trilhas", [])
    elegiveis = [t for t in trilhas if t.get("elegivel_para_analise")]
    itens = []

    for trilha in elegiveis:
        passos = trilha.get("passos") or []
        velocidades = [
            p.get("velocidade_estimada_kmh")
            for p in passos
            if isinstance(p.get("velocidade_estimada_kmh"), (int, float))
        ]
        velocidades_faixa_eta = [v for v in velocidades if 5 <= v <= 120]
        velocidades_faixa_rastreio = [v for v in velocidades if 0 <= v <= 150]

        transicoes = trilha.get("transicoes") or 0
        score = trilha.get("score_medio")
        dispersao = trilha.get("dispersao_direcao_max_graus")
        similaridade = trilha.get("similaridade_cores_media")

        criterios = {
            "transicoes_minimas_3": transicoes >= 3,
            "score_geometrico_minimo_0_55": isinstance(score, (int, float)) and score >= 0.55,
            "direcao_estavel_max_45_graus": isinstance(dispersao, (int, float)) and dispersao <= 45,
            "ao_menos_2_passos_velocidade_5_120": len(velocidades_faixa_eta) >= 2,
            "nenhum_passo_acima_limite_rastreio_150": len(velocidades_faixa_rastreio) == len(velocidades),
        }
        falhas = [nome for nome, ok in criterios.items() if not ok]

        if velocidades:
            vel_min = round(min(velocidades), 1)
            vel_max = round(max(velocidades), 1)
            vel_media = round(sum(velocidades) / len(velocidades), 1)
            amplitude = round(vel_max - vel_min, 1)
        else:
            vel_min = vel_max = vel_media = amplitude = None

        itens.append({
            "id_trilha": trilha.get("id_trilha"),
            "status": "coerente_para_estudo" if not falhas else "requer_revisao",
            "transicoes": transicoes,
            "score_medio": score,
            "similaridade_cores_media": similaridade,
            "direcao_media_graus": trilha.get("direcao_media_graus"),
            "direcao_media_cardinal": trilha.get("direcao_media_cardinal"),
            "dispersao_direcao_max_graus": dispersao,
            "tendencia_relativa_comasa": trilha.get("tendencia_relativa_comasa"),
            "ultima_distancia_comasa_km": trilha.get("ultima_distancia_comasa_km"),
            "velocidade_resumo_kmh": {
                "media": vel_media,
                "minima": vel_min,
                "maxima": vel_max,
                "amplitude": amplitude,
                "passos_total": len(velocidades),
                "passos_na_faixa_eta_5_120": len(velocidades_faixa_eta),
            },
            "criterios": criterios,
            "falhas": falhas,
            "eta_liberado": False,
        })

    coerentes = [x for x in itens if x["status"] == "coerente_para_estudo"]
    revisar = [x for x in itens if x["status"] == "requer_revisao"]

    contagem_falhas = {}
    for item in revisar:
        for falha in item["falhas"]:
            contagem_falhas[falha] = contagem_falhas.get(falha, 0) + 1

    return {
        "versao": "#135",
        "status": "auditoria_fisica_preliminar_ativa",
        "origem_trilhas": "somente_componentes_formados_por_rgb_oficial_#133",
        "quantidade_trilhas_elegiveis_recebidas": len(elegiveis),
        "quantidade_coerentes_para_estudo": len(coerentes),
        "quantidade_requer_revisao": len(revisar),
        "falhas_agregadas": contagem_falhas,
        "criterios_herdados": {
            "minimo_transicoes": 3,
            "score_minimo": 0.55,
            "dispersao_direcao_max_graus": 45,
            "velocidade_eta_min_kmh": 5,
            "velocidade_eta_max_kmh": 120,
            "velocidade_rastreio_max_kmh": 150,
        },
        "trilhas": itens,
        "dbz_numerico_validado": False,
        "equivale_chuva_medida": False,
        "eta_liberado": False,
        "regra_seguranca": (
            "A auditoria #134 testa apenas coerência interna das trilhas formadas por cores oficiais. "
            "Ela não prova precipitação no solo, não valida dBZ e não autoriza ETA automático."
        ),
    }

# =========================================================
# #135 - FUNIL OPERACIONAL EXPERIMENTAL DAS TRILHAS
# =========================================================

def funil_operacional_135(rastreamento, auditoria_134):
    """Filtra para estudo operacional apenas trilhas aprovadas na #134."""
    trilhas = (rastreamento or {}).get("trilhas", [])
    aprovadas = {
        item.get("id_trilha")
        for item in (auditoria_134 or {}).get("trilhas", [])
        if item.get("status") == "coerente_para_estudo"
    }
    operacionais = [t for t in trilhas if t.get("id_trilha") in aprovadas]
    rejeitadas = [
        t for t in trilhas
        if t.get("elegivel_para_analise") and t.get("id_trilha") not in aprovadas
    ]
    return {
        "versao": "#135",
        "status": "funil_operacional_experimental_ativo",
        "origem": "rgb_oficial_#133_mais_coerencia_fisica_#134",
        "quantidade_trilhas_operacionais_experimentais": len(operacionais),
        "quantidade_trilhas_rejeitadas_pelo_funil": len(rejeitadas),
        "ids_operacionais": [t.get("id_trilha") for t in operacionais],
        "ids_rejeitadas": [t.get("id_trilha") for t in rejeitadas],
        "trilhas_operacionais": operacionais,
        "trilhas_rejeitadas_diagnostico": rejeitadas,
        "dbz_numerico_validado": False,
        "equivale_chuva_medida": False,
        "eta_liberado": False,
        "regra_seguranca": (
            "A #135 aplica a auditoria física #134 como filtro experimental. "
            "Trilhas rejeitadas permanecem apenas para diagnóstico. "
            "Nenhuma trilha autoriza ETA, dBZ numérico ou chuva medida."
        ),
    }


def rastreamento_operacional_135(rastreamento, funil):
    """Visão filtrada; preserva separadamente o rastreamento diagnóstico completo."""
    base = dict(rastreamento or {})
    trilhas = list((funil or {}).get("trilhas_operacionais") or [])
    base["versao_funil"] = "#135"
    base["status_funil"] = "somente_trilhas_coerentes_134"
    base["trilhas"] = trilhas
    base["quantidade_trilhas"] = len(trilhas)
    base["quantidade_trilhas_elegiveis"] = len(trilhas)
    base["trilha_principal_diagnostica"] = (
        max(trilhas, key=lambda t: (t.get("transicoes") or 0, t.get("score_medio") or 0))
        if trilhas else None
    )
    base["eta_liberado"] = False
    return base


# #129 - ECO OFICIAL RADARSC AO REDOR DO COMASA
# =========================================================

def diagnostico_eco_oficial_local(imagem, legenda_oficial):
    """Cruza o PNG com as cores RGB da legenda oficial em 2, 5, 10 e 25 km."""
    classes = (legenda_oficial or {}).get("classes", [])
    cores = {}
    for item in classes:
        rgb = item.get("rgb") if isinstance(item, dict) else None
        if isinstance(rgb, list) and len(rgb) == 3:
            cores[tuple(rgb)] = item.get("classe")
    base = {
        "status": "sem_classes_oficiais",
        "metodo": "pixels_rgb_exatos_legenda_oficial_#129",
        "referencia": "Comasa - coordenada pública aproximada",
        "raios_km": [2, 5, 10, 25],
        "classes_legenda_total": len(cores),
        "dbz_numerico_validado": False,
        "equivale_chuva_medida": False,
        "eta_liberado": False,
    }
    if not cores:
        return base
    rgba = imagem.convert("RGBA")
    px = rgba.load()
    contagens = {2: Counter(), 5: Counter(), 10: Counter(), 25: Counter()}
    total = {2: 0, 5: 0, 10: 0, 25: 0}
    mais_proximo = None
    lat_delta = 25 / 111.32
    lon_delta = 25 / (111.32 * max(0.2, math.cos(math.radians(LAT))))
    x1, y2 = geo2px(LON - lon_delta, LAT - lat_delta, rgba.width, rgba.height)
    x2, y1 = geo2px(LON + lon_delta, LAT + lat_delta, rgba.width, rgba.height)
    xa, xb = sorted((x1, x2))
    ya, yb = sorted((y1, y2))
    for y in range(ya, yb + 1):
        for x in range(xa, xb + 1):
            r, g, b, a = px[x, y]
            if a <= 0:
                continue
            cor = (r, g, b)
            classe = cores.get(cor)
            if classe is None:
                continue
            lat, lon = px2geo(x, y, rgba.width, rgba.height)
            d = hav(LAT, LON, lat, lon)
            if d <= 25:
                if mais_proximo is None or d < mais_proximo[0]:
                    mais_proximo = (d, classe, cor, lat, lon)
                for raio in (2, 5, 10, 25):
                    if d <= raio:
                        total[raio] += 1
                        contagens[raio][classe] += 1
    por_raio = {}
    for raio in (2, 5, 10, 25):
        por_raio[str(raio)] = {
            "pixels_classes_oficiais": total[raio],
            "eco_oficial_detectado": total[raio] > 0,
            "classes_presentes": [
                {"classe": int(classe), "pixels": qtd}
                for classe, qtd in sorted(contagens[raio].items())
            ],
        }
    resultado = {**base, "status": "diagnostico_ativo", "por_raio": por_raio}
    if mais_proximo:
        d, classe, cor, lat, lon = mais_proximo
        resultado["eco_oficial_mais_proximo"] = {
            "distancia_comasa_km": round(d, 2),
            "classe": int(classe),
            "rgb": list(cor),
            "latitude": round(lat, 5),
            "longitude": round(lon, 5),
        }
    else:
        resultado["eco_oficial_mais_proximo"] = None
    resultado["regra_seguranca"] = (
        "Detecção significa pixel com RGB idêntico a uma classe da legenda oficial RadarSC. "
        "Não significa chuva medida no solo e não atribui dBZ enquanto a escala numérica não for validada."
    )
    return resultado



# =========================================================
# #130 - DICIONÁRIO QUALITATIVO DE CORES DO RADAR
# =========================================================

def familia_cor_radar(rgb):
    """Classifica apenas a família visual da cor oficial.

    A interpretação meteorológica é deliberadamente qualitativa:
    SIMEPAR documenta verde/amarelo como chuva de menor intensidade e
    vermelho/rosa como chuva mais intensa/tempestades. A Defesa Civil SC
    publica CMAX (dBZ) com vermelho/rosa em instabilidades intensas.
    Nenhum valor numérico de dBZ ou mm/h é inferido aqui.
    """
    if not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        return "outra"
    r, g, b = [int(v) for v in rgb[:3]]
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 28:
        return "neutra"
    # rosa/magenta/roxo: vermelho e azul dominantes
    if r >= 150 and b >= 120 and g <= min(r, b) * 0.82:
        return "rosa_magenta_roxo"
    # vermelho: canal R claramente dominante
    if r >= 160 and r >= g * 1.35 and r >= b * 1.25:
        return "vermelho"
    # laranja: R dominante com G intermediário
    if r >= 180 and 55 <= g < 210 and b <= 120:
        return "laranja"
    # amarelo: R e G altos, B baixo
    if r >= 170 and g >= 150 and b <= 130:
        return "amarelo"
    # verde: G dominante
    if g >= 110 and g >= r * 1.15 and g >= b * 1.10:
        return "verde"
    # ciano/azul: B ou combinação G+B dominantes
    if b >= 120 and (b >= r * 1.20 or g >= r * 1.25):
        return "azul_ciano"
    return "outra"


def significado_qualitativo_familia(familia):
    if familia in ("verde", "amarelo"):
        return {
            "categoria": "precipitacao_menor_intensidade_documentada",
            "nivel_evidencia": "documental_qualitativo",
        }
    if familia == "laranja":
        return {
            "categoria": "precipitacao_temporal_documentado_sem_faixa_numerica",
            "nivel_evidencia": "documental_qualitativo",
        }
    if familia in ("vermelho", "rosa_magenta_roxo"):
        return {
            "categoria": "precipitacao_intensa_ou_tempestade_documentada",
            "nivel_evidencia": "documental_qualitativo",
        }
    return {
        "categoria": "sem_interpretacao_meteorologica_validada",
        "nivel_evidencia": "nao_classificado",
    }


def construir_dicionario_cores_130(legenda_oficial):
    classes = (legenda_oficial or {}).get("classes") or []
    saida = []
    for item in classes:
        rgb = item.get("rgb")
        familia = familia_cor_radar(rgb)
        significado = significado_qualitativo_familia(familia)
        saida.append({
            "classe": item.get("classe"),
            "rgb": rgb,
            "familia_cor": familia,
            **significado,
            "dbz": None,
            "mm_h": None,
        })
    return {
        "versao": "#130",
        "status": "dicionario_qualitativo_ativo" if saida else "sem_classes",
        "fonte_cores": "legenda oficial RadarSC baixada em cada execução",
        "produto_monitor": "COMP / C-MAX",
        "classes": saida,
        "fontes_documentais": [
            {
                "fonte": "SIMEPAR - Informações dos mapas de Radar",
                "regra": "vermelho/rosa: chuvas mais intensas/tempestades; amarelo/verde: chuvas de menor intensidade",
            },
            {
                "fonte": "Defesa Civil SC - publicações CMAX (dBZ)",
                "regra": "vermelho/rosa aparecem documentados em instabilidades/temporais intensos",
            },
        ],
        "regra_seguranca": (
            "A #130 ensina famílias qualitativas usando somente RGBs da legenda oficial RadarSC. "
            "Não converte cor em dBZ, mm/h ou chuva medida no solo. ETA permanece bloqueado."
        ),
        "dbz_numerico_validado": False,
        "eta_liberado": False,
    }


def diagnostico_qualitativo_local_130(imagem, legenda_oficial):
    dicionario = construir_dicionario_cores_130(legenda_oficial)
    mapa = {tuple(x["rgb"]): x for x in dicionario.get("classes", []) if x.get("rgb")}
    base = {
        "versao": "#130",
        "referencia": "Comasa - coordenada pública aproximada",
        "raios_km": [2, 5, 10, 25],
        "dbz_numerico_validado": False,
        "equivale_chuva_medida": False,
        "eta_liberado": False,
    }
    if not mapa:
        return {**base, "status": "sem_dicionario_oficial", "por_raio": {}}
    rgba = imagem.convert("RGBA")
    largura, altura = rgba.size
    x0, y0 = geo2px(LON, LAT, largura, altura)
    # Converte raios km em uma caixa de busca segura; hav() decide inclusão real.
    km_por_px_lat = abs((EXT[3] - EXT[1]) * 111.32 / max(1, altura - 1))
    km_por_px_lon = abs((EXT[2] - EXT[0]) * 111.32 * math.cos(math.radians(LAT)) / max(1, largura - 1))
    passo = max(0.01, min(km_por_px_lat, km_por_px_lon))
    alcance_px = int(math.ceil(25 / passo)) + 2
    contagens = {r: Counter() for r in (2, 5, 10, 25)}
    familias = {r: Counter() for r in (2, 5, 10, 25)}
    for y in range(max(0, y0-alcance_px), min(altura, y0+alcance_px+1)):
        for x in range(max(0, x0-alcance_px), min(largura, x0+alcance_px+1)):
            px = rgba.getpixel((x, y))
            if px[3] == 0:
                continue
            info = mapa.get(tuple(px[:3]))
            if not info:
                continue
            lat, lon = px2geo(x, y, largura, altura)
            dist = hav(LAT, LON, lat, lon)
            for raio in (2, 5, 10, 25):
                if dist <= raio:
                    contagens[raio][int(info["classe"])] += 1
                    familias[raio][info["familia_cor"]] += 1
    por_raio = {}
    for raio in (2, 5, 10, 25):
        total = sum(contagens[raio].values())
        por_raio[str(raio)] = {
            "pixels_oficiais_classificados": total,
            "eco_oficial_detectado": total > 0,
            "classes_presentes": [
                {"classe": c, "pixels": n} for c, n in sorted(contagens[raio].items())
            ],
            "familias_cor": [
                {"familia": f, "pixels": n, **significado_qualitativo_familia(f)}
                for f, n in familias[raio].most_common()
            ],
        }
    return {
        **base,
        "status": "diagnostico_qualitativo_ativo",
        "por_raio": por_raio,
        "regra_seguranca": (
            "Presença de cor oficial é detecção por radar, não medição de chuva no solo. "
            "As categorias de intensidade são qualitativas e documentais; dBZ e mm/h continuam não atribuídos."
        ),
    }

# =========================================================
# #132 - AUDITORIA ESPACIAL: LEGADO x RGB OFICIAL
# =========================================================

def auditoria_espacial_132(imagem, legenda_oficial):
    """Explica a divergência entre a máscara legada e as cores oficiais.

    A máscara histórica considera candidato todo pixel visível diferente de
    CINZA (200,200,200). A auditoria #132 não usa isso como chuva: ela mostra
    qual RGB/índice gerou o candidato mais próximo e se esse RGB pertence ou
    não à legenda oficial RadarSC. Também testa a transformação geo<->pixel.
    """
    classes = (legenda_oficial or {}).get("classes") or []
    mapa_oficial = {}
    for item in classes:
        if not isinstance(item, dict):
            continue
        rgb = item.get("rgb")
        if isinstance(rgb, list) and len(rgb) == 3:
            mapa_oficial[tuple(int(v) for v in rgb)] = item.get("classe")

    base = {
        "versao": "#133",
        "status": "auditoria_espacial_ativa",
        "referencia": "Comasa - coordenada pública aproximada",
        "coordenada_referencia": {"latitude": LAT, "longitude": LON},
        "metodo_legado": "todo_pixel_visivel_exceto_cinza_200_200_200",
        "metodo_oficial": "somente_rgb_exato_da_legenda_oficial_radarsc",
        "dbz_numerico_validado": False,
        "equivale_chuva_medida": False,
        "eta_liberado": False,
    }

    if imagem.mode != "P":
        return {**base, "status": "modo_png_inesperado", "modo": imagem.mode}

    largura, altura = imagem.size
    x0, y0 = geo2px(LON, LAT, largura, altura)
    lat_rt, lon_rt = px2geo(x0, y0, largura, altura)
    erro_rt = hav(LAT, LON, lat_rt, lon_rt)

    paleta = imagem.getpalette()
    transparencia = imagem.info.get("transparency")
    pixels = imagem.load()
    indice_ponto = int(pixels[x0, y0])
    rgb_ponto = rgb_idx(paleta, indice_ponto)
    alpha_ponto = alpha_idx(transparencia, indice_ponto)
    classe_ponto = mapa_oficial.get(tuple(rgb_ponto)) if rgb_ponto else None

    pontos_legado, indices_legado = mascara(imagem)
    legado_mais_proximo = None
    for x, y in pontos_legado:
        lat, lon = px2geo(x, y, largura, altura)
        d = hav(LAT, LON, lat, lon)
        if legado_mais_proximo is None or d < legado_mais_proximo[0]:
            indice = int(pixels[x, y])
            rgb = indices_legado.get(indice) or rgb_idx(paleta, indice)
            alpha = alpha_idx(transparencia, indice)
            classe = mapa_oficial.get(tuple(rgb)) if rgb else None
            legado_mais_proximo = (d, x, y, indice, rgb, alpha, classe, lat, lon)

    oficial_mais_proximo = None
    # Varre o quadro inteiro apenas por RGBs oficiais. Isso é diagnóstico,
    # não medição de chuva e não atribui intensidade numérica.
    if mapa_oficial:
        for y in range(altura):
            for x in range(largura):
                indice = int(pixels[x, y])
                if alpha_idx(transparencia, indice) <= 0:
                    continue
                rgb = rgb_idx(paleta, indice)
                if not rgb:
                    continue
                classe = mapa_oficial.get(tuple(rgb))
                if classe is None:
                    continue
                lat, lon = px2geo(x, y, largura, altura)
                d = hav(LAT, LON, lat, lon)
                if oficial_mais_proximo is None or d < oficial_mais_proximo[0]:
                    oficial_mais_proximo = (d, x, y, indice, rgb, classe, lat, lon)

    def pacote_legado(item):
        if not item:
            return None
        d, x, y, indice, rgb, alpha, classe, lat, lon = item
        return {
            "distancia_comasa_km": round(d, 3),
            "pixel_x": x,
            "pixel_y": y,
            "indice_p": indice,
            "rgb": list(rgb) if rgb else None,
            "alpha": alpha,
            "rgb_pertence_legenda_oficial": classe is not None,
            "classe_oficial": int(classe) if classe is not None else None,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "diagnostico": (
                "candidato_legado_tambem_e_cor_oficial"
                if classe is not None
                else "falso_candidato_pelo_criterio_legado_para_fins_meteorologicos"
            ),
        }

    def pacote_oficial(item):
        if not item:
            return None
        d, x, y, indice, rgb, classe, lat, lon = item
        return {
            "distancia_comasa_km": round(d, 3),
            "pixel_x": x,
            "pixel_y": y,
            "indice_p": indice,
            "rgb": list(rgb),
            "classe_oficial": int(classe),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
        }

    legado = pacote_legado(legado_mais_proximo)
    oficial = pacote_oficial(oficial_mais_proximo)
    divergencia = None
    if legado and oficial:
        divergencia = round(
            oficial["distancia_comasa_km"] - legado["distancia_comasa_km"], 3
        )

    # Conta, em raios locais, quantos candidatos legados são de fato cores
    # oficiais. Assim a #132 mede a contaminação do critério antigo.
    raios = (2, 5, 10, 25)
    cont = {r: {"legado": 0, "oficial": 0, "legado_nao_oficial": 0} for r in raios}
    for x, y in pontos_legado:
        lat, lon = px2geo(x, y, largura, altura)
        d = hav(LAT, LON, lat, lon)
        if d > 25:
            continue
        indice = int(pixels[x, y])
        rgb = indices_legado.get(indice) or rgb_idx(paleta, indice)
        eh_oficial = bool(rgb and tuple(rgb) in mapa_oficial)
        for r in raios:
            if d <= r:
                cont[r]["legado"] += 1
                if eh_oficial:
                    cont[r]["oficial"] += 1
                else:
                    cont[r]["legado_nao_oficial"] += 1

    return {
        **base,
        "transformacao_geografica": {
            "pixel_comasa": {"x": x0, "y": y0},
            "coordenada_recalculada_do_pixel": {
                "latitude": round(lat_rt, 6),
                "longitude": round(lon_rt, 6),
            },
            "erro_roundtrip_km": round(erro_rt, 4),
            "observacao": "Erro pequeno confirma consistencia matematica interna; nao prova sozinho que EXT representa perfeitamente o PNG do RadarSC.",
        },
        "pixel_exato_comasa": {
            "indice_p": indice_ponto,
            "rgb": list(rgb_ponto) if rgb_ponto else None,
            "alpha": alpha_ponto,
            "visivel": alpha_ponto > 0,
            "rgb_pertence_legenda_oficial": classe_ponto is not None,
            "classe_oficial": int(classe_ponto) if classe_ponto is not None else None,
        },
        "candidato_legado_mais_proximo": legado,
        "eco_oficial_mais_proximo_no_quadro": oficial,
        "diferenca_distancias_oficial_menos_legado_km": divergencia,
        "contagem_local_por_raio": {str(r): cont[r] for r in raios},
        "conclusao_automatica": (
            "criterio_legado_inclui_cor_nao_oficial"
            if legado and not legado["rgb_pertence_legenda_oficial"]
            else "sem_falso_candidato_demonstrado_no_mais_proximo"
        ),
        "regra_seguranca": (
            "A #132 e auditoria diagnostica. Candidatos do metodo legado nao devem ser tratados como chuva quando o RGB nao pertence a legenda oficial. "
            "dBZ numerico e ETA permanecem bloqueados."
        ),
    }


# =========================================================
# DOWNLOAD DO RADAR
# =========================================================
 
def baixar(nome, legenda_oficial=None):
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
                imagem,
                legenda_oficial,
            ),

        "eco_oficial_local_129":
            diagnostico_eco_oficial_local(
                imagem,
                legenda_oficial,
            ),

        "classificacao_qualitativa_local_130":
            diagnostico_qualitativo_local_130(
                imagem,
                legenda_oficial,
            ),

        "auditoria_espacial_132":
            auditoria_espacial_132(
                imagem,
                legenda_oficial,
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
                "Radar não retornou lista de imagens."
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
 
                    **baixar(nome, leg),
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
 
        validacao_paleta = validar_paleta_radar(
            leg,
            validos,
        )
 
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

        auditoria_fisica_134 = auditoria_fisica_trilhas_134(
            rastreamento
        )

        funil_135 = funil_operacional_135(
            rastreamento,
            auditoria_fisica_134,
        )

        rastreamento_operacional = rastreamento_operacional_135(
            rastreamento,
            funil_135,
        )
 
        avaliacao = avaliar_todas_trilhas(
            rastreamento_operacional,
            fresco,
            idade,
            horario_ultimo,
        )
 
        selecionado = avaliacao.get(
            "candidato_selecionado"
        )
 
        principal = (
            rastreamento_operacional.get(
                "trilha_principal_diagnostica"
            )
        )
 
        movimento = {
            "status":
                "sem_trilha_elegivel",
 
            "metodo":
                "identidade_temporal_#118",
 
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
                    "identidade_temporal_multivetorial_#118",
 
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
 
                "similaridade_cores_media":
                    principal.get(
                        "similaridade_cores_media"
                    ),
 
                "dispersao_direcao_max_graus":
                    principal.get(
                        "dispersao_direcao_max_graus"
                    ),
 
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
 
                "candidato_eta":
                    bool(
                        selecionado
                    ),
            }
 
        if selecionado:
            inter = selecionado[
                "resultado"
            ]
 
        elif principal:
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
                    "Nenhuma trilha elegível disponível.",
 
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
            e = inter[
                "eta"
            ]
 
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
                    for q in validos
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
 
            "validacao_paleta_radar":
                validacao_paleta,

            "eco_oficial_local_129":
                ultimo.get("eco_oficial_local_129"),

            "dicionario_cores_130":
                construir_dicionario_cores_130(leg),

            "classificacao_qualitativa_local_130":
                ultimo.get("classificacao_qualitativa_local_130"),

            "auditoria_espacial_132":
                ultimo.get("auditoria_espacial_132"),

            "correcao_rastreamento_133": {
                "versao": "#133",
                "status": "ativa",
                "mascara_operacional": "somente_rgb_exato_da_legenda_oficial_radarsc",
                "pixels_visiveis_nao_oficiais": "excluidos_de_componentes_trilhas_e_autovalidacao",
                "criterio_legado": "mantido_apenas_na_auditoria_132_para_comparacao",
                "dbz_numerico_validado": False,
                "eta_liberado": False,
                "regra_seguranca": "Cor oficial detectada por radar não equivale a chuva medida no solo. A #133 corrige a seleção espacial; não atribui dBZ, mm/h nem libera ETA.",
            },
 
            "metodo_eco": {
                "status":
                    "experimental_funil_fisico_135",
 
                "fundo":
                    "alpha_zero_excluido",
 
                "cinza_200_200_200":
                    "excluido_ate_validacao",
 
                "demais_pixels_visiveis":
                    "excluidos_do_rastreamento_#133",
 
                "dbz":
                    "nao_atribuido",

                "classificacao_qualitativa":
                    "somente_rgb_exato_da_legenda_oficial",

                "rastreamento_temporal":
                    "somente_componentes_formados_por_rgb_oficial_#133",

                "autovalidacao":
                    "somente_trilhas_rgb_oficial_que_passaram_auditoria_fisica_#135",
 
                "validacao_rgb":
                    validacao_paleta.get("status"),
            },
 
            "serie_espacial":
                serie,
 
            "rastreamento_temporal":
                rastreamento,

            "auditoria_fisica_trilhas_134":
                auditoria_fisica_134,

            "funil_operacional_135":
                funil_135,

            "rastreamento_operacional_135":
                rastreamento_operacional,
 
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
                "aguardando_validacao_numerica",
 
            "eta":
                eta,
 
            "seguranca_eta": {
                "status":
                    "experimental",
 
                "versao":
                    "#118",
 
                "publicacao_automatica":
                    False,
 
                "validado_para_eta":
                    False,
 
                "regra":
                    (
                        "Nenhum ETA do #118 deve "
                        "ser tratado como previsão "
                        "operacional antes de "
                        "validação observacional."
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
 

# =========================================================
# #136 - CHUVA OBSERVADA / CEMADEN - ACUMULADO 24 H
# =========================================================

def numero_cemaden(valor):
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if not texto or texto.lower() in ("null", "none", "nan"):
        return None
    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numero) or numero < 0:
        return None
    return numero


def inteiro_cemaden(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def parse_jsonp_cemaden(texto):
    if not isinstance(texto, str):
        raise ValueError("Resposta CEMADEN não textual.")
    bruto = texto.lstrip("\ufeff").strip()
    if not bruto:
        raise ValueError("Resposta CEMADEN vazia.")
    if bruto[0] in "[{":
        return json.loads(bruto.rstrip(";").strip())
    combinado = re.match(
        r"^\s*([A-Za-z_$][\w$]*)\s*\((.*)\)\s*;?\s*$",
        bruto,
        flags=re.S,
    )
    if not combinado:
        raise ValueError("Formato JSONP CEMADEN não reconhecido.")
    callback = combinado.group(1)
    if callback != "estacoes":
        raise ValueError("Callback JSONP inesperado: " + callback)
    return json.loads(combinado.group(2))


def extrair_estacoes_cemaden(payload):
    blocos = payload if isinstance(payload, list) else [payload]
    estacoes = []
    for bloco in blocos:
        if not isinstance(bloco, dict):
            continue
        lista = bloco.get("estacao")
        if isinstance(lista, list):
            estacoes.extend(
                item for item in lista
                if isinstance(item, dict)
            )
    return estacoes


def buscar_chuva_cemaden_136():
    base = {
        "status": "indisponivel",
        "versao_integracao": "#136",
        "tipo": "observacao_pluviometrica_acumulada",
        "fonte": "CEMADEN",
        "fonte_primaria": (
            "Centro Nacional de Monitoramento e Alertas "
            "de Desastres Naturais"
        ),
        "endpoint_publico": CEMADEN_PLUV_24H,
        "produto_mapa": "311_24",
        "janela_acumulado_h": 24,
        "referencia": "Comasa - coordenada publica aproximada",
        "coordenada_referencia": {
            "latitude": LAT,
            "longitude": LON,
        },
        "estacao_selecionada": None,
        "acumulado_24h_mm": None,
        "quantidade_estacoes_joinville_ativas": 0,
        "estacoes_joinville_ativas": [],
        "horario_medicao": None,
        "idade_leitura_min": None,
        "dados_frescos": None,
        "equivale_medicao_no_comasa": False,
        "classificacao_risco_automatica": False,
        "regra_seguranca": (
            "Dado bruto de estação CEMADEN. O acumulado pertence à estação "
            "selecionada e não equivale a medição no Comasa. Falha, ausência "
            "ou valor nulo nunca é convertido em 0 mm."
        ),
    }
    try:
        resposta = get(CEMADEN_PLUV_24H)
        payload = parse_jsonp_cemaden(resposta.text)
        estacoes = extrair_estacoes_cemaden(payload)
        if not estacoes:
            raise ValueError("Feed CEMADEN sem estações reconhecíveis.")

        candidatas = []
        for estacao in estacoes:
            cidade = str(estacao.get("cidade") or "").strip()
            uf = str(estacao.get("uf") or "").strip().upper()
            tipo = inteiro_cemaden(estacao.get("idtipoestacao"))
            status = inteiro_cemaden(estacao.get("status"))
            if cidade.casefold() != "joinville":
                continue
            if uf != "SC" or tipo != 1 or status != 0:
                continue

            try:
                lat = float(str(estacao.get("latitude")).replace(",", "."))
                lon = float(str(estacao.get("longitude")).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if not (
                math.isfinite(lat)
                and math.isfinite(lon)
                and -90 <= lat <= 90
                and -180 <= lon <= 180
            ):
                continue

            acumulado = numero_cemaden(estacao.get("acumulado"))
            candidatas.append({
                "id": estacao.get("idestacao"),
                "codigo": estacao.get("codestacao"),
                "nome": estacao.get("nomeestacao"),
                "rede": estacao.get("sigla"),
                "cidade": cidade,
                "uf": uf,
                "latitude": lat,
                "longitude": lon,
                "distancia_comasa_aprox_km": round(hav(LAT, LON, lat, lon), 2),
                "acumulado_24h_mm": acumulado,
                "acumulado_disponivel": acumulado is not None,
            })

        candidatas.sort(
            key=lambda item: item["distancia_comasa_aprox_km"]
        )
        base["quantidade_estacoes_joinville_ativas"] = len(candidatas)
        base["estacoes_joinville_ativas"] = candidatas

        if not candidatas:
            base["status"] = "online_sem_estacao_joinville_ativa"
            base["observacao"] = (
                "O endpoint respondeu, mas nenhuma estação automática ativa "
                "de Joinville/SC passou pelos filtros da integração #136."
            )
            return base

        com_leitura = [
            item for item in candidatas
            if item["acumulado_disponivel"]
        ]
        selecionada = com_leitura[0] if com_leitura else candidatas[0]
        base["estacao_selecionada"] = selecionada
        base["acumulado_24h_mm"] = selecionada["acumulado_24h_mm"]
        base["coletado_em"] = agora().isoformat()

        if selecionada["acumulado_disponivel"]:
            base["status"] = "online_dado_bruto_24h"
        else:
            base["status"] = "online_sem_acumulado_valido"
            base["observacao"] = (
                "Estação identificada, porém o feed não trouxe acumulado "
                "24 h válido. O Monitor mantém o valor indisponível."
            )
        return base

    except Exception as e:
        base["erro"] = str(e)
        base["observacao"] = (
            "Falha na coleta do feed público 311_24 do CEMADEN; "
            "não interpretar como ausência de chuva."
        )
        return base


# =========================================================
# #138 - SONDA DIAGNOSTICA DA SERIE TEMPORAL CEMADEN
# =========================================================

def investigar_serie_cemaden_138(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#138",
        "tipo": "sonda_diagnostica_serie_temporal_cemaden",
        "fonte": "CEMADEN",
        "estacao": None,
        "pagina_grafico": None,
        "recursos_encontrados": [],
        "evidencias_endpoint": [],
        "serie_temporal_integrada": False,
        "publicacao_automatica": False,
        "regra_seguranca": (
            "A #138 apenas investiga a estrutura publica usada pelo grafico "
            "CEMADEN. Nenhum valor encontrado e publicado como chuva recente "
            "sem validacao explicita da estrutura, unidade e janela temporal."
        ),
    }
    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        uf = str(selecionada.get("uf") or "SC").strip().upper()
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            resultado["observacao"] = "A coleta #136 nao selecionou estacao; a sonda #138 nao foi executada."
            return resultado

        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": uf,
        }
        url = CEMADEN_RECURSOS + "/graficos/interativo/grafico_CEMADEN.php?idpcd=" + str(idestacao) + "&uf=" + uf
        resultado["pagina_grafico"] = url
        resposta = get(url)
        html = resposta.text
        resultado["http_status"] = resposta.status_code
        resultado["bytes_html"] = len(resposta.content)

        recursos = re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', html, flags=re.I)
        urls = []
        for item in recursos:
            absoluta = urljoin(url, item)
            if absoluta not in urls:
                urls.append(absoluta)
        resultado["recursos_encontrados"] = urls[:80]

        textos = [(url, html)]
        for recurso in urls:
            baixo = recurso.lower().split("?", 1)[0]
            if not baixo.endswith(".js"):
                continue
            try:
                rjs = get(recurso)
                textos.append((recurso, rjs.text))
            except Exception as e:
                resultado.setdefault("erros_recursos", []).append({"url": recurso, "erro": str(e)[:220]})

        padroes = [
            r'''(?:url\s*:\s*|fetch\s*\(|getJSON\s*\()["']([^"']+)["']''',
            r'''["']([^"']*(?:pluv|chuva|cemaden|graf|serie|dados)[^"']*(?:\.php|\.json|\.csv)[^"']*)["']''',
        ]
        evidencias = []
        vistos = set()
        for origem, texto in textos:
            for padrao in padroes:
                for achado in re.findall(padrao, texto, flags=re.I):
                    achado = str(achado).strip()
                    if not achado or achado.startswith("javascript:"):
                        continue
                    chave = (origem, achado)
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    evidencias.append({
                        "origem": origem,
                        "referencia_bruta": achado[:700],
                        "url_resolvida": urljoin(origem, achado)[:1200],
                    })
        resultado["evidencias_endpoint"] = evidencias[:120]
        resultado["status"] = "evidencias_encontradas_para_revisao" if evidencias else "pagina_acessivel_sem_endpoint_identificado"
        resultado["observacao"] = "Resultado bruto para auditoria. A #138 nao interpreta nem publica serie temporal automaticamente."
        return resultado
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = "Falha da sonda #138 nao altera nem invalida o acumulado 24 h da #136."
        return resultado



# =========================================================
# #139 - SONDA DO ENDPOINT grafico_pcds.php / CEMADEN
# =========================================================

def investigar_endpoint_pcds_139(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#139",
        "tipo": "sonda_diagnostica_endpoint_grafico_pcds",
        "fonte": "CEMADEN",
        "estacao": None,
        "endpoint": None,
        "http_status": None,
        "content_type": None,
        "bytes_resposta": None,
        "amostra_textual": None,
        "referencias_encontradas": [],
        "padroes_temporais": [],
        "estruturas_tabela": [],
        "serie_temporal_integrada": False,
        "publicacao_automatica": False,
        "regra_seguranca": (
            "A #139 apenas audita a resposta do endpoint grafico_pcds.php. "
            "Nenhum numero e publicado como chuva, horario, acumulado ou "
            "intensidade sem validacao explicita da estrutura e unidade."
        ),
    }
    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado
        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": selecionada.get("uf"),
        }
        endpoint = CEMADEN_RECURSOS + "/graficos/interativo/grafico_pcds.php?idpcd=" + str(idestacao)
        resultado["endpoint"] = endpoint
        resposta = get(endpoint)
        resultado["http_status"] = resposta.status_code
        resultado["content_type"] = resposta.headers.get("Content-Type")
        resultado["bytes_resposta"] = len(resposta.content)
        texto = resposta.text or ""
        resultado["amostra_textual"] = re.sub(r"\s+", " ", texto).strip()[:3000]

        referencias = []
        vistos = set()
        for padrao in [
            r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']",
            r"(?:url\s*:\s*|fetch\s*\(|getJSON\s*\()[\"']([^\"']+)[\"']",
            r"[\"']([^\"']*(?:pluv|chuva|pcd|serie|dados|graf)[^\"']*(?:\.php|\.json|\.csv)[^\"']*)[\"']",
        ]:
            for achado in re.findall(padrao, texto, flags=re.I):
                bruto = str(achado).strip()
                if not bruto or bruto.startswith("javascript:"):
                    continue
                resolvida = urljoin(endpoint, bruto)
                chave = (bruto, resolvida)
                if chave not in vistos:
                    vistos.add(chave)
                    referencias.append({"referencia_bruta": bruto[:700], "url_resolvida": resolvida[:1200]})
        resultado["referencias_encontradas"] = referencias[:120]

        temporais = []
        vistos_temporais = set()
        for padrao in [
            r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?\b",
            r"\b\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?\b",
            r"\b\d{2}:\d{2}(?::\d{2})?\b",
        ]:
            for achado in re.findall(padrao, texto):
                if achado not in vistos_temporais:
                    vistos_temporais.add(achado)
                    temporais.append(achado)
        resultado["padroes_temporais"] = temporais[:120]

        tabelas = []
        for indice, bloco in enumerate(re.findall(r"<table\b[^>]*>(.*?)</table>", texto, flags=re.I | re.S)):
            linhas = []
            for linha in re.findall(r"<tr\b[^>]*>(.*?)</tr>", bloco, flags=re.I | re.S):
                celulas = []
                for celula in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", linha, flags=re.I | re.S):
                    limpo = re.sub(r"<[^>]+>", " ", celula)
                    limpo = re.sub(r"\s+", " ", limpo).strip()
                    celulas.append(limpo[:300])
                if celulas:
                    linhas.append(celulas)
            if linhas:
                tabelas.append({"indice": indice, "quantidade_linhas": len(linhas), "amostra_linhas": linhas[:20]})
        resultado["estruturas_tabela"] = tabelas[:20]
        resultado["sinais_estruturais"] = {
            "tem_tabela_html": bool(tabelas),
            "tem_timestamp": bool(temporais),
            "tem_referencias": bool(referencias),
            "menciona_mm": bool(re.search(r"\bmm\b|mil[ií]metro", texto, flags=re.I)),
            "menciona_chuva": bool(re.search(r"chuva|precipita", texto, flags=re.I)),
            "menciona_acumulado": bool(re.search(r"acumul", texto, flags=re.I)),
        }
        resultado["status"] = (
            "resposta_com_estrutura_para_revisao"
            if resposta.status_code == 200 and (tabelas or temporais or referencias)
            else "resposta_acessivel_sem_estrutura_identificada"
            if resposta.status_code == 200
            else "indisponivel"
        )
        resultado["observacao"] = (
            "Resultado bruto para auditoria. A #139 nao converte a resposta "
            "em chuva recente; primeiro precisamos confirmar campos, unidade, "
            "timezone e significado temporal."
        )
        return resultado
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = "Falha da sonda #139 nao altera a integracao CEMADEN #136 nem a sonda #138."
        return resultado



# =========================================================
# #140 - DESCOBERTA DA CHAMADA MAPAINTERATIVOWS / CEMADEN
# =========================================================

def investigar_mapservices_cemaden_140(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#140",
        "tipo": "descoberta_chamada_mapainterativows",
        "fonte": "CEMADEN",
        "estacao": None,
        "pagina_origem": None,
        "base_mapservices": (
            "https://mapservices.cemaden.gov.br/"
            "MapaInterativoWS/resources/"
        ),
        "chamadas_identificadas": [],
        "contextos_mapservices": [],
        "requisicoes_teste": [],
        "serie_temporal_integrada": False,
        "publicacao_automatica": False,
        "regra_seguranca": (
            "A #140 investiga chamadas estruturadas do servico usado pelo "
            "grafico oficial CEMADEN. Respostas de teste nao sao publicadas "
            "como chuva sem validacao de campos, unidade e referencia temporal."
        ),
    }

    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado

        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": selecionada.get("uf"),
        }

        pagina = (
            CEMADEN_RECURSOS
            + "/graficos/interativo/grafico_pcds.php?idpcd="
            + str(idestacao)
        )
        resultado["pagina_origem"] = pagina
        resposta = get(pagina)
        texto = resposta.text or ""

        # Guarda contextos literais ao redor de qualquer referencia ao
        # MapainterativoWS/mapservices para auditoria humana.
        contextos = []
        baixo = texto.lower()
        termos = [
            "mapainterativows",
            "mapservices.cemaden.gov.br",
            "var path",
            "$.ajax",
            "$.get",
            "$http",
        ]
        for termo in termos:
            inicio = 0
            while len(contextos) < 120:
                pos = baixo.find(termo.lower(), inicio)
                if pos < 0:
                    break
                a = max(0, pos - 700)
                b = min(len(texto), pos + 1800)
                trecho = re.sub(r"\s+", " ", texto[a:b]).strip()
                item = {
                    "termo": termo,
                    "trecho": trecho[:2600],
                }
                if item not in contextos:
                    contextos.append(item)
                inicio = pos + len(termo)
        resultado["contextos_mapservices"] = contextos

        # Procura expressoes em que a variavel path e concatenada a uma rota.
        chamadas = []
        vistos = set()
        padroes = [
            r'path\s*\+\s*["\']([^"\']+)["\']',
            r'path\s*\+\s*([A-Za-z_$][\w$]*)',
            r'(?:url\s*:\s*|getJSON\s*\(|ajax\s*\()\s*path\s*\+\s*([^,;\)\n]+)',
            r'["\'](https://mapservices\.cemaden\.gov\.br/MapaInterativoWS/resources/[^"\']*)["\']',
        ]
        for padrao in padroes:
            for achado in re.findall(padrao, texto, flags=re.I):
                bruto = str(achado).strip()
                if not bruto:
                    continue
                chave = bruto
                if chave in vistos:
                    continue
                vistos.add(chave)
                chamadas.append({"expressao": bruto[:1200]})
        resultado["chamadas_identificadas"] = chamadas[:120]

        # Extrai rotas literais relativas que aparecem proximas a "path".
        rotas = []
        for contexto in contextos:
            trecho = contexto["trecho"]
            for rota in re.findall(
                r'["\']([A-Za-z0-9_./?=&%-]{3,240})["\']',
                trecho,
            ):
                rlow = rota.lower()
                if (
                    "resource" in rlow
                    or "pcd" in rlow
                    or "estacao" in rlow
                    or "pluv" in rlow
                    or "dado" in rlow
                    or "graf" in rlow
                ):
                    if rota not in rotas:
                        rotas.append(rota)
        resultado["rotas_literais_candidatas"] = rotas[:80]

        # Somente rotas literais seguras, sem templates/variaveis, sao
        # consultadas. A resposta e guardada apenas como diagnostico.
        base = resultado["base_mapservices"]
        testes = []
        for rota in rotas[:20]:
            if (
                "{{" in rota
                or "}}" in rota
                or "$" in rota
                or " " in rota
                or not rota
            ):
                continue
            url_teste = urljoin(base, rota)
            if not url_teste.startswith(base):
                continue
            try:
                rt = get(url_teste)
                corpo = rt.text or ""
                testes.append({
                    "url": url_teste,
                    "http_status": rt.status_code,
                    "content_type": rt.headers.get("Content-Type"),
                    "bytes": len(rt.content),
                    "amostra": re.sub(r"\s+", " ", corpo).strip()[:1600],
                })
            except Exception as e:
                testes.append({
                    "url": url_teste,
                    "status": "erro",
                    "erro": str(e)[:400],
                })
        resultado["requisicoes_teste"] = testes

        if chamadas or contextos:
            resultado["status"] = "chamadas_encontradas_para_revisao"
        else:
            resultado["status"] = "pagina_acessivel_sem_chamada_identificada"

        resultado["observacao"] = (
            "A #140 preserva expressoes e contextos do codigo oficial para "
            "descobrir a rota exata. Nenhuma resposta e promovida a dado "
            "operacional nesta etapa."
        )
        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha da #140 nao altera as integracoes CEMADEN anteriores."
        )
        return resultado



# =========================================================
# #141 - AUDITORIA DO JSON HORARIO / CEMADEN
# =========================================================

def auditar_json_horario_cemaden_141(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#141",
        "tipo": "auditoria_json_horario_mapainterativows",
        "fonte": "CEMADEN",
        "estacao_solicitada": None,
        "endpoint": None,
        "parametro_horas_pagina": None,
        "parametro_final_endpoint": None,
        "http_status": None,
        "content_type": None,
        "bytes_resposta": None,
        "chaves_raiz": [],
        "metadados_estacao": None,
        "datas": [],
        "horarios": [],
        "dimensoes_acumulados": None,
        "amostra_acumulados": [],
        "valores_numericos": {
            "quantidade": 0,
            "minimo": None,
            "maximo": None,
        },
        "serie_temporal_integrada": False,
        "publicacao_automatica": False,
        "regra_seguranca": (
            "A #141 consulta diretamente a rota horario descoberta no codigo "
            "oficial do grafico CEMADEN, mas nao publica chuva recente. "
            "Primeiro valida estrutura, unidade, janela e referencia temporal."
        ),
    }

    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado

        resultado["estacao_solicitada"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": selecionada.get("uf"),
        }

        # O JS oficial usa:
        # url = path + "horario/" + idEstacao + "/" + (horas - 1)
        # A pagina define select_hr default como 24 + fuso.
        # A #141 usa explicitamente 24 como janela de auditoria e envia 23.
        horas = 24
        parametro = horas - 1
        resultado["parametro_horas_pagina"] = horas
        resultado["parametro_final_endpoint"] = parametro

        base = (
            "https://mapservices.cemaden.gov.br/"
            "MapaInterativoWS/resources/"
        )
        endpoint = (
            base
            + "horario/"
            + str(idestacao)
            + "/"
            + str(parametro)
        )
        resultado["endpoint"] = endpoint

        resposta = get(endpoint)
        resultado["http_status"] = resposta.status_code
        resultado["content_type"] = resposta.headers.get("Content-Type")
        resultado["bytes_resposta"] = len(resposta.content)

        dados = resposta.json()
        if not isinstance(dados, dict):
            raise ValueError(
                "Endpoint horario respondeu JSON, mas a raiz nao e objeto."
            )

        resultado["chaves_raiz"] = sorted(str(k) for k in dados.keys())

        estacao = dados.get("estacao")
        if isinstance(estacao, dict):
            rede = estacao.get("idRede")
            resultado["metadados_estacao"] = {
                "id": estacao.get("idEstacao") or estacao.get("id"),
                "codigo": (
                    estacao.get("codEstacao")
                    or estacao.get("codigo")
                    or estacao.get("codestacao")
                ),
                "nome": estacao.get("nome"),
                "cidade": estacao.get("cidade"),
                "uf": estacao.get("uf") or estacao.get("estado"),
                "rede": rede if isinstance(rede, (str, int, float)) else (
                    {
                        "idRede": rede.get("idRede"),
                        "sigla": rede.get("sigla"),
                        "nome": rede.get("nome"),
                    }
                    if isinstance(rede, dict)
                    else None
                ),
            }

        datas = dados.get("datas")
        horarios = dados.get("horarios")
        acumulados = dados.get("acumulados")

        if isinstance(datas, list):
            resultado["datas"] = datas[:40]
        if isinstance(horarios, list):
            resultado["horarios"] = horarios[:80]

        if isinstance(acumulados, list):
            linhas = len(acumulados)
            comprimentos = [
                len(linha)
                for linha in acumulados
                if isinstance(linha, list)
            ]
            resultado["dimensoes_acumulados"] = {
                "linhas": linhas,
                "colunas_por_linha": comprimentos[:40],
            }
            resultado["amostra_acumulados"] = [
                linha[:40] if isinstance(linha, list) else linha
                for linha in acumulados[:8]
            ]

            numeros = []
            for linha in acumulados:
                itens = linha if isinstance(linha, list) else [linha]
                for valor in itens:
                    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                        numeros.append(float(valor))
                    elif isinstance(valor, str):
                        try:
                            numeros.append(float(valor.replace(",", ".")))
                        except Exception:
                            pass

            resultado["valores_numericos"] = {
                "quantidade": len(numeros),
                "minimo": min(numeros) if numeros else None,
                "maximo": max(numeros) if numeros else None,
            }

        campos_extras = {}
        for chave, valor in dados.items():
            if chave in ("estacao", "datas", "horarios", "acumulados"):
                continue
            if isinstance(valor, (str, int, float, bool)) or valor is None:
                campos_extras[str(chave)] = valor
            elif isinstance(valor, list):
                campos_extras[str(chave)] = {
                    "tipo": "lista",
                    "quantidade": len(valor),
                    "amostra": valor[:5],
                }
            elif isinstance(valor, dict):
                campos_extras[str(chave)] = {
                    "tipo": "objeto",
                    "chaves": sorted(str(k) for k in valor.keys())[:40],
                }
        resultado["campos_extras"] = campos_extras

        estrutura_minima = (
            isinstance(datas, list)
            and isinstance(horarios, list)
            and isinstance(acumulados, list)
        )
        resultado["estrutura_minima_esperada"] = estrutura_minima

        if estrutura_minima:
            resultado["status"] = "json_horario_recebido_para_validacao"
        else:
            resultado["status"] = "json_recebido_estrutura_inesperada"

        resultado["observacao"] = (
            "A #141 confirma somente a estrutura bruta da rota horario. "
            "Mesmo com valores numericos, eles permanecem diagnosticos ate "
            "validarmos como datas, horarios e acumulados se combinam e qual "
            "janela cada celula representa."
        )
        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha da #141 nao altera o acumulado CEMADEN #136 nem os "
            "diagnosticos #138-#140."
        )
        return resultado



# =========================================================
# #142 - DECODIFICACAO TEMPORAL DA MATRIZ HORARIA CEMADEN
# =========================================================

def decodificar_matriz_horaria_cemaden_142(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#142",
        "tipo": "decodificacao_temporal_matriz_horaria_cemaden",
        "fonte": "CEMADEN",
        "estacao": None,
        "endpoint": None,
        "timezone_fonte": "UTC",
        "timezone_local": "America/Sao_Paulo",
        "leituras_validas": [],
        "quantidade_leituras_validas": 0,
        "ultima_leitura": None,
        "idade_ultima_leitura_min": None,
        "dados_frescos_diagnostico": None,
        "limite_frescor_diagnostico_min": 120,
        "acumulados_diagnosticos": {
            "1h_mm": None,
            "6h_mm": None,
            "24h_mm": None,
        },
        "comparacao_produto_311_24": None,
        "publicacao_automatica": False,
        "classificacao_risco_automatica": False,
        "regra_seguranca": (
            "A #142 decodifica a matriz horaria em instantes UTC e calcula "
            "somatorios apenas como diagnostico. Nao publica chuva operacional "
            "nem infere chuva no Comasa. A granularidade de 10 minutos continua "
            "nao validada."
        ),
    }

    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado

        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": selecionada.get("uf"),
            "distancia_comasa_aprox_km": selecionada.get(
                "distancia_comasa_aprox_km"
            ),
        }

        base = (
            "https://mapservices.cemaden.gov.br/"
            "MapaInterativoWS/resources/"
        )
        endpoint = base + "horario/" + str(idestacao) + "/23"
        resultado["endpoint"] = endpoint

        resposta = get(endpoint)
        dados = resposta.json()
        if not isinstance(dados, dict):
            raise ValueError("Resposta horario sem objeto JSON.")

        datas = dados.get("datas")
        horarios = dados.get("horarios")
        acumulados = dados.get("acumulados")

        if not (
            isinstance(datas, list)
            and isinstance(horarios, list)
            and isinstance(acumulados, list)
        ):
            raise ValueError(
                "Matriz horario sem datas/horarios/acumulados validos."
            )

        leituras = []
        for indice_data, data_txt in enumerate(datas):
            if indice_data >= len(acumulados):
                continue
            linha = acumulados[indice_data]
            if not isinstance(linha, list):
                continue

            for indice_hora, hora_txt in enumerate(horarios):
                if indice_hora >= len(linha):
                    continue
                valor = linha[indice_hora]
                if valor is None:
                    continue

                try:
                    numero = float(str(valor).replace(",", "."))
                except Exception:
                    continue

                data_base = datetime.strptime(
                    str(data_txt).strip(),
                    "%d/%m/%Y",
                )
                achado_hora = re.search(r"(\d{1,2})", str(hora_txt))
                if not achado_hora:
                    continue
                hora = int(achado_hora.group(1))
                if hora < 0 or hora > 23:
                    continue

                instante_utc = data_base.replace(
                    hour=hora,
                    minute=0,
                    second=0,
                    microsecond=0,
                    tzinfo=UTC,
                )
                instante_local = instante_utc.astimezone(FUSO)

                leituras.append({
                    "instante_utc": instante_utc,
                    "instante_local": instante_local,
                    "valor_mm": numero,
                    "data_fonte": str(data_txt),
                    "hora_fonte": str(hora_txt),
                })

        leituras.sort(key=lambda x: x["instante_utc"])

        unicas = {}
        for leitura in leituras:
            unicas[leitura["instante_utc"].isoformat()] = leitura
        leituras = sorted(
            unicas.values(),
            key=lambda x: x["instante_utc"],
        )

        resultado["quantidade_leituras_validas"] = len(leituras)
        resultado["leituras_validas"] = [
            {
                "instante_utc": x["instante_utc"].isoformat(),
                "instante_local": x["instante_local"].isoformat(),
                "valor_mm": x["valor_mm"],
                "data_fonte": x["data_fonte"],
                "hora_fonte": x["hora_fonte"],
            }
            for x in leituras[-30:]
        ]

        if not leituras:
            resultado["status"] = "matriz_sem_leitura_numerica"
            return resultado

        ultima = leituras[-1]
        idade = (
            datetime.now(UTC) - ultima["instante_utc"]
        ).total_seconds() / 60.0
        idade = max(0.0, round(idade, 1))

        resultado["ultima_leitura"] = {
            "instante_utc": ultima["instante_utc"].isoformat(),
            "instante_local": ultima["instante_local"].isoformat(),
            "valor_mm": ultima["valor_mm"],
            "data_fonte": ultima["data_fonte"],
            "hora_fonte": ultima["hora_fonte"],
        }
        resultado["idade_ultima_leitura_min"] = idade
        resultado["dados_frescos_diagnostico"] = idade <= 120

        def somar_ultimas_horas(qtd):
            escolhidas = leituras[-qtd:]
            if len(escolhidas) < qtd:
                return None
            for anterior, posterior in zip(escolhidas, escolhidas[1:]):
                delta = (
                    posterior["instante_utc"] - anterior["instante_utc"]
                ).total_seconds() / 3600.0
                if abs(delta - 1.0) > 1e-9:
                    return None
            return round(
                sum(x["valor_mm"] for x in escolhidas),
                2,
            )

        soma_1h = somar_ultimas_horas(1)
        soma_6h = somar_ultimas_horas(6)
        soma_24h = somar_ultimas_horas(24)

        resultado["acumulados_diagnosticos"] = {
            "1h_mm": soma_1h,
            "6h_mm": soma_6h,
            "24h_mm": soma_24h,
        }

        produto_24h = (chuva_cemaden or {}).get("acumulado_24h_mm")
        diferenca = None
        confere = None
        if (
            isinstance(produto_24h, (int, float))
            and isinstance(soma_24h, (int, float))
        ):
            diferenca = round(float(soma_24h) - float(produto_24h), 2)
            confere = abs(diferenca) <= 0.01

        resultado["comparacao_produto_311_24"] = {
            "produto_311_24_mm": produto_24h,
            "soma_24_celulas_horarias_mm": soma_24h,
            "diferenca_mm": diferenca,
            "coincide_tolerancia_0_01_mm": confere,
        }

        if confere is True:
            resultado["status"] = "matriz_decodificada_com_concordancia_24h"
        elif soma_24h is None:
            resultado["status"] = "matriz_decodificada_sem_24h_continuas"
        else:
            resultado["status"] = "matriz_decodificada_divergencia_24h"

        resultado["observacao"] = (
            "A #142 transforma datas/horarios em instantes UTC e local, "
            "mede a idade da ultima celula e compara a soma de 24 celulas "
            "com o produto independente 311_24. 1h/6h/24h permanecem "
            "diagnosticos nesta etapa; 10 min continua indisponivel."
        )
        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha da #142 nao altera a integracao CEMADEN #136 nem os "
            "diagnosticos anteriores."
        )
        return resultado



# =========================================================
# #143 - AUDITORIA SEMANTICA DAS JANELAS HORARIAS CEMADEN
# =========================================================

def auditar_janelas_horarias_cemaden_143(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#143",
        "tipo": "auditoria_semantica_janelas_horarias_cemaden",
        "fonte": "CEMADEN",
        "estacao": None,
        "base_endpoint": (
            "https://mapservices.cemaden.gov.br/"
            "MapaInterativoWS/resources/horario/"
        ),
        "regra_js_oficial": (
            'cria_grafico_horario(horas): endpoint = '
            'horario/idEstacao/(horas-1)'
        ),
        "janelas_testadas_h": [1, 2, 6, 24, 48],
        "resultados_janelas": [],
        "comparacoes_sobreposicao": [],
        "semantica_confirmada": False,
        "granularidade_10min_confirmada": False,
        "publicacao_automatica": False,
        "classificacao_risco_automatica": False,
        "regra_seguranca": (
            "A #143 compara varias janelas da mesma rota oficial para validar "
            "a semantica temporal. Nao promove 1h/6h/24h ao painel e nao "
            "inventa granularidade de 10 minutos."
        ),
    }

    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado

        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "uf": selecionada.get("uf"),
        }

        base = resultado["base_endpoint"]
        mapas = {}

        def extrair_celulas(dados):
            datas = dados.get("datas")
            horarios = dados.get("horarios")
            acumulados = dados.get("acumulados")
            if not (
                isinstance(datas, list)
                and isinstance(horarios, list)
                and isinstance(acumulados, list)
            ):
                return []

            celulas = []
            for i, data_txt in enumerate(datas):
                if i >= len(acumulados) or not isinstance(acumulados[i], list):
                    continue
                linha = acumulados[i]
                for j, hora_txt in enumerate(horarios):
                    if j >= len(linha):
                        continue
                    valor = linha[j]
                    if valor is None:
                        continue
                    try:
                        numero = float(str(valor).replace(",", "."))
                    except Exception:
                        continue
                    try:
                        data_base = datetime.strptime(
                            str(data_txt).strip(),
                            "%d/%m/%Y",
                        )
                    except Exception:
                        continue
                    achado = re.search(r"(\d{1,2})", str(hora_txt))
                    if not achado:
                        continue
                    hora = int(achado.group(1))
                    if hora < 0 or hora > 23:
                        continue
                    instante = data_base.replace(
                        hour=hora,
                        minute=0,
                        second=0,
                        microsecond=0,
                        tzinfo=UTC,
                    )
                    celulas.append({
                        "instante_utc": instante.isoformat(),
                        "instante_local": instante.astimezone(FUSO).isoformat(),
                        "valor_mm": numero,
                    })
            unicas = {x["instante_utc"]: x for x in celulas}
            return [unicas[k] for k in sorted(unicas)]

        for horas in resultado["janelas_testadas_h"]:
            parametro = horas - 1
            endpoint = base + str(idestacao) + "/" + str(parametro)
            item = {
                "janela_solicitada_h": horas,
                "parametro_endpoint": parametro,
                "endpoint": endpoint,
                "http_status": None,
                "quantidade_celulas_numericas": 0,
                "primeira_celula": None,
                "ultima_celula": None,
                "soma_mm": None,
            }
            try:
                resposta = get(endpoint)
                item["http_status"] = resposta.status_code
                dados = resposta.json()
                celulas = extrair_celulas(dados) if isinstance(dados, dict) else []
                item["quantidade_celulas_numericas"] = len(celulas)
                if celulas:
                    item["primeira_celula"] = celulas[0]
                    item["ultima_celula"] = celulas[-1]
                    item["soma_mm"] = round(
                        sum(x["valor_mm"] for x in celulas),
                        2,
                    )
                mapas[horas] = {
                    x["instante_utc"]: x["valor_mm"]
                    for x in celulas
                }
            except Exception as e:
                item["erro"] = str(e)[:500]

            resultado["resultados_janelas"].append(item)

        # Janelas maiores devem preservar exatamente as celulas da janela menor
        # quando os instantes se sobrepoem.
        pares = [(1, 2), (2, 6), (6, 24), (24, 48)]
        comparacoes = []
        todas_coerentes = True

        for menor, maior in pares:
            a = mapas.get(menor, {})
            b = mapas.get(maior, {})
            comuns = sorted(set(a) & set(b))
            divergencias = []
            for instante in comuns:
                if abs(float(a[instante]) - float(b[instante])) > 0.000001:
                    divergencias.append({
                        "instante_utc": instante,
                        "menor_mm": a[instante],
                        "maior_mm": b[instante],
                    })

            esperado_minimo = min(
                len(a),
                len(b),
            )
            coerente = (
                bool(a)
                and bool(b)
                and len(comuns) == esperado_minimo
                and not divergencias
            )
            if not coerente:
                todas_coerentes = False

            comparacoes.append({
                "janela_menor_h": menor,
                "janela_maior_h": maior,
                "celulas_menor": len(a),
                "celulas_maior": len(b),
                "instantes_em_comum": len(comuns),
                "divergencias_valor": divergencias[:20],
                "sobreposicao_coerente": coerente,
            })

        resultado["comparacoes_sobreposicao"] = comparacoes

        # Valida a regra horas -> quantidade de celulas quando o servico
        # retorna a janela completa.
        validacoes_quantidade = []
        for item in resultado["resultados_janelas"]:
            horas = item["janela_solicitada_h"]
            qtd = item["quantidade_celulas_numericas"]
            validacoes_quantidade.append({
                "janela_h": horas,
                "celulas": qtd,
                "quantidade_compativel_com_janela": qtd == horas,
            })
        resultado["validacoes_quantidade"] = validacoes_quantidade

        quantidades_ok = all(
            x["quantidade_compativel_com_janela"]
            for x in validacoes_quantidade
        )

        resultado["semantica_confirmada"] = (
            todas_coerentes and quantidades_ok
        )

        produto_24 = (chuva_cemaden or {}).get("acumulado_24h_mm")
        soma_24 = None
        for item in resultado["resultados_janelas"]:
            if item["janela_solicitada_h"] == 24:
                soma_24 = item["soma_mm"]
                break

        if (
            isinstance(produto_24, (int, float))
            and isinstance(soma_24, (int, float))
        ):
            diferenca = round(float(soma_24) - float(produto_24), 2)
            resultado["comparacao_311_24"] = {
                "produto_311_24_mm": produto_24,
                "soma_janela_24h_mm": soma_24,
                "diferenca_mm": diferenca,
                "coincide_0_01_mm": abs(diferenca) <= 0.01,
            }
        else:
            resultado["comparacao_311_24"] = {
                "produto_311_24_mm": produto_24,
                "soma_janela_24h_mm": soma_24,
                "diferenca_mm": None,
                "coincide_0_01_mm": None,
            }

        if resultado["semantica_confirmada"]:
            resultado["status"] = "janelas_horarias_coerentes"
        else:
            resultado["status"] = "janelas_horarias_requerem_revisao"

        resultado["observacao"] = (
            "A #143 testa a propria regra do JavaScript oficial: pedir N horas "
            "usa parametro N-1. Ela exige que janelas maiores preservem os "
            "mesmos valores nos instantes sobrepostos e que a quantidade de "
            "celulas numericas corresponda a janela pedida. O teste nao "
            "estabelece granularidade sub-horaria."
        )
        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha da #143 nao altera CEMADEN #136 nem diagnosticos #138-#142."
        )
        return resultado



# =========================================================
# #144 - CHUVA OBSERVADA CEMADEN / BLOCO OPERACIONAL SEGURO
# =========================================================

def chuva_observada_cemaden_144(chuva_cemaden):
    resultado = {
        "status": "indisponivel",
        "versao": "#144",
        "tipo": "observacao_pluviometrica_horaria_estacao",
        "fonte": "CEMADEN",
        "fonte_primaria": "Centro Nacional de Monitoramento e Alertas de Desastres Naturais",
        "estacao": None,
        "1h_mm": None,
        "6h_mm": None,
        "24h_mm": None,
        "horario_ultima_celula_utc": None,
        "horario_ultima_celula_local": None,
        "idade_leitura_min": None,
        "dados_frescos": False,
        "limite_frescor_min": 120,
        "granularidade": "horaria",
        "granularidade_10min_disponivel": False,
        "representatividade": (
            "Medição observada na estação CEMADEN selecionada. "
            "Não equivale a medição no Comasa."
        ),
        "classificacao_risco_automatica": False,
        "regra_seguranca": (
            "Valor zero significa zero somente na estação e nas janelas "
            "horárias informadas. Falha, atraso ou ausência de dado nunca "
            "é convertida em 0 mm. O bloco não infere chuva no Comasa."
        ),
    }

    try:
        selecionada = (chuva_cemaden or {}).get("estacao_selecionada") or {}
        idestacao = selecionada.get("id")
        if idestacao is None:
            resultado["status"] = "sem_estacao_selecionada"
            return resultado

        resultado["estacao"] = {
            "id": idestacao,
            "codigo": selecionada.get("codigo"),
            "nome": selecionada.get("nome"),
            "cidade": selecionada.get("cidade"),
            "uf": selecionada.get("uf"),
            "distancia_comasa_aprox_km": selecionada.get(
                "distancia_comasa_aprox_km"
            ),
        }

        base = (
            "https://mapservices.cemaden.gov.br/"
            "MapaInterativoWS/resources/horario/"
        )

        def extrair_janela(horas):
            endpoint = base + str(idestacao) + "/" + str(horas - 1)
            resposta = get(endpoint)
            dados = resposta.json()

            if not isinstance(dados, dict):
                raise ValueError("Resposta CEMADEN horario sem objeto JSON.")

            datas = dados.get("datas")
            horarios = dados.get("horarios")
            acumulados = dados.get("acumulados")

            if not (
                isinstance(datas, list)
                and isinstance(horarios, list)
                and isinstance(acumulados, list)
            ):
                raise ValueError(
                    "Resposta CEMADEN sem datas/horarios/acumulados validos."
                )

            celulas = []
            for i, data_txt in enumerate(datas):
                if i >= len(acumulados) or not isinstance(acumulados[i], list):
                    continue

                linha = acumulados[i]

                for j, hora_txt in enumerate(horarios):
                    if j >= len(linha):
                        continue

                    valor = linha[j]
                    if valor is None:
                        continue

                    try:
                        numero = float(str(valor).replace(",", "."))
                    except Exception:
                        continue

                    try:
                        data_base = datetime.strptime(
                            str(data_txt).strip(),
                            "%d/%m/%Y",
                        )
                    except Exception:
                        continue

                    achado = re.search(r"(\d{1,2})", str(hora_txt))
                    if not achado:
                        continue

                    hora = int(achado.group(1))
                    if hora < 0 or hora > 23:
                        continue

                    instante_utc = data_base.replace(
                        hour=hora,
                        minute=0,
                        second=0,
                        microsecond=0,
                        tzinfo=UTC,
                    )

                    celulas.append({
                        "instante_utc": instante_utc,
                        "valor_mm": numero,
                    })

            unicas = {
                x["instante_utc"].isoformat(): x
                for x in celulas
            }
            celulas = sorted(
                unicas.values(),
                key=lambda x: x["instante_utc"],
            )

            if len(celulas) != horas:
                raise ValueError(
                    "Janela de "
                    + str(horas)
                    + "h retornou "
                    + str(len(celulas))
                    + " celulas numericas."
                )

            for anterior, posterior in zip(celulas, celulas[1:]):
                delta = (
                    posterior["instante_utc"]
                    - anterior["instante_utc"]
                ).total_seconds() / 3600.0

                if abs(delta - 1.0) > 1e-9:
                    raise ValueError(
                        "Janela CEMADEN sem continuidade horaria."
                    )

            return {
                "horas": horas,
                "endpoint": endpoint,
                "celulas": celulas,
                "soma_mm": round(
                    sum(x["valor_mm"] for x in celulas),
                    2,
                ),
                "ultima": celulas[-1],
            }

        janela_1 = extrair_janela(1)
        janela_6 = extrair_janela(6)
        janela_24 = extrair_janela(24)

        ultima = janela_1["ultima"]

        # Exige que todas as janelas terminem no mesmo instante.
        if not (
            janela_6["ultima"]["instante_utc"] == ultima["instante_utc"]
            and janela_24["ultima"]["instante_utc"] == ultima["instante_utc"]
        ):
            raise ValueError(
                "Janelas 1h/6h/24h nao terminam no mesmo instante."
            )

        idade = (
            datetime.now(UTC) - ultima["instante_utc"]
        ).total_seconds() / 60.0
        idade = max(0.0, round(idade, 1))
        fresco = idade <= resultado["limite_frescor_min"]

        # A janela de 24h precisa continuar concordando com o produto
        # independente 311_24 antes de ser promovida neste bloco.
        produto_24 = (chuva_cemaden or {}).get("acumulado_24h_mm")
        concorda_24 = False
        diferenca_24 = None

        if isinstance(produto_24, (int, float)):
            diferenca_24 = round(
                janela_24["soma_mm"] - float(produto_24),
                2,
            )
            concorda_24 = abs(diferenca_24) <= 0.01

        resultado["validacao_24h"] = {
            "produto_311_24_mm": produto_24,
            "soma_24_celulas_mm": janela_24["soma_mm"],
            "diferenca_mm": diferenca_24,
            "coincide_tolerancia_0_01_mm": concorda_24,
        }

        if not concorda_24:
            resultado["status"] = "bloqueado_divergencia_24h"
            resultado["observacao"] = (
                "A janela horaria de 24h divergiu do produto 311_24; "
                "1h/6h/24h permanecem indisponiveis no bloco operacional."
            )
            return resultado

        resultado["1h_mm"] = janela_1["soma_mm"]
        resultado["6h_mm"] = janela_6["soma_mm"]
        resultado["24h_mm"] = janela_24["soma_mm"]
        resultado["horario_ultima_celula_utc"] = (
            ultima["instante_utc"].isoformat()
        )
        resultado["horario_ultima_celula_local"] = (
            ultima["instante_utc"].astimezone(FUSO).isoformat()
        )
        resultado["idade_leitura_min"] = idade
        resultado["dados_frescos"] = fresco
        resultado["endpoints"] = {
            "1h": janela_1["endpoint"],
            "6h": janela_6["endpoint"],
            "24h": janela_24["endpoint"],
        }

        resultado["status"] = (
            "online_fresco_validado"
            if fresco
            else "online_desatualizado_validado"
        )

        resultado["observacao"] = (
            "Bloco operacional baseado em janelas horarias coerentes "
            "validadas nas #141-#143. O horario exibido e o rotulo temporal "
            "da ultima celula fornecida pelo CEMADEN; a #144 nao afirma "
            "se ele representa inicio ou fechamento do intervalo horario. "
            "Granularidade de 10 minutos permanece indisponivel."
        )

        return resultado

    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha da #144 mantem 1h/6h/24h indisponiveis; "
            "nenhum valor ausente e convertido em zero."
        )
        return resultado


# =========================================================
# #123 - CHUVA OBSERVADA / ESTAÇÃO INMET - RECUPERADA NA #128
# =========================================================

def numero_inmet(valor):
    if valor is None: return None
    texto=str(valor).strip().replace(",", ".")
    if not texto or texto.lower() in ("null","none","nan"): return None
    try: numero=float(texto)
    except (TypeError,ValueError): return None
    return None if abs(numero)>=9999 else numero


def horario_inmet_utc(data,hora):
    if not data or hora is None: return None
    h=str(hora).strip().zfill(4)[:4]
    try: return datetime.strptime(f"{data} {h}","%Y-%m-%d %H%M").replace(tzinfo=UTC)
    except Exception: return None


def buscar_chuva_observada_inmet():
    try:
        resposta=get(INMET_ATUAL+IBGE_JOINVILLE).json()
        if not isinstance(resposta,dict): raise ValueError("Resposta INMET em formato inesperado.")
        estacao=resposta.get("estacao") or {}; dados=resposta.get("dados") or {}
        if not isinstance(estacao,dict) or not isinstance(dados,dict): raise ValueError("INMET sem blocos estacao/dados válidos.")
        chuva=numero_inmet(dados.get("CHUVA")); distancia=numero_inmet(estacao.get("DISTANCIA_EM_KM"))
        instante=horario_inmet_utc(dados.get("DT_MEDICAO"),dados.get("HR_MEDICAO"))
        idade=None; horario_local=None; fresco=False
        if instante is not None:
            idade=max(0.0,round((datetime.now(UTC)-instante).total_seconds()/60,1))
            horario_local=instante.astimezone(FUSO).isoformat(); fresco=idade<=120
        status="online_fresco" if fresco else "online_desatualizado"
        if chuva is None: status="online_sem_chuva_valida"
        return {"status":status,"tipo":"observacao_estacao_automatica","fonte":"INMET","fonte_primaria":"Instituto Nacional de Meteorologia","geocodigo_ibge_consultado":IBGE_JOINVILLE,"estacao":{"codigo":estacao.get("CODIGO") or dados.get("CD_ESTACAO"),"nome":estacao.get("NOME") or dados.get("DC_NOME"),"uf":estacao.get("UF") or dados.get("UF"),"distancia_referencia_joinville_km":distancia},"leitura_horaria_mm":chuva,"horario_medicao_utc":instante.isoformat() if instante else None,"horario_medicao_local":horario_local,"idade_leitura_min":idade,"dados_frescos":fresco,"representatividade":"Medição observada na estação INMET mais próxima retornada para Joinville. Não equivale a medição no Comasa.","regra_seguranca":"Valor zero só significa zero na estação e no intervalo horário informado; nunca significa ausência de chuva no Comasa."}
    except Exception as e:
        return {"status":"indisponivel","tipo":"observacao_estacao_automatica","fonte":"INMET","geocodigo_ibge_consultado":IBGE_JOINVILLE,"leitura_horaria_mm":None,"horario_medicao_utc":None,"horario_medicao_local":None,"idade_leitura_min":None,"dados_frescos":False,"erro":str(e),"regra_seguranca":"Falha de coleta não é interpretada como ausência de chuva."}


def main():
    chuva_cemaden = buscar_chuva_cemaden_136()
    dados = {
        "monitor":
            "Monitor Guaxanduva",
 
        "local":
            "Comasa - Joinville/SC",
 
        "gerado_em":
            agora().isoformat(),
 
        "chuva":
            chuva_cemaden,

        "investigacao_cemaden_138":
            investigar_serie_cemaden_138(chuva_cemaden),

        "investigacao_cemaden_139":
            investigar_endpoint_pcds_139(chuva_cemaden),

        "investigacao_cemaden_140":
            investigar_mapservices_cemaden_140(chuva_cemaden),

        "investigacao_cemaden_141":
            auditar_json_horario_cemaden_141(chuva_cemaden),

        "investigacao_cemaden_142":
            decodificar_matriz_horaria_cemaden_142(chuva_cemaden),

        "investigacao_cemaden_143":
            auditar_janelas_horarias_cemaden_143(chuva_cemaden),

        "chuva_observada_cemaden_144":
            chuva_observada_cemaden_144(chuva_cemaden),
 
        "chuva_observada_inmet":
            buscar_chuva_observada_inmet(),

        "investigacao_radarsc_128":
            investigar_fonte_radarsc(),

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
 
    historico = registrar_historico_validacao(dados)

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
