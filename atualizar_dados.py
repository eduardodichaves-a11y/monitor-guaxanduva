import io
import base64
import json
import math
import hashlib
import statistics
import time
import re
from urllib.parse import urljoin
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
 
import requests
import urllib3
from PIL import Image
from bs4 import BeautifulSoup
import paho.mqtt.client as mqtt
 
 
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
DEFESA_CIVIL_SC_BUSCA = "https://www.defesacivil.sc.gov.br/"
 
FUSO = ZoneInfo("America/Sao_Paulo")
UTC = ZoneInfo("UTC")
 
MARE = (
    "https://ciram.epagri.sc.gov.br/"
    "ciram_arquivos/oceano/tabuamare/csv/"
    "Tabua_Mare_Joinville.csv"
)
 
# #160 - Marégrafo observado oficial EPAGRI/CIRAM para Joinville.
# Esta série é de maré em Joinville/Babitonga e NÃO mede o Rio Guaxanduva.
MAREGRAFO_JOINVILLE = (
    "https://ciram.epagri.sc.gov.br/"
    "graficos/getDataMare11_2913.php"
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
 
        # =========================================================
        # #162 - PREVISAO ACUMULADA • PROXIMAS 24 HORAS
        # Janela movel baseada exclusivamente na serie horaria
        # de precipitacao ja recebida do Open-Meteo.
        # Nao alimenta classificacao automatica de risco nesta etapa.
        # =========================================================
 
        previsao_24h = {
            "status": "indisponivel",
            "fonte": "Open-Meteo",
            "modelo": "Best Match",
            "tipo": "previsao_horaria_acumulada",
            "janela_horas": 24,
            "inicio": None,
            "fim": None,
            "fim_exclusivo": None,
            "horas_esperadas": 24,
            "horas_validas": 0,
            "precipitacao_acumulada_mm": None,
            "integridade": False,
            "uso_no_risco": False,
            "observacao": (
                "Janela movel das proximas 24 horas. "
                "Nesta etapa, o valor e diagnostico e nao alimenta "
                "classificacao automatica de risco."
            ),
        }
 
        tempos_horarios = horario.get("time", [])
        precipitacoes_horarias = horario.get("precipitation", [])
 
        if indice is not None:
            fim_indice = indice + 24
            tempos_janela = tempos_horarios[indice:fim_indice]
            precipitacoes_janela = precipitacoes_horarias[indice:fim_indice]
 
            if tempos_janela:
                previsao_24h["inicio"] = tempos_janela[0]
                previsao_24h["fim"] = tempos_janela[-1]
 
                try:
                    fim_exclusivo = (
                        datetime
                        .fromisoformat(tempos_janela[0])
                        .replace(tzinfo=FUSO)
                        + timedelta(hours=24)
                    )
                    previsao_24h["fim_exclusivo"] = (
                        fim_exclusivo.isoformat()
                    )
                except Exception:
                    pass
 
            valores_validos = []
            serie_completa = (
                len(tempos_janela) == 24
                and len(precipitacoes_janela) == 24
            )
 
            if serie_completa:
                for valor in precipitacoes_janela:
                    try:
                        if valor is None:
                            raise ValueError("precipitacao ausente")
                        numero = float(valor)
                        if numero < 0:
                            raise ValueError("precipitacao negativa")
                        valores_validos.append(numero)
                    except Exception:
                        valores_validos = []
                        break
 
            previsao_24h["horas_validas"] = len(valores_validos)
 
            if serie_completa and len(valores_validos) == 24:
                previsao_24h["status"] = "online_completo"
                previsao_24h["precipitacao_acumulada_mm"] = round(
                    sum(valores_validos),
                    2,
                )
                previsao_24h["integridade"] = True
            else:
                previsao_24h["status"] = "janela_incompleta"
                previsao_24h["observacao"] = (
                    "Nao foi possivel formar 24 intervalos horarios "
                    "validos consecutivos. Ausencia de dados nao e "
                    "interpretada como 0 mm."
                )
 
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
 
            "proximas_24h":
                previsao_24h,
 
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
# #160 - MARÉ OBSERVADA • JOINVILLE / BABITONGA • EPAGRI/CIRAM
# =========================================================
 
def _numero_maregrafo_160(valor):
    """Converte números do DataTable; 'null' textual e nulo viram None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto or texto.lower() in {"null", "none", "nan"}:
        return None
    try:
        return float(texto.replace(",", "."))
    except Exception:
        return None
 
 
def _momento_maregrafo_160(rotulo, referencia):
    """Interpreta DD/MM HH:MM escolhendo o ano mais próximo da coleta."""
    texto = str(rotulo or "").strip()
    base = datetime.strptime(texto, "%d/%m %H:%M")
    candidatos = []
    for ano in (referencia.year - 1, referencia.year, referencia.year + 1):
        try:
            candidatos.append(
                datetime(
                    ano, base.month, base.day, base.hour, base.minute,
                    tzinfo=FUSO,
                )
            )
        except ValueError:
            continue
    if not candidatos:
        raise ValueError("Data/hora inválida no marégrafo: " + texto)
    return min(candidatos, key=lambda dt: abs((dt - referencia).total_seconds()))
 
 
def buscar_mare_observada_joinville_160():
    """Lê o último valor observado não nulo do marégrafo oficial de Joinville.
 
    A página oficial da EPAGRI/CIRAM associa este endpoint ao gráfico de
    Joinville e define a unidade vertical como cm. O bloco permanece separado
    do Rio Guaxanduva: não é sensor fluvial e não altera o risco operacional.
    """
    resultado = {
        "status": "indisponivel",
        "fonte": "EPAGRI/CIRAM",
        "tipo": "mare_observada",
        "local": "Joinville / Babitonga",
        "unidade": "cm",
        "url_fonte": MAREGRAFO_JOINVILLE,
        "nivel_cm": None,
        "nivel_m": None,
        "mare_astronomica_cm": None,
        "residual_cm": None,
        "nmm_cm": None,
        "horario": None,
        "idade_min": None,
        "frescor": "indisponivel",
        "residual_aritmetica_validada": None,
        "uso_no_risco": False,
        "observacao": (
            "Medição de maré em Joinville/Babitonga; não é nível do "
            "Rio Guaxanduva e não entra automaticamente no painel de risco."
        ),
    }
 
    try:
        resposta = get(MAREGRAFO_JOINVILLE)
        payload = resposta.json()
        colunas = payload.get("cols") or []
        linhas = payload.get("rows") or []
 
        rotulos = [str(c.get("label") or "").strip() for c in colunas]
        esperados = [
            "Topping",
            "Mare Obser. (MO)",
            "Mare Astron (MA)",
            "Mare Residual (MA-MO)",
            "Previsao MohidSC",
            "Mare Residual Prevista",
            "NMM",
        ]
        resultado["colunas_recebidas"] = rotulos
        resultado["estrutura_validada"] = rotulos[:7] == esperados
        if not resultado["estrutura_validada"]:
            raise ValueError("Estrutura inesperada no DataTable do marégrafo")
 
        atual = agora()
        observacoes = []
        for linha in linhas:
            celulas = linha.get("c") or []
            if len(celulas) < 7:
                continue
            valores = [c.get("v") if isinstance(c, dict) else None for c in celulas[:7]]
            nivel = _numero_maregrafo_160(valores[1])
            if nivel is None:
                continue
            try:
                momento = _momento_maregrafo_160(valores[0], atual)
            except Exception:
                continue
            observacoes.append({
                "momento": momento,
                "nivel_cm": nivel,
                "mare_astronomica_cm": _numero_maregrafo_160(valores[2]),
                "residual_cm": _numero_maregrafo_160(valores[3]),
                "nmm_cm": _numero_maregrafo_160(valores[6]),
            })
 
        if not observacoes:
            raise ValueError("Nenhuma observação de maré não nula encontrada")
 
        # Não seleciona um ponto futuro como observação atual por erro de relógio/dado.
        passadas = [o for o in observacoes if o["momento"] <= atual + timedelta(minutes=5)]
        ultimo = max(passadas or observacoes, key=lambda o: o["momento"])
        idade_min = max(0.0, (atual - ultimo["momento"]).total_seconds() / 60.0)
 
        astronomica = ultimo["mare_astronomica_cm"]
        residual = ultimo["residual_cm"]
        validacao = None
        erro_residual = None
        if astronomica is not None and residual is not None:
            calculado = ultimo["nivel_cm"] - astronomica
            erro_residual = abs(calculado - residual)
            validacao = erro_residual <= 0.2
 
        # A série observada é de 15 min. Até 90 min é apresentada como atual;
        # acima disso o valor permanece disponível, mas explicitamente atrasado.
        if idade_min <= 90:
            status = "observado_disponivel"
            frescor = "atual"
        else:
            status = "observado_atrasado"
            frescor = "atrasado"
 
        resultado.update({
            "status": status,
            "nivel_cm": round(ultimo["nivel_cm"], 2),
            "nivel_m": round(ultimo["nivel_cm"] / 100.0, 3),
            "mare_astronomica_cm": astronomica,
            "residual_cm": residual,
            "nmm_cm": ultimo["nmm_cm"],
            "horario": ultimo["momento"].isoformat(),
            "idade_min": round(idade_min, 1),
            "frescor": frescor,
            "residual_aritmetica_validada": validacao,
            "erro_residual_cm": None if erro_residual is None else round(erro_residual, 3),
            "quantidade_observacoes_validas": len(observacoes),
        })
        return resultado
 
    except Exception as e:
        resultado["erro"] = str(e)
        return resultado
 
 
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
 
 
 
def buscar_alerta_granizo_148():
    """
    #148 - Consulta resiliente dos alertas oficiais da Defesa Civil SC.
 
    Estratégia:
    1) tenta mais de uma rota oficial do mesmo portal;
    2) usa timeouts curtos e tentativas controladas;
    3) procura somente publicações recentes com granizo;
    4) confirma Joinville no conteúdo oficial antes de aceitar o alerta;
    5) falha de todas as rotas = INDISPONÍVEL, nunca "sem alerta".
    """
    saida = {
        "status": "indisponivel",
        "versao": "#148",
        "fonte": "Secretaria de Estado da Protecao e Defesa Civil de Santa Catarina",
        "tipo": "alerta_oficial_municipal",
        "municipio": "Joinville",
        "granizo_em_alerta_ativo": None,
        "nivel": None,
        "inicio_local": None,
        "validade_ate_local": None,
        "janela_horas": None,
        "titulo": None,
        "url": None,
        "ultima_publicacao_relevante": None,
        "rotas_testadas": [],
        "regra_seguranca": (
            "Somente publicacao oficial que mencione Joinville e granizo, "
            "com janela temporal ainda valida, e tratada como alerta ativo. "
            "Falha de consulta permanece indisponivel e nunca significa "
            "ausencia de risco."
        ),
    }
 
    def requisicao_curta(url, params=None):
        ultimo_erro = None
        for tentativa in range(1, 3):
            try:
                r = requests.get(
                    url,
                    params=params,
                    timeout=(8, 12),
                    headers={
                        "User-Agent": "Monitor-Guaxanduva/1.0",
                        "Accept": "text/html,application/xhtml+xml,application/json",
                    },
                )
                r.raise_for_status()
                return r, tentativa, None
            except Exception as e:
                ultimo_erro = str(e)
        return None, 2, ultimo_erro
 
    def coletar_links_html(html, base):
        soup = BeautifulSoup(html, "html.parser")
        achados = []
        vistos = set()
        for a in soup.find_all("a", href=True):
            href = urljoin(base, str(a.get("href") or "").strip())
            texto = " ".join(a.stripped_strings)
            combinado = (texto + " " + href).lower()
            if (
                href.startswith("https://www.defesacivil.sc.gov.br/")
                and re.search(r"/20\d{2}/\d{2}/\d{2}/", href)
                and "granizo" in combinado
                and href not in vistos
            ):
                vistos.add(href)
                achados.append(href)
        return achados
 
    rotas = [
        (
            "pagina_alertas",
            "https://www.defesacivil.sc.gov.br/alerta/",
            None,
        ),
        (
            "busca_site",
            "https://www.defesacivil.sc.gov.br/",
            {"s": "granizo Joinville"},
        ),
        (
            "busca_wordpress_json",
            "https://www.defesacivil.sc.gov.br/wp-json/wp/v2/search",
            {"search": "granizo Joinville", "per_page": 20},
        ),
    ]
 
    links = []
    vistos = set()
    alguma_rota_online = False
 
    for nome, url, params in rotas:
        resposta, tentativas, erro = requisicao_curta(url, params=params)
        registro = {
            "rota": nome,
            "url": url,
            "tentativas": tentativas,
            "status": "erro" if resposta is None else "online",
        }
        if erro:
            registro["erro"] = erro[:500]
        saida["rotas_testadas"].append(registro)
 
        if resposta is None:
            continue
 
        alguma_rota_online = True
 
        try:
            if nome == "busca_wordpress_json":
                dados = resposta.json()
                if isinstance(dados, list):
                    for item in dados:
                        if not isinstance(item, dict):
                            continue
                        href = str(item.get("url") or "").strip()
                        titulo = str(item.get("title") or "")
                        if (
                            href.startswith("https://www.defesacivil.sc.gov.br/")
                            and "granizo" in (titulo + " " + href).lower()
                            and href not in vistos
                        ):
                            vistos.add(href)
                            links.append(href)
            else:
                for href in coletar_links_html(resposta.text, url):
                    if href not in vistos:
                        vistos.add(href)
                        links.append(href)
        except Exception as e:
            registro["parse_erro"] = str(e)[:500]
 
    # Publicações de alerta são curtas; limitar evita transformar uma
    # indisponibilidade parcial em execução excessivamente longa.
    links = links[:12]
    relevantes = []
 
    for href in links:
        pagina, tentativas, erro = requisicao_curta(href)
        if pagina is None:
            continue
 
        try:
            psoup = BeautifulSoup(pagina.text, "html.parser")
            h1 = psoup.find("h1")
            titulo = " ".join(h1.stripped_strings) if h1 else ""
            texto = " ".join(psoup.stripped_strings)
            baixo = texto.lower()
 
            if "joinville" not in baixo or "granizo" not in baixo:
                continue
 
            m = re.search(
                r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})",
                titulo,
            )
            if not m:
                continue
 
            dia, mes, hora, minuto = map(int, m.groups())
            my = re.search(r"/(20\d{2})/", href)
            ano = int(my.group(1)) if my else agora().year
            inicio = datetime(ano, mes, dia, hora, minuto, tzinfo=FUSO)
 
            # Descartar publicações muito antigas da análise operacional.
            if inicio < agora() - timedelta(days=7):
                continue
 
            mj = re.search(
                r"pr[oó]ximas?\s+(\d+)\s+horas?",
                titulo,
                flags=re.I,
            )
            if mj:
                janela = int(mj.group(1))
            elif re.search(r"pr[oó]xima\s+hora", titulo, flags=re.I):
                janela = 1
            else:
                janela = None
 
            validade = inicio + timedelta(hours=janela) if janela else None
            nivel = (
                "ALERTA" if titulo.upper().startswith("ALERTA")
                else "ATENCAO" if titulo.upper().startswith("ATENÇÃO")
                else "OBSERVACAO" if titulo.upper().startswith("OBSERVAÇÃO")
                else "INFORMATIVO"
            )
 
            relevantes.append({
                "titulo": titulo,
                "url": href,
                "nivel": nivel,
                "inicio": inicio,
                "validade": validade,
                "janela_horas": janela,
            })
        except Exception:
            continue
 
    saida["links_candidatos"] = len(links)
    saida["publicacoes_relevantes_7d"] = len(relevantes)
 
    if not alguma_rota_online:
        saida["observacao"] = (
            "Todas as rotas oficiais testadas falharam nesta coleta. "
            "O estado permanece INDISPONIVEL; isso nao significa ausencia "
            "de alerta de granizo."
        )
        return saida
 
    if not relevantes:
        # A fonte respondeu, mas não é seguro afirmar "sem alerta" se não
        # conseguimos decodificar nenhuma publicação recente para Joinville.
        saida["status"] = "online_sem_publicacao_relevante_decodificada"
        saida["granizo_em_alerta_ativo"] = None
        saida["observacao"] = (
            "Ao menos uma rota oficial respondeu, mas nenhuma publicacao "
            "recente de granizo para Joinville foi decodificada. Por seguranca, "
            "o Monitor nao converte isso em 'sem alerta'."
        )
        return saida
 
    relevantes.sort(key=lambda x: x["inicio"], reverse=True)
    ultimo = relevantes[0]
    ativos = [
        x for x in relevantes
        if x["validade"] is not None
        and x["inicio"] <= agora() <= x["validade"]
    ]
 
    saida["ultima_publicacao_relevante"] = {
        "titulo": ultimo["titulo"],
        "inicio_local": ultimo["inicio"].isoformat(),
        "validade_ate_local": (
            ultimo["validade"].isoformat() if ultimo["validade"] else None
        ),
        "url": ultimo["url"],
    }
 
    if ativos:
        ativos.sort(key=lambda x: x["inicio"], reverse=True)
        atual = ativos[0]
        saida.update({
            "status": "alerta_oficial_ativo",
            "granizo_em_alerta_ativo": True,
            "nivel": atual["nivel"],
            "inicio_local": atual["inicio"].isoformat(),
            "validade_ate_local": atual["validade"].isoformat(),
            "janela_horas": atual["janela_horas"],
            "titulo": atual["titulo"],
            "url": atual["url"],
            "observacao": (
                "Publicacao oficial recente, com Joinville e granizo, "
                "encontrada dentro da propria janela de validade."
            ),
        })
    else:
        saida.update({
            "status": "online_sem_alerta_granizo_ativo",
            "granizo_em_alerta_ativo": False,
            "nivel": ultimo["nivel"],
            "inicio_local": ultimo["inicio"].isoformat(),
            "validade_ate_local": (
                ultimo["validade"].isoformat() if ultimo["validade"] else None
            ),
            "janela_horas": ultimo["janela_horas"],
            "titulo": ultimo["titulo"],
            "url": ultimo["url"],
            "observacao": (
                "A fonte oficial respondeu e as publicacoes recentes "
                "decodificadas para Joinville estao fora da validade."
            ),
        })
 
    return saida
 
 
def diagnosticar_wis2_inmet_149():
    """
    #149 - Diagnóstico isolado do WIS2/INMET.
 
    Este bloco NÃO altera o estado operacional de granizo.
    Ele apenas testa se o GitHub Actions consegue:
    - abrir TLS/MQTT com um Global Broker WIS2;
    - assinar o tópico oficial de avisos do INMET;
    - receber uma notificação WIS2, caso uma seja publicada durante a janela;
    - registrar links canonical/update sem interpretar o CAP ainda.
    """
    resultado = {
        "status": "nao_testado",
        "versao": "#149",
        "fonte": "WIS2 / INMET / WMO",
        "broker": "globalbroker.meteo.fr",
        "porta": 8883,
        "topico": (
            "origin/a/wis2/br-inmet/data/core/weather/"
            "advisories-warnings/#"
        ),
        "conectado": False,
        "assinatura_confirmada": False,
        "notificacao_recebida": False,
        "quantidade_notificacoes": 0,
        "links": [],
        "amostra_propriedades": None,
        "erro": None,
        "uso_operacional_granizo": False,
        "observacao": (
            "Diagnostico de conectividade e estrutura. Ausencia de mensagem "
            "durante a janela de teste nao significa ausencia de alerta."
        ),
    }
 
    mensagens = []
 
    try:
        cliente = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="monitor-guaxanduva-wis2-149",
            protocol=mqtt.MQTTv311,
        )
        cliente.username_pw_set("everyone", "everyone")
        cliente.tls_set()
 
        def ao_conectar(client, userdata, flags, reason_code, properties):
            try:
                codigo = int(reason_code)
            except Exception:
                codigo = 0 if str(reason_code).lower() == "success" else -1
 
            if codigo == 0:
                resultado["conectado"] = True
                client.subscribe(resultado["topico"], qos=0)
            else:
                resultado["erro"] = (
                    "MQTT recusou conexao: " + str(reason_code)
                )
 
        def ao_assinar(client, userdata, mid, reason_codes, properties):
            resultado["assinatura_confirmada"] = True
 
        def ao_mensagem(client, userdata, msg):
            try:
                texto = msg.payload.decode("utf-8", errors="replace")
                dados = json.loads(texto)
 
                item = {
                    "topico": msg.topic,
                    "bytes": len(msg.payload),
                    "links": [],
                    "propriedades": None,
                }
 
                if isinstance(dados, dict):
                    props = dados.get("properties")
                    if isinstance(props, dict):
                        item["propriedades"] = {
                            k: props.get(k)
                            for k in (
                                "datetime",
                                "pubtime",
                                "data_id",
                                "metadata_id",
                            )
                            if k in props
                        }
 
                    links = dados.get("links")
                    if isinstance(links, list):
                        for link in links:
                            if not isinstance(link, dict):
                                continue
                            rel = link.get("rel")
                            href = link.get("href")
                            if (
                                rel in ("canonical", "update")
                                and isinstance(href, str)
                                and href.startswith(("https://", "http://"))
                            ):
                                item["links"].append({
                                    "rel": rel,
                                    "href": href,
                                    "type": link.get("type"),
                                })
 
                mensagens.append(item)
 
                if len(mensagens) >= 3:
                    client.disconnect()
 
            except Exception as e:
                mensagens.append({
                    "topico": msg.topic,
                    "erro_parse": str(e)[:500],
                })
 
        cliente.on_connect = ao_conectar
        cliente.on_subscribe = ao_assinar
        cliente.on_message = ao_mensagem
 
        cliente.connect(
            resultado["broker"],
            port=resultado["porta"],
            keepalive=30,
        )
 
        cliente.loop_start()
 
        # Janela curta: suficiente para provar conectividade sem atrasar
        # excessivamente o workflow de 15 em 15 minutos.
        import time
        inicio = time.monotonic()
        while time.monotonic() - inicio < 15:
            if resultado["erro"]:
                break
            if len(mensagens) >= 3:
                break
            time.sleep(0.25)
 
        try:
            cliente.disconnect()
        except Exception:
            pass
        cliente.loop_stop()
 
        resultado["quantidade_notificacoes"] = len(mensagens)
        resultado["notificacao_recebida"] = bool(mensagens)
 
        if mensagens:
            primeiro = mensagens[0]
            resultado["links"] = primeiro.get("links", [])
            resultado["amostra_propriedades"] = primeiro.get(
                "propriedades"
            )
 
        if resultado["conectado"] and resultado["assinatura_confirmada"]:
            resultado["status"] = (
                "mqtt_ok_com_notificacao"
                if mensagens
                else "mqtt_ok_sem_notificacao_na_janela"
            )
        elif resultado["conectado"]:
            resultado["status"] = "mqtt_conectado_assinatura_nao_confirmada"
        else:
            resultado["status"] = "mqtt_indisponivel"
 
        return resultado
 
    except Exception as e:
        resultado["status"] = "mqtt_indisponivel"
        resultado["erro"] = str(e)
        return resultado
 
 
def diagnosticar_historico_cap_inmet_150():
    """
    #150 - Consulta o histórico de notificações do próprio WIS2 Node do INMET.
 
    A API OGC do wis2box expõe a coleção 'messages'. Este diagnóstico tenta
    recuperar notificações já publicadas, em vez de depender de uma nova
    mensagem surgir durante poucos segundos de MQTT.
 
    Nenhum resultado deste bloco altera o card operacional de granizo.
    """
    resultado = {
        "status": "indisponivel",
        "versao": "#150",
        "fonte": "WIS2 Node oficial do INMET / wis2box OGC API",
        "endpoint": (
            "https://wis2bra.inmet.gov.br/oapi/"
            "collections/messages/items"
        ),
        "http_status": None,
        "quantidade_features": 0,
        "quantidade_cap_candidatos": 0,
        "amostras_cap": [],
        "estrutura_primeira_feature": None,
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Este bloco apenas investiga notificacoes historicas do CAP. "
            "Nao afirma alerta ativo, ausencia de alerta ou risco de granizo."
        ),
    }
 
    try:
        resposta = requests.get(
            resultado["endpoint"],
            params={
                "f": "json",
                "limit": 100,
            },
            timeout=(10, 20),
            headers={
                "User-Agent": "Monitor-Guaxanduva/1.0",
                "Accept": "application/geo+json,application/json",
            },
        )
        resultado["http_status"] = resposta.status_code
        resposta.raise_for_status()
        dados = resposta.json()
 
        features = []
        if isinstance(dados, dict):
            bruto = dados.get("features")
            if isinstance(bruto, list):
                features = bruto
 
        resultado["quantidade_features"] = len(features)
 
        if features and isinstance(features[0], dict):
            primeira = features[0]
            props = primeira.get("properties")
            resultado["estrutura_primeira_feature"] = {
                "chaves_feature": sorted(
                    str(k) for k in primeira.keys()
                )[:50],
                "chaves_properties": (
                    sorted(str(k) for k in props.keys())[:80]
                    if isinstance(props, dict)
                    else []
                ),
                "id": primeira.get("id"),
            }
 
        candidatos = []
 
        for feature in features:
            if not isinstance(feature, dict):
                continue
 
            props = feature.get("properties")
            if not isinstance(props, dict):
                props = {}
 
            # A estrutura pode variar por versão do wis2box. Para o
            # diagnóstico, serializamos somente a feature corrente e
            # procuramos o tópico/data_id oficial de advisories-warnings.
            texto = json.dumps(
                feature,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            baixo = texto.lower()
 
            if (
                "br-inmet" in baixo
                and "advisories-warnings" in baixo
            ):
                links = feature.get("links")
                if not isinstance(links, list):
                    links = props.get("links")
                if not isinstance(links, list):
                    links = []
 
                links_seguros = []
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    href = link.get("href")
                    rel = link.get("rel")
                    if (
                        isinstance(href, str)
                        and href.startswith(("https://", "http://"))
                    ):
                        links_seguros.append({
                            "rel": rel,
                            "href": href,
                            "type": link.get("type"),
                        })
 
                candidatos.append({
                    "id": feature.get("id"),
                    "datetime": (
                        props.get("datetime")
                        or props.get("pubtime")
                        or props.get("created")
                    ),
                    "data_id": props.get("data_id"),
                    "topic": (
                        props.get("topic")
                        or props.get("channel")
                    ),
                    "links": links_seguros[:10],
                    "chaves_properties": sorted(
                        str(k) for k in props.keys()
                    )[:80],
                })
 
        resultado["quantidade_cap_candidatos"] = len(candidatos)
        resultado["amostras_cap"] = candidatos[:10]
 
        if candidatos:
            resultado["status"] = "historico_cap_encontrado"
            resultado["observacao"] = (
                "Foram encontradas notificacoes historicas relacionadas "
                "ao topico CAP/advisories-warnings do INMET. O proximo passo "
                "e validar e baixar um XML real pelos links publicados."
            )
        elif features:
            resultado["status"] = "api_online_sem_cap_nas_100_features"
            resultado["observacao"] = (
                "A API oficial respondeu e retornou mensagens, mas nenhuma "
                "das 100 features recuperadas pertenceu ao topico CAP. "
                "Isso nao significa ausencia de alertas."
            )
        else:
            resultado["status"] = "api_online_sem_features"
            resultado["observacao"] = (
                "A API oficial respondeu sem features nesta consulta. "
                "Isso nao significa ausencia de alertas."
            )
 
        return resultado
 
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha no diagnostico historico #150. Nenhuma conclusao sobre "
            "alerta de granizo e produzida a partir desta falha."
        )
        return resultado
 
 
def diagnosticar_filtro_cap_inmet_151():
    """
    #151 - Descobre e testa filtros seletivos da OGC API do WIS2/INMET.
 
    Objetivo:
    - consultar /queryables da coleção messages;
    - verificar se data_id é filtrável;
    - testar filtros seletivos para advisories-warnings;
    - registrar data_ids reais retornados pela API.
 
    Continua estritamente diagnóstico: não altera o card de granizo.
    """
    base = "https://wis2bra.inmet.gov.br/oapi/collections/messages"
    alvo = "advisories-warnings"
 
    resultado = {
        "status": "indisponivel",
        "versao": "#151",
        "fonte": "WIS2 Node oficial do INMET / OGC API",
        "queryables_http": None,
        "queryables": [],
        "data_id_filtravel": False,
        "tentativas": [],
        "data_ids_amostra_consulta_geral": [],
        "candidatos_cap": [],
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico de descoberta/filtro. Nenhum resultado deste bloco "
            "significa alerta ativo, ausencia de alerta ou risco de granizo."
        ),
    }
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/geo+json,application/json",
    }
 
    def ler_features(resp):
        try:
            obj = resp.json()
        except Exception:
            return [], None
        if not isinstance(obj, dict):
            return [], obj
        feats = obj.get("features")
        return (feats if isinstance(feats, list) else []), obj
 
    def resumir_features(features, limite=20):
        saida = []
        for f in features[:limite]:
            if not isinstance(f, dict):
                continue
            p = f.get("properties")
            if not isinstance(p, dict):
                p = {}
            saida.append({
                "id": f.get("id"),
                "data_id": p.get("data_id"),
                "datetime": p.get("datetime"),
                "pubtime": p.get("pubtime"),
                "metadata_id": p.get("metadata_id"),
            })
        return saida
 
    try:
        # 1) Descobre formalmente quais propriedades a coleção declara
        # como consultáveis.
        qurl = base + "/queryables"
        qr = requests.get(
            qurl,
            params={"f": "json"},
            timeout=(10, 20),
            headers=headers,
        )
        resultado["queryables_http"] = qr.status_code
 
        if qr.ok:
            qobj = qr.json()
            props = qobj.get("properties") if isinstance(qobj, dict) else None
            if isinstance(props, dict):
                resultado["queryables"] = sorted(str(k) for k in props.keys())
                resultado["data_id_filtravel"] = "data_id" in props
 
        # 2) Coleta uma amostra real de data_id para não depender de
        # suposição sobre a forma do identificador.
        geral = requests.get(
            base + "/items",
            params={"f": "json", "limit": 100},
            timeout=(10, 20),
            headers=headers,
        )
        if geral.ok:
            feats, _ = ler_features(geral)
            ids = []
            for f in feats:
                if not isinstance(f, dict):
                    continue
                p = f.get("properties")
                if not isinstance(p, dict):
                    continue
                did = p.get("data_id")
                if did is not None and str(did) not in ids:
                    ids.append(str(did))
            resultado["data_ids_amostra_consulta_geral"] = ids[:30]
 
        # 3) Testa variantes suportadas por implementações pygeoapi/OGC.
        # Não assumimos que uma delas funciona: cada resposta é registrada.
        testes = [
            ("property_data_id_curto", {"data_id": alvo, "limit": 100}),
            (
                "property_data_id_topico",
                {
                    "data_id": (
                        "br-inmet/data/core/weather/"
                        "advisories-warnings"
                    ),
                    "limit": 100,
                },
            ),
            ("texto_q", {"q": alvo, "limit": 100}),
        ]
 
        candidatos = []
 
        for nome, params in testes:
            params = {"f": "json", **params}
            item = {
                "teste": nome,
                "params": params,
                "http_status": None,
                "quantidade_features": 0,
                "features_amostra": [],
                "erro": None,
            }
 
            try:
                r = requests.get(
                    base + "/items",
                    params=params,
                    timeout=(10, 20),
                    headers=headers,
                )
                item["http_status"] = r.status_code
 
                if r.ok:
                    feats, _ = ler_features(r)
                    item["quantidade_features"] = len(feats)
                    item["features_amostra"] = resumir_features(feats, 10)
 
                    for f in feats:
                        if not isinstance(f, dict):
                            continue
                        p = f.get("properties")
                        if not isinstance(p, dict):
                            continue
                        texto = " ".join(
                            str(p.get(k) or "")
                            for k in ("data_id", "metadata_id", "content")
                        ).lower()
                        if alvo in texto:
                            cand = {
                                "teste": nome,
                                "id": f.get("id"),
                                "data_id": p.get("data_id"),
                                "datetime": p.get("datetime"),
                                "pubtime": p.get("pubtime"),
                                "metadata_id": p.get("metadata_id"),
                                "links": [],
                            }
                            links = f.get("links")
                            if isinstance(links, list):
                                for link in links:
                                    if not isinstance(link, dict):
                                        continue
                                    href = link.get("href")
                                    if isinstance(href, str) and href.startswith(
                                        ("https://", "http://")
                                    ):
                                        cand["links"].append({
                                            "rel": link.get("rel"),
                                            "href": href,
                                            "type": link.get("type"),
                                        })
                            candidatos.append(cand)
                else:
                    item["erro"] = r.text[:500]
 
            except Exception as e:
                item["erro"] = str(e)[:500]
 
            resultado["tentativas"].append(item)
 
        # Remove duplicatas por id/data_id/pubtime.
        unicos = []
        vistos = set()
        for c in candidatos:
            chave = (
                str(c.get("id")),
                str(c.get("data_id")),
                str(c.get("pubtime")),
            )
            if chave in vistos:
                continue
            vistos.add(chave)
            unicos.append(c)
 
        resultado["candidatos_cap"] = unicos[:20]
 
        if unicos:
            resultado["status"] = "cap_localizado_por_filtro"
            resultado["observacao"] = (
                "Ao menos uma notificacao relacionada a advisories-warnings "
                "foi localizada seletivamente. O proximo passo e recuperar "
                "o recurso CAP/XML real sem ainda alterar o estado operacional."
            )
        elif resultado["queryables_http"] == 200:
            resultado["status"] = "api_e_queryables_online_sem_cap_filtrado"
            resultado["observacao"] = (
                "A API e /queryables responderam, mas os filtros testados "
                "nao localizaram CAP. Isso nao significa ausencia de alertas."
            )
        else:
            resultado["status"] = "api_online_queryables_nao_confirmado"
            resultado["observacao"] = (
                "A consulta diagnostica executou, mas /queryables nao foi "
                "confirmado com HTTP 200. Nenhuma conclusao sobre alertas."
            )
 
        return resultado
 
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha no diagnostico seletivo #151. Nenhuma conclusao sobre "
            "alerta de granizo e produzida."
        )
        return resultado
 
 
def diagnosticar_data_id_cap_inmet_152():
    """
    #152 - Descobre o identificador real dos CAPs a partir do
    discovery-metadata oficial WIS2/INMET, sem inventar prefixos.
 
    Preserva strings e links relevantes da resposta oficial e testa como
    data_id somente candidatos que apareçam literalmente no metadata.
    Não altera o card operacional de granizo.
    """
    metadata_url = (
        "https://wis2bra.inmet.gov.br/oapi/collections/"
        "discovery-metadata/items/"
        "urn%3Awmo%3Amd%3Abr-inmet%3Aalerts"
    )
    messages_url = (
        "https://wis2bra.inmet.gov.br/oapi/"
        "collections/messages/items"
    )
 
    resultado = {
        "status": "indisponivel",
        "versao": "#152",
        "fonte": "WIS2 Node oficial do INMET / discovery-metadata",
        "metadata_url": metadata_url,
        "metadata_http": None,
        "chaves_metadata": [],
        "links_metadata": [],
        "strings_relevantes": [],
        "candidatos_data_id": [],
        "testes_data_id": [],
        "cap_localizado": False,
        "notificacoes_cap": [],
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico documental. Nenhum resultado deste bloco afirma "
            "alerta ativo, ausencia de alerta ou risco de granizo."
        ),
    }
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/geo+json,application/json",
    }
 
    def coletar_strings(obj, caminho="$", saida=None):
        if saida is None:
            saida = []
        if len(saida) >= 400:
            return saida
        if isinstance(obj, dict):
            for k, v in obj.items():
                coletar_strings(v, f"{caminho}.{k}", saida)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:200]):
                coletar_strings(v, f"{caminho}[{i}]", saida)
        elif isinstance(obj, str):
            baixo = obj.lower()
            if any(
                termo in baixo
                for termo in (
                    "alert", "advis", "warning", "cap",
                    "br-inmet", "weather", "xml",
                )
            ):
                saida.append({
                    "caminho": caminho,
                    "valor": obj[:1000],
                })
        return saida
 
    def extrair_links(obj):
        encontrados = []
        vistos = set()
 
        def andar(x):
            if isinstance(x, dict):
                href = x.get("href")
                if isinstance(href, str) and href.startswith(
                    ("https://", "http://")
                ):
                    chave = (x.get("rel"), href, x.get("type"))
                    if chave not in vistos:
                        vistos.add(chave)
                        encontrados.append({
                            "rel": x.get("rel"),
                            "href": href,
                            "type": x.get("type"),
                            "title": x.get("title"),
                        })
                for v in x.values():
                    andar(v)
            elif isinstance(x, list):
                for v in x:
                    andar(v)
 
        andar(obj)
        return encontrados[:100]
 
    def extrair_candidatos(strings):
        candidatos = []
        vistos = set()
 
        for item in strings:
            valor = str(item.get("valor") or "").strip()
            baixo = valor.lower()
            if (
                "br-inmet" in baixo
                and any(t in baixo for t in ("alert", "advis", "warning"))
            ):
                pedacos = re.split(r"[\s,;\"'<>]+", valor)
                for p in pedacos:
                    p = p.strip("()[]{}")
                    pl = p.lower()
                    if (
                        "br-inmet" in pl
                        and any(t in pl for t in ("alert", "advis", "warning"))
                        and len(p) <= 500
                        and p not in vistos
                    ):
                        vistos.add(p)
                        candidatos.append(p)
 
        return candidatos[:30]
 
    try:
        r = requests.get(
            metadata_url,
            params={"f": "json"},
            timeout=(10, 25),
            headers=headers,
        )
        resultado["metadata_http"] = r.status_code
        r.raise_for_status()
        metadata = r.json()
 
        if isinstance(metadata, dict):
            resultado["chaves_metadata"] = sorted(
                str(k) for k in metadata.keys()
            )
 
        resultado["links_metadata"] = extrair_links(metadata)
        strings = coletar_strings(metadata)
        resultado["strings_relevantes"] = strings[:100]
        candidatos = extrair_candidatos(strings)
        resultado["candidatos_data_id"] = candidatos
 
        notificacoes = []
        vistos_not = set()
 
        for candidato in candidatos[:15]:
            teste = {
                "data_id": candidato,
                "http_status": None,
                "quantidade_features": 0,
                "amostras": [],
                "erro": None,
            }
 
            try:
                rr = requests.get(
                    messages_url,
                    params={
                        "f": "json",
                        "data_id": candidato,
                        "limit": 20,
                    },
                    timeout=(10, 25),
                    headers=headers,
                )
                teste["http_status"] = rr.status_code
 
                if rr.ok:
                    obj = rr.json()
                    feats = (
                        obj.get("features", [])
                        if isinstance(obj, dict)
                        else []
                    )
                    if not isinstance(feats, list):
                        feats = []
 
                    teste["quantidade_features"] = len(feats)
 
                    for f in feats[:20]:
                        if not isinstance(f, dict):
                            continue
                        p = f.get("properties")
                        if not isinstance(p, dict):
                            p = {}
 
                        amostra = {
                            "id": f.get("id"),
                            "data_id": p.get("data_id"),
                            "datetime": p.get("datetime"),
                            "pubtime": p.get("pubtime"),
                            "metadata_id": p.get("metadata_id"),
                            "links": extrair_links(f)[:10],
                        }
                        teste["amostras"].append(amostra)
 
                        chave = (
                            str(amostra["id"]),
                            str(amostra["data_id"]),
                            str(amostra["pubtime"]),
                        )
                        if chave not in vistos_not:
                            vistos_not.add(chave)
                            notificacoes.append(amostra)
                else:
                    teste["erro"] = rr.text[:500]
 
            except Exception as e:
                teste["erro"] = str(e)[:500]
 
            resultado["testes_data_id"].append(teste)
 
        resultado["notificacoes_cap"] = notificacoes[:30]
        resultado["cap_localizado"] = bool(notificacoes)
 
        if notificacoes:
            resultado["status"] = "data_id_documentado_e_cap_localizado"
            resultado["observacao"] = (
                "O discovery-metadata forneceu candidato documental e ao "
                "menos uma notificacao historica foi localizada. O proximo "
                "passo e validar o recurso CAP/XML real."
            )
        elif candidatos:
            resultado["status"] = (
                "data_id_documentado_sem_notificacao_localizada"
            )
            resultado["observacao"] = (
                "O discovery-metadata revelou candidato literal, mas o "
                "filtro exato nao retornou notificacao nesta consulta. "
                "Isso nao significa ausencia de alertas."
            )
        else:
            resultado["status"] = (
                "metadata_online_sem_data_id_literal_extraido"
            )
            resultado["observacao"] = (
                "O metadata oficial respondeu, mas nenhum data_id CAP foi "
                "extraido pelas regras conservadoras. Strings e links foram "
                "preservados para a proxima investigacao."
            )
 
        return resultado
 
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha no diagnostico #152. Nenhuma conclusao sobre alerta de "
            "granizo e produzida."
        )
        return resultado
 
 
def diagnosticar_cap_por_metadata_id_153():
    """
    #153 - Separa mensagens de METADATA das mensagens de DATA.
 
    A #151 confirmou que metadata_id e filtravel. A #152 confirmou
    documentalmente que o dataset de alertas possui o identificador
    urn:wmo:md:br-inmet:alerts. Aqui usamos esse identificador no campo
    metadata_id da colecao messages, em vez de confundi-lo com data_id.
 
    O objetivo e localizar notificacoes de dados CAP/XML reais.
    Este bloco ainda nao altera o card operacional de granizo.
    """
    endpoint = (
        "https://wis2bra.inmet.gov.br/oapi/"
        "collections/messages/items"
    )
    metadata_alvo = "urn:wmo:md:br-inmet:alerts"
 
    resultado = {
        "status": "indisponivel",
        "versao": "#153",
        "fonte": "WIS2 Node oficial do INMET / messages",
        "endpoint": endpoint,
        "metadata_id_alvo": metadata_alvo,
        "http_status": None,
        "quantidade_features": 0,
        "quantidade_metadata": 0,
        "quantidade_data": 0,
        "data_ids_reais": [],
        "notificacoes_data_cap": [],
        "links_xml_candidatos": [],
        "xml_cap_confirmado": False,
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico de mensagens DATA associadas ao metadata oficial. "
            "Nenhum resultado deste bloco afirma alerta ativo, ausencia de "
            "alerta ou risco de granizo."
        ),
    }
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/geo+json,application/json",
    }
 
    def links_http(feature):
        saida = []
        vistos = set()
        links = feature.get("links") if isinstance(feature, dict) else None
        if not isinstance(links, list):
            return saida
 
        for link in links:
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            if not isinstance(href, str):
                continue
            if not href.startswith(("https://", "http://")):
                continue
            chave = (link.get("rel"), href, link.get("type"))
            if chave in vistos:
                continue
            vistos.add(chave)
            saida.append({
                "rel": link.get("rel"),
                "href": href,
                "type": link.get("type"),
            })
        return saida
 
    try:
        r = requests.get(
            endpoint,
            params={
                "f": "json",
                "metadata_id": metadata_alvo,
                "limit": 100,
            },
            timeout=(10, 25),
            headers=headers,
        )
        resultado["http_status"] = r.status_code
        r.raise_for_status()
 
        obj = r.json()
        features = (
            obj.get("features", [])
            if isinstance(obj, dict)
            else []
        )
        if not isinstance(features, list):
            features = []
 
        resultado["quantidade_features"] = len(features)
 
        data_ids = []
        notificacoes = []
        links_xml = []
 
        for feature in features:
            if not isinstance(feature, dict):
                continue
 
            props = feature.get("properties")
            if not isinstance(props, dict):
                props = {}
 
            data_id = props.get("data_id")
            metadata_id = props.get("metadata_id")
            links = links_http(feature)
 
            # Mensagens de atualização de metadata são explicitamente
            # separadas das mensagens de dados.
            eh_metadata = (
                isinstance(data_id, str)
                and "/metadata/" in data_id.lower()
            )
 
            if eh_metadata:
                resultado["quantidade_metadata"] += 1
                continue
 
            resultado["quantidade_data"] += 1
 
            if isinstance(data_id, str) and data_id not in data_ids:
                data_ids.append(data_id)
 
            item = {
                "id": feature.get("id"),
                "data_id": data_id,
                "metadata_id": metadata_id,
                "datetime": props.get("datetime"),
                "pubtime": props.get("pubtime"),
                "content": props.get("content"),
                "links": links,
            }
            notificacoes.append(item)
 
            for link in links:
                href = link.get("href")
                tipo = str(link.get("type") or "").lower()
                if (
                    isinstance(href, str)
                    and (
                        href.lower().endswith(".xml")
                        or "xml" in tipo
                    )
                ):
                    if href not in [x["href"] for x in links_xml]:
                        links_xml.append({
                            "href": href,
                            "rel": link.get("rel"),
                            "type": link.get("type"),
                            "data_id": data_id,
                        })
 
        resultado["data_ids_reais"] = data_ids[:30]
        resultado["notificacoes_data_cap"] = notificacoes[:30]
        resultado["links_xml_candidatos"] = links_xml[:30]
 
        # Nesta etapa "XML confirmado" significa apenas que uma mensagem
        # DATA associada ao dataset oficial publicou link explicitamente XML.
        # O conteúdo CAP ainda será decodificado numa etapa posterior.
        resultado["xml_cap_confirmado"] = bool(links_xml)
 
        if links_xml:
            resultado["status"] = "mensagem_data_cap_com_link_xml_localizada"
            resultado["observacao"] = (
                "Foram separadas mensagens DATA das mensagens METADATA e "
                "foi localizado ao menos um link XML publicado pela mensagem. "
                "O proximo passo e baixar e decodificar o XML CAP."
            )
        elif notificacoes:
            resultado["status"] = "mensagem_data_cap_localizada_sem_link_xml_explicito"
            resultado["observacao"] = (
                "Foram localizadas mensagens DATA associadas ao metadata "
                "oficial de alertas, mas nenhum link explicitamente XML foi "
                "identificado. O conteudo/links foram preservados para estudo."
            )
        else:
            resultado["status"] = "metadata_id_online_sem_mensagem_data"
            resultado["observacao"] = (
                "A consulta por metadata_id respondeu, mas nenhuma mensagem "
                "DATA foi localizada nas features retornadas. Isso nao "
                "significa ausencia de alertas."
            )
 
        return resultado
 
    except Exception as e:
        resultado["erro"] = str(e)
        resultado["observacao"] = (
            "Falha no diagnostico #153. Nenhuma conclusao sobre alerta de "
            "granizo e produzida."
        )
        return resultado
 
 
def diagnosticar_xml_cap_inmet_154():
    """#154 - Baixa e disseca XMLs CAP reais do INMET, sem uso operacional."""
    import xml.etree.ElementTree as ET
 
    resultado = {
        "status": "indisponivel",
        "versao": "#154",
        "fonte": "WIS2 Node oficial do INMET / CAP XML canonical",
        "xmls_testados": 0,
        "xmls_http_200": 0,
        "xmls_cap_parseaveis": 0,
        "amostras": [],
        "campos_cap_confirmados": [],
        "estrutura_area_confirmada": False,
        "estrutura_geocode_confirmada": False,
        "estrutura_polygon_confirmada": False,
        "mencao_granizo_encontrada_nas_amostras": False,
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico estrutural de XML CAP historico. Mencao historica "
            "a granizo nao significa alerta atual/cobertura de Joinville; "
            "ausencia nas amostras tambem nao significa ausencia de alerta."
        ),
    }
 
    diag153 = diagnosticar_cap_por_metadata_id_153()
    candidatos = diag153.get("links_xml_candidatos", [])
    if not isinstance(candidatos, list) or not candidatos:
        resultado["status"] = "sem_link_xml_da_153"
        return resultado
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/xml,text/xml,*/*",
    }
 
    def local(tag):
        return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else tag
 
    def textos(elem, nome):
        return [
            (x.text or "").strip()
            for x in elem.iter()
            if local(x.tag) == nome and (x.text or "").strip()
        ]
 
    def primeiro(elem, nome):
        vals = textos(elem, nome)
        return vals[0] if vals else None
 
    def areas_info(info):
        saida = []
        for area in [x for x in info.iter() if local(x.tag) == "area"]:
            geocodes = []
            for geo in [x for x in area if local(x.tag) == "geocode"]:
                geocodes.append({
                    "valueName": primeiro(geo, "valueName"),
                    "value": primeiro(geo, "value"),
                })
            poligonos = [
                (x.text or "").strip()
                for x in area
                if local(x.tag) == "polygon" and (x.text or "").strip()
            ]
            saida.append({
                "areaDesc": primeiro(area, "areaDesc"),
                "geocodes": geocodes,
                "polygons": poligonos,
            })
        return saida
 
    campos = set()
    amostras = []
 
    for cand in candidatos[:5]:
        href = cand.get("href") if isinstance(cand, dict) else None
        if not isinstance(href, str) or not href.startswith("https://"):
            continue
 
        resultado["xmls_testados"] += 1
        a = {
            "url": href,
            "data_id": cand.get("data_id"),
            "http_status": None,
            "content_type": None,
            "parseavel": False,
            "raiz": None,
            "namespace": None,
            "identifier": None,
            "sender": None,
            "sent": None,
            "status_cap": None,
            "msgType": None,
            "scope": None,
            "infos": [],
            "menciona_granizo_ou_hail": False,
            "erro": None,
        }
 
        try:
            r = requests.get(href, timeout=(10, 25), headers=headers)
            a["http_status"] = r.status_code
            a["content_type"] = r.headers.get("Content-Type")
            if r.status_code != 200:
                a["erro"] = r.text[:300]
                amostras.append(a)
                continue
 
            resultado["xmls_http_200"] += 1
            raiz = ET.fromstring(r.content)
            a["parseavel"] = True
            resultado["xmls_cap_parseaveis"] += 1
            a["raiz"] = local(raiz.tag)
            if raiz.tag.startswith("{") and "}" in raiz.tag:
                a["namespace"] = raiz.tag[1:].split("}", 1)[0]
 
            for x in raiz.iter():
                campos.add(local(x.tag))
 
            for nome in ("identifier", "sender", "sent", "msgType", "scope"):
                a[nome] = primeiro(raiz, nome)
            a["status_cap"] = primeiro(raiz, "status")
 
            busca = []
            for info in [x for x in raiz.iter() if local(x.tag) == "info"]:
                areas = areas_info(info)
                if areas:
                    resultado["estrutura_area_confirmada"] = True
                for area in areas:
                    if area["geocodes"]:
                        resultado["estrutura_geocode_confirmada"] = True
                    if area["polygons"]:
                        resultado["estrutura_polygon_confirmada"] = True
 
                item = {
                    "language": primeiro(info, "language"),
                    "category": textos(info, "category"),
                    "event": primeiro(info, "event"),
                    "urgency": primeiro(info, "urgency"),
                    "severity": primeiro(info, "severity"),
                    "certainty": primeiro(info, "certainty"),
                    "effective": primeiro(info, "effective"),
                    "onset": primeiro(info, "onset"),
                    "expires": primeiro(info, "expires"),
                    "headline": primeiro(info, "headline"),
                    "description": primeiro(info, "description"),
                    "instruction": primeiro(info, "instruction"),
                    "areas": areas,
                }
                a["infos"].append(item)
                for k in ("event", "headline", "description", "instruction"):
                    if isinstance(item.get(k), str):
                        busca.append(item[k])
                for area in areas:
                    if isinstance(area.get("areaDesc"), str):
                        busca.append(area["areaDesc"])
 
            total = " ".join(busca).lower()
            a["menciona_granizo_ou_hail"] = "granizo" in total or "hail" in total
            if a["menciona_granizo_ou_hail"]:
                resultado["mencao_granizo_encontrada_nas_amostras"] = True
 
        except Exception as e:
            a["erro"] = str(e)[:500]
 
        amostras.append(a)
 
    resultado["amostras"] = amostras
    resultado["campos_cap_confirmados"] = sorted(campos)
 
    if any(a.get("parseavel") and a.get("raiz") == "alert" for a in amostras):
        resultado["status"] = "cap_xml_real_parseado"
        resultado["observacao"] = (
            "Recurso canonical baixado e parseado como CAP XML com raiz "
            "alert. Estrutura real registrada; sem decisao operacional."
        )
    elif resultado["xmls_http_200"] > 0:
        resultado["status"] = "xml_baixado_sem_raiz_cap_alert_confirmada"
    else:
        resultado["status"] = "xml_cap_nao_baixado"
 
    return resultado
 
 
def diagnosticar_cap_recente_inmet_155():
    """#155 - Localiza CAPs recentes por janela temporal e testa XMLs ainda disponíveis."""
    endpoint = (
        "https://wis2bra.inmet.gov.br/oapi/"
        "collections/messages/items"
    )
    metadata_alvo = "urn:wmo:md:br-inmet:alerts"
    agora_utc = datetime.now(UTC)
 
    resultado = {
        "status": "indisponivel",
        "versao": "#155",
        "fonte": "WIS2 Node oficial do INMET / OGC API messages",
        "endpoint": endpoint,
        "metadata_id_alvo": metadata_alvo,
        "consultas_temporais": [],
        "consultas_ordenacao": [],
        "mensagens_data_recentes": [],
        "links_xml_recentes": [],
        "xmls_testados": [],
        "xml_recente_disponivel": False,
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico de localizacao e disponibilidade de CAP recente. "
            "Ausencia de mensagem, erro HTTP ou XML indisponivel nao significa "
            "ausencia de alerta. Nenhum resultado deste bloco altera o card "
            "operacional de granizo."
        ),
    }
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/geo+json,application/json",
    }
 
    def iso_z(dt):
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
 
    def extrair_features(obj):
        feats = obj.get("features", []) if isinstance(obj, dict) else []
        return feats if isinstance(feats, list) else []
 
    def eh_data_alerta(feature):
        if not isinstance(feature, dict):
            return False
        props = feature.get("properties")
        if not isinstance(props, dict):
            return False
        data_id = props.get("data_id")
        return (
            isinstance(data_id, str)
            and "/metadata/" not in data_id.lower()
            and "alerts/" in data_id.lower()
        )
 
    def links_xml(feature):
        saida = []
        if not isinstance(feature, dict):
            return saida
        links = feature.get("links")
        if not isinstance(links, list):
            return saida
        for link in links:
            if not isinstance(link, dict):
                continue
            href = link.get("href")
            tipo = str(link.get("type") or "").lower()
            if (
                isinstance(href, str)
                and href.startswith("https://")
                and (href.lower().endswith(".xml") or "xml" in tipo)
            ):
                saida.append({
                    "href": href,
                    "rel": link.get("rel"),
                    "type": link.get("type"),
                })
        return saida
 
    def momento_feature(feature):
        props = feature.get("properties") if isinstance(feature, dict) else {}
        if not isinstance(props, dict):
            return None
        for chave in ("pubtime", "datetime", "pubTime"):
            valor = props.get(chave)
            if not isinstance(valor, str) or not valor.strip():
                continue
            try:
                texto = valor.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(texto)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except Exception:
                pass
        return None
 
    encontrados = {}
 
    # OGC API Features define o parametro datetime. Testamos janelas
    # progressivas para evitar depender da ordem padrao da colecao.
    for dias in (2, 7, 30, 90):
        inicio = agora_utc - timedelta(days=dias)
        params = {
            "f": "json",
            "metadata_id": metadata_alvo,
            "datetime": iso_z(inicio) + "/" + iso_z(agora_utc),
            "limit": 100,
        }
        teste = {
            "dias": dias,
            "datetime": params["datetime"],
            "http_status": None,
            "quantidade_features": 0,
            "quantidade_data_alerta": 0,
            "numberMatched": None,
            "erro": None,
        }
        try:
            r = requests.get(endpoint, params=params, timeout=(10, 25), headers=headers)
            teste["http_status"] = r.status_code
            if r.ok:
                obj = r.json()
                teste["numberMatched"] = obj.get("numberMatched") if isinstance(obj, dict) else None
                feats = extrair_features(obj)
                teste["quantidade_features"] = len(feats)
                dados = [f for f in feats if eh_data_alerta(f)]
                teste["quantidade_data_alerta"] = len(dados)
                for f in dados:
                    props = f.get("properties") or {}
                    chave = str(f.get("id") or props.get("data_id") or "")
                    if chave:
                        encontrados[chave] = f
            else:
                teste["erro"] = r.text[:300]
        except Exception as e:
            teste["erro"] = str(e)[:500]
        resultado["consultas_temporais"].append(teste)
 
    # Teste documental das extensoes de ordenacao. Se o servidor nao as
    # suportar, o erro fica registrado e as janelas datetime continuam sendo
    # a estrategia principal.
    for campo in ("-datetime", "-pubtime"):
        teste = {
            "sortby": campo,
            "http_status": None,
            "quantidade_features": 0,
            "primeiro_momento": None,
            "erro": None,
        }
        try:
            r = requests.get(
                endpoint,
                params={
                    "f": "json",
                    "metadata_id": metadata_alvo,
                    "sortby": campo,
                    "limit": 20,
                },
                timeout=(10, 25),
                headers=headers,
            )
            teste["http_status"] = r.status_code
            if r.ok:
                obj = r.json()
                feats = [f for f in extrair_features(obj) if eh_data_alerta(f)]
                teste["quantidade_features"] = len(feats)
                if feats:
                    m = momento_feature(feats[0])
                    teste["primeiro_momento"] = iso_z(m) if m else None
                for f in feats:
                    props = f.get("properties") or {}
                    chave = str(f.get("id") or props.get("data_id") or "")
                    if chave:
                        encontrados[chave] = f
            else:
                teste["erro"] = r.text[:300]
        except Exception as e:
            teste["erro"] = str(e)[:500]
        resultado["consultas_ordenacao"].append(teste)
 
    itens = []
    for feature in encontrados.values():
        props = feature.get("properties") or {}
        momento = momento_feature(feature)
        xmls = links_xml(feature)
        itens.append({
            "id": feature.get("id"),
            "data_id": props.get("data_id"),
            "metadata_id": props.get("metadata_id"),
            "datetime": props.get("datetime"),
            "pubtime": props.get("pubtime"),
            "momento_normalizado_utc": iso_z(momento) if momento else None,
            "links_xml": xmls,
            "_momento": momento,
        })
 
    itens.sort(
        key=lambda x: x.get("_momento") or datetime(1970, 1, 1, tzinfo=UTC),
        reverse=True,
    )
 
    for item in itens[:30]:
        limpo = dict(item)
        limpo.pop("_momento", None)
        resultado["mensagens_data_recentes"].append(limpo)
        for link in item.get("links_xml", []):
            href = link.get("href")
            if href and href not in [x.get("href") for x in resultado["links_xml_recentes"]]:
                resultado["links_xml_recentes"].append({
                    **link,
                    "data_id": item.get("data_id"),
                    "momento_normalizado_utc": item.get("momento_normalizado_utc"),
                })
 
    # Testa somente os cinco XMLs mais recentes encontrados. O objetivo aqui
    # e provar disponibilidade atual, nao interpretar risco.
    for link in resultado["links_xml_recentes"][:5]:
        teste = {
            "href": link.get("href"),
            "data_id": link.get("data_id"),
            "momento_normalizado_utc": link.get("momento_normalizado_utc"),
            "http_status": None,
            "content_type": None,
            "parece_xml_cap": False,
            "erro": None,
        }
        try:
            r = requests.get(
                link["href"],
                timeout=(10, 25),
                headers={
                    "User-Agent": "Monitor-Guaxanduva/1.0",
                    "Accept": "application/xml,text/xml,*/*",
                },
            )
            teste["http_status"] = r.status_code
            teste["content_type"] = r.headers.get("Content-Type")
            if r.status_code == 200:
                inicio = r.content[:1000].lower()
                teste["parece_xml_cap"] = b"<alert" in inicio or b":alert" in inicio
                if teste["parece_xml_cap"]:
                    resultado["xml_recente_disponivel"] = True
            else:
                teste["erro"] = r.text[:300]
        except Exception as e:
            teste["erro"] = str(e)[:500]
        resultado["xmls_testados"].append(teste)
 
    if resultado["xml_recente_disponivel"]:
        resultado["status"] = "cap_recente_xml_disponivel"
        resultado["observacao"] = (
            "Foi localizado ao menos um recurso XML recente disponivel no "
            "WIS2/INMET. A proxima etapa pode decodificar CAP e validar area, "
            "vigencia e mencao explicita a granizo, ainda sem inferencias."
        )
    elif resultado["mensagens_data_recentes"]:
        resultado["status"] = "cap_recente_localizado_xml_indisponivel"
        resultado["observacao"] = (
            "Mensagens DATA recentes foram localizadas, mas os XMLs testados "
            "nao estavam disponiveis. Isso nao significa ausencia de alerta."
        )
    elif any(x.get("http_status") == 200 for x in resultado["consultas_temporais"]):
        resultado["status"] = "consultas_temporais_online_sem_cap_data_na_janela"
        resultado["observacao"] = (
            "O servidor respondeu as consultas temporais, mas nenhuma mensagem "
            "DATA de alerta foi localizada nas janelas testadas. Isso nao e "
            "convertido em ausencia operacional de alerta."
        )
    else:
        resultado["status"] = "consultas_temporais_indisponiveis"
 
    return resultado
 
 
def diagnosticar_conteudo_cap_inmet_156(diag155=None):
    """#156 - Decodifica CAPs recentes e testa vigencia/area/granizo, sem uso operacional."""
    import xml.etree.ElementTree as ET
 
    resultado = {
        "status": "indisponivel",
        "versao": "#156",
        "fonte": "WIS2 Node oficial do INMET / CAP XML recente",
        "xmls_analisados": 0,
        "xmls_cap_validos": 0,
        "alertas": [],
        "estrutura_area_confirmada": False,
        "estrutura_geocode_confirmada": False,
        "estrutura_polygon_confirmada": False,
        "mencao_granizo_em_algum_cap": False,
        "joinville_identificada_em_algum_cap": False,
        "cap_vigente_em_algum_cap": False,
        "candidato_granizo_joinville_vigente": False,
        "uso_operacional_granizo": False,
        "regra_seguranca": (
            "Diagnostico estrutural dos CAPs recentes. Somente mencao explicita "
            "a granizo/hail, vigencia temporal e cobertura documental de Joinville "
            "sao registradas. O bloco nao altera o card operacional de granizo."
        ),
    }
 
    if not isinstance(diag155, dict):
        diag155 = diagnosticar_cap_recente_inmet_155()
 
    links = diag155.get("links_xml_recentes", [])
    if not isinstance(links, list) or not links:
        resultado["status"] = "sem_xml_recente_da_155"
        return resultado
 
    headers = {
        "User-Agent": "Monitor-Guaxanduva/1.0",
        "Accept": "application/xml,text/xml,*/*",
    }
 
    def local(tag):
        if not isinstance(tag, str):
            return tag
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag
 
    def filhos(elem, nome):
        return [x for x in list(elem) if local(x.tag) == nome]
 
    def descendentes(elem, nome):
        return [x for x in elem.iter() if local(x.tag) == nome]
 
    def texto_direto(elem, nome):
        for x in filhos(elem, nome):
            t = (x.text or "").strip()
            if t:
                return t
        return None
 
    def textos_diretos(elem, nome):
        saida = []
        for x in filhos(elem, nome):
            t = (x.text or "").strip()
            if t:
                saida.append(t)
        return saida
 
    def parse_dt(valor):
        if not isinstance(valor, str) or not valor.strip():
            return None
        try:
            dt = datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return None
 
    def ponto_no_poligono(lat, lon, texto):
        try:
            pontos = []
            for par in str(texto).replace(";", " ").split():
                a, b = par.split(",", 1)
                pontos.append((float(b), float(a)))  # x=lon, y=lat
            if len(pontos) < 3:
                return False
            x, y = float(lon), float(lat)
            dentro = False
            j = len(pontos) - 1
            for i in range(len(pontos)):
                xi, yi = pontos[i]
                xj, yj = pontos[j]
                cruza = ((yi > y) != (yj > y))
                if cruza:
                    x_inter = (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
                    if x < x_inter:
                        dentro = not dentro
                j = i
            return dentro
        except Exception:
            return False
 
    def area_joinville(area):
        area_desc = str(area.get("areaDesc") or "")
        if "joinville" in area_desc.lower():
            return True, "areaDesc"
 
        for geo in area.get("geocodes", []):
            nome = str(geo.get("valueName") or "").lower()
            valor = str(geo.get("value") or "").strip()
            somente_digitos = re.sub(r"\\D", "", valor)
            if valor == IBGE_JOINVILLE or somente_digitos == IBGE_JOINVILLE:
                return True, "geocode_ibge_4209102"
            if "joinville" in valor.lower():
                return True, "geocode_textual"
            if "ibge" in nome and somente_digitos == IBGE_JOINVILLE:
                return True, "geocode_ibge_4209102"
 
        for pol in area.get("polygons", []):
            if ponto_no_poligono(LAT, LON, pol):
                return True, "polygon_contem_coordenada_publica_comasa"
 
        return False, None
 
    agora_utc = datetime.now(UTC)
 
    for cand in links[:5]:
        href = cand.get("href") if isinstance(cand, dict) else None
        if not isinstance(href, str) or not href.startswith("https://"):
            continue
 
        resultado["xmls_analisados"] += 1
        alerta = {
            "data_id": cand.get("data_id"),
            "url": href,
            "http_status": None,
            "raiz": None,
            "identifier": None,
            "sender": None,
            "sent": None,
            "status_cap": None,
            "msgType": None,
            "scope": None,
            "infos": [],
            "menciona_granizo_ou_hail": False,
            "joinville_identificada": False,
            "metodo_identificacao_joinville": [],
            "vigente_agora": False,
            "candidato_granizo_joinville_vigente": False,
            "erro": None,
        }
 
        try:
            r = requests.get(href, timeout=(10, 25), headers=headers)
            alerta["http_status"] = r.status_code
            if r.status_code != 200:
                alerta["erro"] = r.text[:300]
                resultado["alertas"].append(alerta)
                continue
 
            raiz = ET.fromstring(r.content)
            alerta["raiz"] = local(raiz.tag)
            if alerta["raiz"] != "alert":
                alerta["erro"] = "raiz_xml_nao_e_alert"
                resultado["alertas"].append(alerta)
                continue
 
            resultado["xmls_cap_validos"] += 1
            alerta["identifier"] = texto_direto(raiz, "identifier")
            alerta["sender"] = texto_direto(raiz, "sender")
            alerta["sent"] = texto_direto(raiz, "sent")
            alerta["status_cap"] = texto_direto(raiz, "status")
            alerta["msgType"] = texto_direto(raiz, "msgType")
            alerta["scope"] = texto_direto(raiz, "scope")
 
            busca_alerta = []
            metodos_joinville = set()
            algum_info_vigente = False
 
            for info in filhos(raiz, "info"):
                areas = []
                info_joinville = False
                info_metodos = set()
 
                for area_el in filhos(info, "area"):
                    geocodes = []
                    for geo in filhos(area_el, "geocode"):
                        geocodes.append({
                            "valueName": texto_direto(geo, "valueName"),
                            "value": texto_direto(geo, "value"),
                        })
                    polygons = textos_diretos(area_el, "polygon")
                    area = {
                        "areaDesc": texto_direto(area_el, "areaDesc"),
                        "geocodes": geocodes,
                        "polygons": polygons,
                    }
                    if area["areaDesc"] or geocodes or polygons:
                        resultado["estrutura_area_confirmada"] = True
                    if geocodes:
                        resultado["estrutura_geocode_confirmada"] = True
                    if polygons:
                        resultado["estrutura_polygon_confirmada"] = True
 
                    cobre, metodo = area_joinville(area)
                    if cobre:
                        info_joinville = True
                        info_metodos.add(metodo)
                        metodos_joinville.add(metodo)
                    areas.append(area)
 
                inicio_txt = (
                    texto_direto(info, "onset")
                    or texto_direto(info, "effective")
                    or alerta.get("sent")
                )
                fim_txt = texto_direto(info, "expires")
                inicio = parse_dt(inicio_txt)
                fim = parse_dt(fim_txt)
                vigente = bool(
                    inicio is not None
                    and fim is not None
                    and inicio <= agora_utc <= fim
                )
                if vigente:
                    algum_info_vigente = True
 
                item = {
                    "language": texto_direto(info, "language"),
                    "category": textos_diretos(info, "category"),
                    "event": texto_direto(info, "event"),
                    "urgency": texto_direto(info, "urgency"),
                    "severity": texto_direto(info, "severity"),
                    "certainty": texto_direto(info, "certainty"),
                    "effective": texto_direto(info, "effective"),
                    "onset": texto_direto(info, "onset"),
                    "expires": texto_direto(info, "expires"),
                    "headline": texto_direto(info, "headline"),
                    "description": texto_direto(info, "description"),
                    "instruction": texto_direto(info, "instruction"),
                    "areas": areas,
                    "joinville_identificada": info_joinville,
                    "metodos_identificacao_joinville": sorted(info_metodos),
                    "vigente_agora": vigente,
                }
                alerta["infos"].append(item)
 
                for chave in ("event", "headline", "description", "instruction"):
                    if isinstance(item.get(chave), str):
                        busca_alerta.append(item[chave])
 
            total = " ".join(busca_alerta).lower()
            alerta["menciona_granizo_ou_hail"] = (
                "granizo" in total or re.search(r"\bhail\b", total) is not None
            )
            alerta["joinville_identificada"] = bool(metodos_joinville)
            alerta["metodo_identificacao_joinville"] = sorted(metodos_joinville)
            alerta["vigente_agora"] = algum_info_vigente
 
            # Exige as tres provas simultaneamente no mesmo CAP. O bloco
            # permanece diagnostico; nao publica o resultado no card.
            alerta["candidato_granizo_joinville_vigente"] = bool(
                alerta["menciona_granizo_ou_hail"]
                and alerta["joinville_identificada"]
                and alerta["vigente_agora"]
                and str(alerta.get("status_cap") or "").lower() == "actual"
                and str(alerta.get("scope") or "").lower() == "public"
                and str(alerta.get("msgType") or "").lower() not in {"cancel", "error"}
            )
 
            if alerta["menciona_granizo_ou_hail"]:
                resultado["mencao_granizo_em_algum_cap"] = True
            if alerta["joinville_identificada"]:
                resultado["joinville_identificada_em_algum_cap"] = True
            if alerta["vigente_agora"]:
                resultado["cap_vigente_em_algum_cap"] = True
            if alerta["candidato_granizo_joinville_vigente"]:
                resultado["candidato_granizo_joinville_vigente"] = True
 
        except Exception as e:
            alerta["erro"] = str(e)[:500]
 
        resultado["alertas"].append(alerta)
 
    if resultado["xmls_cap_validos"]:
        resultado["status"] = "cap_recente_decodificado"
        resultado["observacao"] = (
            "CAPs recentes foram parseados e os campos de fenomeno, vigencia "
            "e area foram registrados. Mesmo um candidato que cumpra os testes "
            "permanece diagnostico nesta versao; o card operacional nao muda."
        )
    elif resultado["xmls_analisados"]:
        resultado["status"] = "xml_recente_sem_cap_valido_parseado"
    else:
        resultado["status"] = "sem_xml_recente_analisavel"
 
    return resultado
 
 
 
 
def granizo_operacional_inmet_157(diag156=None):
    """#157 - Publica somente alerta positivo de granizo validado pelo CAP INMET.
 
    Regra conservadora: um candidato ativo precisa reunir, no mesmo CAP,
    menção explícita a granizo/hail, cobertura da referência pública de
    Joinville/Comasa, vigência temporal, status Actual, scope Public e
    msgType diferente de Cancel/Error. Ausência entre os cinco CAPs
    inspecionados pela #156 NÃO é convertida em "sem alerta".
    """
    resultado = {
        "status": "indisponivel",
        "versao": "#157",
        "fonte": "INMET / WIS2 / CAP",
        "tipo": "aviso_meteorologico_oficial_granizo",
        "ativo": None,
        "alerta": None,
        "cobertura_referencia_publica_comasa": None,
        "uso_operacional_granizo": True,
        "regra_seguranca": (
            "Somente alerta positivo comprovado e publicado. Ausencia de candidato "
            "na amostra da #156, falha de fonte ou XML indisponivel permanece "
            "inconclusiva e nunca vira automaticamente 'sem alerta'."
        ),
        "observacao": (
            "Aviso oficial indica possibilidade de granizo na area e no periodo; "
            "nao significa granizo observado ou caindo no Comasa."
        ),
    }
 
    if not isinstance(diag156, dict):
        resultado["status"] = "indisponivel_sem_diagnostico_156"
        return resultado
 
    if diag156.get("status") != "cap_recente_decodificado":
        resultado["status"] = "indisponivel_cap_recente_nao_decodificado"
        return resultado
 
    alertas = diag156.get("alertas")
    if not isinstance(alertas, list):
        resultado["status"] = "indisponivel_lista_alertas_invalida"
        return resultado
 
    candidatos = []
    for alerta in alertas:
        if not isinstance(alerta, dict):
            continue
        if not alerta.get("candidato_granizo_joinville_vigente"):
            continue
        if str(alerta.get("status_cap") or "").lower() != "actual":
            continue
        if str(alerta.get("scope") or "").lower() != "public":
            continue
        if str(alerta.get("msgType") or "").lower() in {"cancel", "error"}:
            continue
 
        infos_validas = []
        for info in alerta.get("infos") or []:
            if not isinstance(info, dict):
                continue
            if not info.get("vigente_agora") or not info.get("joinville_identificada"):
                continue
            texto = " ".join(
                str(info.get(k) or "")
                for k in ("event", "headline", "description", "instruction")
            ).lower()
            if "granizo" not in texto and re.search(r"\bhail\b", texto) is None:
                continue
            infos_validas.append(info)
 
        if infos_validas:
            candidatos.append((alerta, infos_validas))
 
    if not candidatos:
        resultado["status"] = "online_sem_conclusao_negativa"
        resultado["ativo"] = None
        resultado["cobertura_referencia_publica_comasa"] = None
        resultado["observacao"] = (
            "Os CAPs inspecionados foram decodificados, mas a #156 avalia apenas "
            "uma amostra recente. Portanto, ausencia de candidato positivo nao "
            "autoriza publicar 'sem alerta de granizo'."
        )
        return resultado
 
    # Havendo mais de um candidato, prioriza o CAP enviado mais recentemente.
    def momento_enviado(item):
        alerta = item[0]
        try:
            dt = datetime.fromisoformat(str(alerta.get("sent") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            return datetime(1970, 1, 1, tzinfo=UTC)
 
    alerta, infos = sorted(candidatos, key=momento_enviado, reverse=True)[0]
    info = infos[0]
 
    resultado["status"] = "alerta_ativo_confirmado"
    resultado["ativo"] = True
    resultado["cobertura_referencia_publica_comasa"] = True
    resultado["alerta"] = {
        "data_id": alerta.get("data_id"),
        "identifier": alerta.get("identifier"),
        "sender": alerta.get("sender"),
        "sent": alerta.get("sent"),
        "status_cap": alerta.get("status_cap"),
        "msgType": alerta.get("msgType"),
        "scope": alerta.get("scope"),
        "event": info.get("event"),
        "urgency": info.get("urgency"),
        "severity": info.get("severity"),
        "certainty": info.get("certainty"),
        "onset": info.get("onset"),
        "expires": info.get("expires"),
        "headline": info.get("headline"),
        "description": info.get("description"),
        "instruction": info.get("instruction"),
        "metodos_identificacao_joinville": info.get("metodos_identificacao_joinville") or [],
        "url_xml": alerta.get("url"),
    }
    return resultado
 
# =========================================================
# #163 - CRITERIO HIDROMETEOROLOGICO CALCULADO • PLANCON
# Diagnostico independente do acionamento oficial da Defesa Civil.
# Usa a previsao movel #162 e a mare observada EPAGRI/CIRAM #160.
# =========================================================
 
def calcular_criterio_hidrometeorologico_plancon_163(previsao, mare_observada):
    resultado = {
        "status": "inconclusivo", "versao": "#163",
        "tipo": "correspondencia_criterios_hidrologicos_plancon",
        "fonte_normativa": "PMGRD/PLANCON Joinville 2026 - Quadro 4.4.2-1 (riscos de desastres hidrologicos)",
        "classificacao_calculada": "inconclusivo",
        "plancon_oficial": False, "uso_como_plancon_oficial": False,
        "entradas": {"chuva_prevista_24h_mm": None, "chuva_24h_integra": False, "mare_observada_m": None, "mare_observada_fresca": False, "mare_fonte": "EPAGRI/CIRAM"},
        "criterios": {"mobilizacao_chuva_superior_20mm_24h": None, "mobilizacao_ocorrencia_confirmada": None, "atencao_chuva_superior_50mm_e_mare_desde_1_5m": None, "alerta_chuva_superior_50mm_e_mare_desde_1_8m": None, "alerta_chuva_superior_80mm_e_mare_desde_1_5m": None, "crise": None},
        "limitacoes": [
            "Mobilizacao no Quadro 4.4.2-1 tambem exige a deflagracao de uma ou mais ocorrencias; o Monitor nao infere essa condicao.",
            "A mare usada neste diagnostico e a observada atual da EPAGRI/CIRAM. Ela nao representa automaticamente o pico de mare de toda a janela futura de 24h.",
            "Crise nao e calculada: o PLANCON a relaciona a extrapolacao dos recursos existentes/disponiveis na Prefeitura para resposta.",
        ],
        "observacao": "Resultado tecnico do Monitor Guaxanduva. Nao declara mudanca de estagio do PLANCON nem substitui comunicacao oficial da Defesa Civil.",
    }
    p24 = (previsao or {}).get("proximas_24h") or {}
    chuva = p24.get("precipitacao_acumulada_mm")
    chuva_integra = (p24.get("status") == "online_completo" and p24.get("integridade") is True and p24.get("horas_validas") == 24 and isinstance(chuva, (int, float)) and not isinstance(chuva, bool) and chuva >= 0)
    mare = (mare_observada or {}).get("nivel_m")
    mare_fresca = ((mare_observada or {}).get("status") == "observado_disponivel" and (mare_observada or {}).get("frescor") == "atual" and isinstance(mare, (int, float)) and not isinstance(mare, bool) and mare >= 0)
    resultado["entradas"].update({"chuva_prevista_24h_mm": chuva if chuva_integra else None, "chuva_24h_integra": chuva_integra, "mare_observada_m": mare if mare_fresca else None, "mare_observada_fresca": mare_fresca, "janela_inicio": p24.get("inicio"), "janela_fim_exclusivo": p24.get("fim_exclusivo"), "mare_horario": (mare_observada or {}).get("horario"), "mare_idade_min": (mare_observada or {}).get("idade_min")})
    if not chuva_integra or not mare_fresca:
        faltantes = []
        if not chuva_integra: faltantes.append("previsao_24h_integra")
        if not mare_fresca: faltantes.append("mare_observada_epagri_fresca")
        resultado["dados_faltantes"] = faltantes
        return resultado
    mobilizacao_chuva = chuva > 20.0
    atencao = chuva > 50.0 and mare >= 1.5
    alerta_50_18 = chuva > 50.0 and mare >= 1.8
    alerta_80_15 = chuva > 80.0 and mare >= 1.5
    alerta = alerta_50_18 or alerta_80_15
    resultado["criterios"].update({"mobilizacao_chuva_superior_20mm_24h": mobilizacao_chuva, "mobilizacao_ocorrencia_confirmada": None, "atencao_chuva_superior_50mm_e_mare_desde_1_5m": atencao, "alerta_chuva_superior_50mm_e_mare_desde_1_8m": alerta_50_18, "alerta_chuva_superior_80mm_e_mare_desde_1_5m": alerta_80_15, "crise": None})
    resultado["status"] = "calculado"
    if alerta: resultado["classificacao_calculada"] = "alerta"
    elif atencao: resultado["classificacao_calculada"] = "atencao"
    elif mobilizacao_chuva: resultado["classificacao_calculada"] = "sinal_pluviometrico_mobilizacao"
    else: resultado["classificacao_calculada"] = "sem_gatilho_superior_identificado"
    return resultado
 
 
# =========================================================
# #164 - PICO DE MARE PREVISTO • PROXIMAS 24 HORAS
# Mesma janela temporal da #162; fonte EPAGRI/CIRAM.
# Diagnostico independente: nao altera os gatilhos da #163.
# =========================================================
 
def calcular_pico_mare_previsto_24h_164(previsao):
    resultado = {
        "status": "inconclusivo", "versao": "#164", "fonte": "EPAGRI/CIRAM",
        "tipo": "pico_mare_previsto_janela_24h", "janela_inicio": None,
        "janela_fim_exclusivo": None, "datas_cobertas_fonte": [],
        "eventos_na_janela": [], "quantidade_eventos": 0,
        "pico_previsto_m": None, "pico_previsto_horario": None,
        "integridade": False, "uso_no_risco": False,
        "observacao": "Diagnostico #164: maior extremo de mare previsto pela EPAGRI/CIRAM dentro da mesma janela movel de 24 horas da #162. Nao altera a classificacao #163 nesta etapa.",
    }
    p24 = (previsao or {}).get("proximas_24h") or {}
    inicio_txt, fim_txt = p24.get("inicio"), p24.get("fim_exclusivo")
    resultado["janela_inicio"], resultado["janela_fim_exclusivo"] = inicio_txt, fim_txt
    janela_integra = (p24.get("status") == "online_completo" and p24.get("integridade") is True and p24.get("horas_validas") == 24 and inicio_txt and fim_txt)
    if not janela_integra:
        resultado["status"] = "inconclusivo_janela_162_invalida"
        resultado["observacao"] = "A janela #162 nao esta completa/valida; a #164 nao infere pico de mare sem a janela temporal de referencia."
        return resultado
    try:
        inicio, fim = datetime.fromisoformat(str(inicio_txt)), datetime.fromisoformat(str(fim_txt))
        inicio = inicio.replace(tzinfo=FUSO) if inicio.tzinfo is None else inicio.astimezone(FUSO)
        fim = fim.replace(tzinfo=FUSO) if fim.tzinfo is None else fim.astimezone(FUSO)
        if fim <= inicio: raise ValueError("fim da janela nao e posterior ao inicio")
    except Exception as e:
        resultado["status"], resultado["erro"] = "inconclusivo_janela_162_nao_parseavel", str(e)
        return resultado
    try:
        resposta = get(MARE); resposta.encoding = "ISO-8859-1"
        eventos_validos, datas_fonte = [], set()
        for linha in resposta.text.splitlines():
            partes = linha.strip().split(";")
            if len(partes) != 3: continue
            try:
                momento = datetime.strptime(partes[0].strip()+" "+partes[1].strip(), "%d/%m/%Y %H:%M").replace(tzinfo=FUSO)
                altura = float(partes[2].strip().replace(",", "."))
                if not math.isfinite(altura) or altura < 0: continue
            except Exception:
                continue
            datas_fonte.add(momento.date())
            if inicio <= momento < fim:
                eventos_validos.append({"horario": momento.isoformat(), "altura_m": round(altura, 3)})
        eventos_validos.sort(key=lambda x: x["horario"])
        resultado["eventos_na_janela"] = eventos_validos
        resultado["quantidade_eventos"] = len(eventos_validos)
        resultado["datas_cobertas_fonte"] = sorted(data.isoformat() for data in datas_fonte)
        datas_necessarias = {inicio.date(), (fim - timedelta(microseconds=1)).date()}
        if not datas_necessarias.issubset(datas_fonte):
            resultado["status"] = "inconclusivo_cobertura_datas_incompleta"
            resultado["observacao"] = "A tabua EPAGRI/CIRAM nao apresentou eventos validos para todas as datas civis atravessadas pela janela #162. A #164 nao infere pico com cobertura temporal incompleta."
            return resultado
        if not eventos_validos:
            resultado["status"] = "inconclusivo_sem_eventos_na_janela"
            resultado["observacao"] = "A fonte cobre as datas da janela, mas nenhum extremo de mare valido caiu dentro do intervalo. Ausencia de evento nao e interpretada como mare zero."
            return resultado
        pico = max(eventos_validos, key=lambda x: x["altura_m"])
        resultado.update({"pico_previsto_m": pico["altura_m"], "pico_previsto_horario": pico["horario"], "integridade": True, "status": "online_completo"})
        return resultado
    except Exception as e:
        resultado["status"], resultado["erro"] = "indisponivel_fonte_mare", str(e)
        resultado["observacao"] = "Falha ao obter ou interpretar a tabua de mare EPAGRI/CIRAM. A #164 permanece inconclusiva e nao substitui ausencia por zero."
        return resultado
 
# =========================================================
# #165 - EPAGRI/CIRAM • AGROCONNECT • PRECIPITACAO HORARIA
# Variavel 271 = Precipitacao Total (mm), produto horario, grupo 4, nhoras 1.
# Cada estacao permanece independente; falha/nulo nunca vira 0.
# =========================================================
EPAGRI_AGROCONNECT = "https://ciram.epagri.sc.gov.br/agroconnect/"
EPAGRI_AGROCONNECT_BUSCA = EPAGRI_AGROCONNECT + "busca.jsp"
EPAGRI_CHAVE_FIXA = "1A853d23"
EPAGRI_LPTYA = "CbkYTPgEQbNLja"
EPAGRI_ESTACOES_CHUVA = [(2382, "Joinville - Pirabeiraba"), (1051, "Joinville - Vila Nova")]
 
def _epagri_keyy_165(timestamp_ms):
    return str(timestamp_ms)[:-5]
 
def _epagri_marcador_165(keyy):
    partes=[]; pos=0
    for i in range(0,len(EPAGRI_LPTYA),2):
        if pos>=len(keyy): raise ValueError("keyy EPAGRI curto demais")
        partes.extend((keyy[pos],EPAGRI_LPTYA[i:i+2])); pos+=1
    partes.append(str(pos)); return "".join(partes)
 
def _epagri_ack3uk_165(texto,keyy):
    marcador=_epagri_marcador_165(keyy); indice=texto.find(marcador)
    if indice<0: raise ValueError("marcador EPAGRI prrtyc nao encontrado")
    chars=list(base64.b64decode(texto[:indice]).decode("utf-8")); chave=EPAGRI_CHAVE_FIXA+keyy; n=len(chars); k=0
    for i in range(math.trunc(n/2)):
        if k>=len(chave): k=0
        esquerda=ord(chars[i]); direita=ord(chars[n-1-i]); ck=ord(chave[k])
        chars[i]=chr(direita^ck); chars[n-1-i]=chr(esquerda^ck); k+=1
    return "".join(chars)
 
def _epagri_date_165(data_dd_mm_aaaa,estacao):
    dia,mes,ano=[int(x) for x in data_dd_mm_aaaa.split("-")]
    return f"{int(ano*(mes*12)*(30*dia))}0"
 
def _epagri_instante_165(texto):
    try: return datetime.strptime(str(texto).strip(),"%d/%m/%Y %H:%M").replace(tzinfo=FUSO)
    except Exception: return None
 
def buscar_chuva_epagri_165():
    resultado={"status":"indisponivel","fonte":"EPAGRI/CIRAM","tipo":"precipitacao_horaria_observada","variavel":271,"produto":"horario","grupo":4,"janela_h":1,"estacoes":[],"regra_seguranca":"Cada leitura pertence a sua propria estacao. Zero retornado no campo de precipitacao e preservado como zero; falha, ausencia ou valor invalido permanece null e nunca e convertido em zero."}
    sessao=requests.Session(); sessao.headers.update({"User-Agent":"Mozilla/5.0 Monitor-Guaxanduva/1.0","Accept":"*/*","Referer":EPAGRI_AGROCONNECT,"Origin":"https://ciram.epagri.sc.gov.br","X-Requested-With":"XMLHttpRequest"})
    filtros=[("0","todas"),("42","todas"),("0","epagri"),("42","epagri"),("0","0"),("42","0")]
    for codigo,nome in EPAGRI_ESTACOES_CHUVA:
        item={"codigo":str(codigo),"nome":nome,"fonte":"EPAGRI/CIRAM","rede":"EPAGRI/CIRAM","latitude":None,"longitude":None,"precipitacao_1h_mm":None,"horario_medicao":None,"idade_leitura_min":None,"dados_frescos":False,"leitura_atual_disponivel":False,"aquisicao_automatica_integrada":True,"status":"indisponivel","equivale_medicao_no_comasa":False}
        ultimo_erro=None
        for estado,tipo_estacao in filtros:
            agora_ms=int(time.time()*1000); keyy=_epagri_keyy_165(agora_ms); hoje=agora().strftime("%d-%m-%Y")
            params=[("cd_estacao",str(codigo)),("cd_cultura","0"),("produto","horario"),("cd_variavel","271"),("grupo","4"),("data",hoje),("nhoras","1"),("estado_",estado),("tipoEstacao_",tipo_estacao),("dt",str(agora_ms)),("date",_epagri_date_165(hoje,codigo)),("idestacao",f"{nome}: {codigo}"),("ka",keyy)]
            try:
                r=sessao.post(EPAGRI_AGROCONNECT_BUSCA,params=params,timeout=30,allow_redirects=True); r.raise_for_status()
                dec=_epagri_ack3uk_165(r.text.replace("\r","").replace("\n",""),keyy)
                candidatos=[]
                for registro in [x.strip() for x in dec.replace("\n","").split(";;") if x.strip()]:
                    campos=[x.strip() for x in registro.split(",")]
                    if len(campos)<7 or campos[0]!=str(codigo): continue
                    try: valor=float(campos[4])
                    except Exception: valor=None
                    candidatos.append((_epagri_instante_165(campos[6]),valor,campos))
                if not candidatos: continue
                candidatos.sort(key=lambda x:x[0] or datetime.min.replace(tzinfo=FUSO)); instante,valor,campos=candidatos[-1]
                idade=max(0.0,(agora()-instante).total_seconds()/60.0) if instante else None
                valido=isinstance(valor,(int,float)) and not isinstance(valor,bool) and math.isfinite(valor) and valor>=0
                item.update({"latitude":float(campos[3]) if campos[3] else None,"longitude":float(campos[2]) if campos[2] else None,"precipitacao_1h_mm":valor if valido else None,"horario_medicao":instante.isoformat() if instante else campos[6],"idade_leitura_min":round(idade,1) if idade is not None else None,"dados_frescos":bool(idade is not None and idade<=120),"leitura_atual_disponivel":valido,"status":"online" if valido and idade is not None and idade<=120 else "online_leitura_atrasada" if valido else "indisponivel"})
                break
            except Exception as exc: ultimo_erro=str(exc)
        if item["status"]=="indisponivel" and ultimo_erro: item["erro"]=ultimo_erro
        resultado["estacoes"].append(item)
    disponiveis=[e for e in resultado["estacoes"] if e.get("leitura_atual_disponivel") is True]; frescas=[e for e in disponiveis if e.get("dados_frescos") is True]
    if len(frescas)==len(EPAGRI_ESTACOES_CHUVA): resultado["status"]="online"
    elif disponiveis: resultado["status"]="parcial_ou_atrasado"
    return resultado
 
def construir_rede_pluviometrica_multifonte_165(chuva_cemaden,chuva_epagri):
    resultado={"status":"inventario_multifonte_com_dados_parciais","versao":"#165","tipo":"rede_pluviometrica_multifonte_joinville","municipio":"Joinville/SC","referencia":"Comasa - coordenada publica aproximada","coordenada_referencia":{"latitude":LAT,"longitude":LON},"estacoes":[],"fontes":[],"quantidade_estacoes":0,"quantidade_com_leitura_atual":0,"quantidade_sem_leitura_automatica_integrada":0,"uso_no_risco":False,"classificacao_risco_automatica":False,"regra_seguranca":"Cada pluviometro representa seu proprio ponto. Leituras de estacoes diferentes nao sao somadas, promediadas nem tratadas como medicao no Comasa. Ausencia, falha ou valor nulo nunca e convertido em 0 mm.","observacao":"CEMADEN e EPAGRI/CIRAM possuem aquisicao automatica integrada. A chuva EPAGRI e horaria e nao e convertida artificialmente em acumulado de 24 horas. ANA/SNIRH e Rede Municipal/Defesa Civil permanecem inventariadas sem telemetria atual integrada."}
    estacoes_cemaden=chuva_cemaden.get("estacoes_joinville_ativas",[]) if isinstance(chuva_cemaden,dict) else []
    if not isinstance(estacoes_cemaden,list): estacoes_cemaden=[]
    for e in estacoes_cemaden:
        if not isinstance(e,dict): continue
        disp=e.get("acumulado_disponivel") is True and isinstance(e.get("acumulado_24h_mm"),(int,float)) and not isinstance(e.get("acumulado_24h_mm"),bool) and e.get("acumulado_24h_mm")>=0
        resultado["estacoes"].append({"nome":e.get("nome"),"fonte":"CEMADEN","rede":"CEMADEN","codigo":e.get("codigo"),"id":e.get("id"),"latitude":e.get("latitude"),"longitude":e.get("longitude"),"distancia_comasa_aprox_km":e.get("distancia_comasa_aprox_km"),"janela_acumulado_h":24,"acumulado_24h_mm":e.get("acumulado_24h_mm") if disp else None,"precipitacao_1h_mm":None,"leitura_atual_disponivel":disp,"aquisicao_automatica_integrada":True,"status":"online" if disp else "indisponivel","equivale_medicao_no_comasa":False})
    for e in (chuva_epagri or {}).get("estacoes",[]):
        if not isinstance(e,dict): continue
        resultado["estacoes"].append({"nome":e.get("nome"),"fonte":"EPAGRI/CIRAM","rede":"EPAGRI/CIRAM","codigo":e.get("codigo"),"latitude":e.get("latitude"),"longitude":e.get("longitude"),"distancia_comasa_aprox_km":None,"janela_acumulado_h":1,"acumulado_24h_mm":None,"precipitacao_1h_mm":e.get("precipitacao_1h_mm"),"horario_medicao":e.get("horario_medicao"),"idade_leitura_min":e.get("idade_leitura_min"),"dados_frescos":e.get("dados_frescos"),"leitura_atual_disponivel":e.get("leitura_atual_disponivel"),"aquisicao_automatica_integrada":True,"status":e.get("status"),"equivale_medicao_no_comasa":False})
    for nome,codigo in [("Joinville/RVPSC","02648014"),("Ponte SC-301","02648028"),("Pirabeiraba","02648033"),("Estrada dos Morros","02648034"),("Primeiro Salto do Cubatao","02649060")]:
        resultado["estacoes"].append({"nome":nome,"fonte":"ANA/SNIRH - inventario historico citado no PMGRD Joinville 2026","rede":"ANA/SNIRH","codigo":codigo,"latitude":None,"longitude":None,"distancia_comasa_aprox_km":None,"janela_acumulado_h":None,"acumulado_24h_mm":None,"precipitacao_1h_mm":None,"leitura_atual_disponivel":False,"aquisicao_automatica_integrada":False,"status":"estacao_identificada_sem_telemetria_atual_integrada","equivale_medicao_no_comasa":False})
    resultado["fontes"]=[{"fonte":"CEMADEN","status_integracao":"automatica_integrada","endpoint":CEMADEN_PLUV_24H},{"fonte":"EPAGRI/CIRAM","status_integracao":"automatica_integrada_agroconnect","endpoint":EPAGRI_AGROCONNECT_BUSCA},{"fonte":"ANA/SNIRH","status_integracao":"inventario_historico_identificado_sem_telemetria_atual_integrada","endpoint":None},{"fonte":"Prefeitura de Joinville / Defesa Civil","status_integracao":"rede_identificada_sem_endpoint_publico_automatico_validado","endpoint":None}]
    resultado["quantidade_estacoes"]=len(resultado["estacoes"]); resultado["quantidade_com_leitura_atual"]=sum(1 for e in resultado["estacoes"] if e.get("leitura_atual_disponivel") is True); resultado["quantidade_sem_leitura_automatica_integrada"]=sum(1 for e in resultado["estacoes"] if e.get("aquisicao_automatica_integrada") is not True)
    if resultado["quantidade_com_leitura_atual"]==0: resultado["status"]="inventario_multifonte_sem_dados_automaticos_disponiveis"
    return resultado
 
# =========================================================
# GUAXANDUVA-MODEL V0.1 - GRAFO HIDROGRAFICO COMPUTACIONAL
# =========================================================
# Integra a hidrografia oficial do SIMGeo ao PY principal sem substituir
# nenhuma das camadas existentes. O grafo e inicialmente nao direcionado:
# a ordem dos vertices de uma LineString nao prova o sentido hidraulico.
# O ponto de referencia e publico/tecnico e nao identifica residencia.
 
SIMGeo_GUAXANDUVA_LAYER_44 = (
    "https://geo.joinville.sc.gov.br/server/rest/services/SEPUR/"
    "meio_ambiente_simgeo_v4_/MapServer/44/query"
)
GUAXANDUVA_MICROBACIA = "44-0"
GUAXANDUVA_SEGMENTO_REFERENCIA = 30960
GUAXANDUVA_PONTO_REFERENCIA = (-48.809508420794316, -26.270596021167542)
GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M = 1.0
GUAXANDUVA_GRAFO_ARQUIVO = "grafo_guaxanduva.json"
GUAXANDUVA_MODELO_VERSAO = "GXA-V0.8-CONTROLE-HIDRAULICO-BUEIRO"
 
 
def _gxa_haversine_m(a, b):
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(h)))
 
 
def _gxa_xy_local(p, lat_ref):
    lon, lat = p
    x = math.radians(lon) * 6371008.8 * math.cos(math.radians(lat_ref))
    y = math.radians(lat) * 6371008.8
    return x, y
 
 
def _gxa_distancia_ponto_segmento_m(p, a, b):
    lat_ref = (p[1] + a[1] + b[1]) / 3.0
    px, py = _gxa_xy_local(p, lat_ref)
    ax, ay = _gxa_xy_local(a, lat_ref)
    bx, by = _gxa_xy_local(b, lat_ref)
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    vv = vx * vx + vy * vy
    if vv == 0:
        return math.hypot(px - ax, py - ay), a
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    qx, qy = ax + t * vx, ay + t * vy
    d = math.hypot(px - qx, py - qy)
    lon_q = math.degrees(qx / (6371008.8 * math.cos(math.radians(lat_ref))))
    lat_q = math.degrees(qy / 6371008.8)
    return d, (lon_q, lat_q)
 
 
def _gxa_distancia_ponto_linha_m(p, coords):
    melhor = (float("inf"), None, None)
    for i in range(len(coords) - 1):
        d, q = _gxa_distancia_ponto_segmento_m(p, coords[i], coords[i + 1])
        if d < melhor[0]:
            melhor = (d, q, i)
    return melhor
 
 
def _gxa_normalizar_feature(feature):
    geom = feature.get("geometry") or {}
    props = feature.get("properties") or {}
    if geom.get("type") != "LineString":
        return None
    coords = geom.get("coordinates") or []
    if len(coords) < 2:
        return None
    try:
        coords = [(float(p[0]), float(p[1])) for p in coords]
    except Exception:
        return None
    oid = props.get("objectid", feature.get("id"))
    try:
        oid = int(oid)
    except Exception:
        return None
    comprimento = props.get("st_length(shape)")
    try:
        comprimento = float(comprimento) if comprimento is not None else None
    except Exception:
        comprimento = None
    return {
        "objectid": oid,
        "nome_rio": props.get("nome_rio"),
        "tipo": props.get("nova_class"),
        "auc": props.get("auc"),
        "contribuicao": props.get("contribuic"),
        "drenagem": props.get("drenagem"),
        "microbacia": props.get("num_microb"),
        "comprimento_m": comprimento,
        "geometria": [[p[0], p[1]] for p in coords],
        "_coords": coords,
    }
 
 
def _gxa_baixar_geojson():
    params = {
        "where": f"num_microb='{GUAXANDUVA_MICROBACIA}'",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    resposta = get(SIMGeo_GUAXANDUVA_LAYER_44, params=params)
    dados = resposta.json()
    if not isinstance(dados, dict) or dados.get("type") != "FeatureCollection":
        raise ValueError("SIMGeo camada 44 nao retornou FeatureCollection valida")
    return dados
 
 
def _gxa_criar_cluster(clusters, ponto, oid, extremidade):
    melhor_id, melhor_dist = None, float("inf")
    for cid, c in clusters.items():
        d = _gxa_haversine_m(ponto, c["centro"])
        if d < melhor_dist:
            melhor_id, melhor_dist = cid, d
    if melhor_id is not None and melhor_dist <= GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M:
        c = clusters[melhor_id]
        c["pontos"].append(ponto)
        c["incidencias"].append({"objectid": oid, "extremidade": extremidade})
        c["centro"] = (
            sum(p[0] for p in c["pontos"]) / len(c["pontos"]),
            sum(p[1] for p in c["pontos"]) / len(c["pontos"]),
        )
        return melhor_id
    cid = f"GXA-N{len(clusters) + 1:04d}"
    clusters[cid] = {
        "centro": ponto,
        "pontos": [ponto],
        "incidencias": [{"objectid": oid, "extremidade": extremidade}],
    }
    return cid
 
 
def _gxa_construir_topologia(segmentos):
    clusters = {}
    endpoints = {}
    for s in sorted(segmentos, key=lambda x: x["objectid"]):
        oid = s["objectid"]
        na = _gxa_criar_cluster(clusters, s["_coords"][0], oid, "inicio")
        nb = _gxa_criar_cluster(clusters, s["_coords"][-1], oid, "fim")
        endpoints[oid] = [na, nb]
 
    por_no = defaultdict(set)
    for oid, nos in endpoints.items():
        for no in nos:
            por_no[no].add(oid)
 
    adj = defaultdict(set)
    for conjunto in por_no.values():
        lista = sorted(conjunto)
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                adj[a].add(b)
                adj[b].add(a)
 
    ligacoes_interiores = []
    vistos = set()
    for s in segmentos:
        oid = s["objectid"]
        for extremidade, p in (("inicio", s["_coords"][0]), ("fim", s["_coords"][-1])):
            no_origem = endpoints[oid][0 if extremidade == "inicio" else 1]
            for alvo in segmentos:
                oid_alvo = alvo["objectid"]
                if oid_alvo == oid or no_origem in endpoints[oid_alvo]:
                    continue
                d, q, indice = _gxa_distancia_ponto_linha_m(p, alvo["_coords"])
                if d > GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M:
                    continue
                if min(
                    _gxa_haversine_m(q, alvo["_coords"][0]),
                    _gxa_haversine_m(q, alvo["_coords"][-1]),
                ) <= GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M:
                    continue
                chave = tuple(sorted((oid, oid_alvo))) + (no_origem,)
                if chave in vistos:
                    continue
                vistos.add(chave)
                ligacoes_interiores.append({
                    "no_endpoint": no_origem,
                    "segmento_endpoint": oid,
                    "segmento_interceptado": oid_alvo,
                    "distancia_m": round(d, 3),
                    "coordenada_intersecao_aprox": [q[0], q[1]],
                    "indice_aresta_interceptada": indice,
                })
                adj[oid].add(oid_alvo)
                adj[oid_alvo].add(oid)
 
    for s in segmentos:
        adj[s["objectid"]]
    return clusters, endpoints, por_no, adj, ligacoes_interiores
 
 
def _gxa_componente(adj, raiz):
    if raiz not in adj:
        return set()
    visitados = set()
    fila = deque([raiz])
    while fila:
        atual = fila.popleft()
        if atual in visitados:
            continue
        visitados.add(atual)
        fila.extend(v for v in adj[atual] if v not in visitados)
    return visitados
 
 
def _gxa_classificar_no(grau):
    if grau <= 1:
        return "extremidade"
    if grau == 2:
        return "passagem"
    return "juncao"
 
 
def _gxa_validar(segmentos_saida, nos_saida):
    erros = []
    segmentos = {s["objectid"]: s for s in segmentos_saida}
    ids_nos = {n["id"] for n in nos_saida}
    for oid, s in segmentos.items():
        for vizinho in s["conectado_a"]:
            if vizinho not in segmentos:
                erros.append(f"{oid}: referencia inexistente {vizinho}")
            elif oid not in segmentos[vizinho]["conectado_a"]:
                erros.append(f"{oid}<->{vizinho}: adjacencia nao simetrica")
        for no in s["nos_extremidade"]:
            if no not in ids_nos:
                erros.append(f"{oid}: no inexistente {no}")
    return erros
 
 
 
# =========================================================
# GUAXANDUVA-MODEL V0.2 - CAMADA MATEMATICA EXPERIMENTAL
# =========================================================
# O estimador abaixo NAO transforma maré em nivel do rio e NAO substitui
# sensor fluviometrico. Ele calcula uma cota experimental no ponto tecnico
# 30960 a partir de uma referencia de fundo experimental, resposta de chuva
# e efeito de remanso de jusante. Os coeficientes ficam publicados no JSON,
# com incerteza ampla, para futura calibracao por eventos e/ou imagem/sensor.
# Estacoes de chuva nunca sao somadas entre si: usa-se o maior acumulado
# valido entre as estacoes como forçante conservadora regional.
 
 
def _gxa_numero_finito(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    valor = float(valor)
    return valor if math.isfinite(valor) else None
 
 
def _gxa_maior_chuva_valida(chuva_por_estacao, janela):
    candidatos = []
    fontes = []
    for estacao in chuva_por_estacao or []:
        if not isinstance(estacao, dict):
            continue
        bloco = estacao.get(janela) or {}
        if bloco.get("disponivel") is not True:
            continue
        valor = _gxa_numero_finito(bloco.get("valor_mm"))
        if valor is None or valor < 0:
            continue
        candidatos.append(valor)
        fontes.append({
            "codigo": str(estacao.get("codigo") or ""),
            "nome": estacao.get("nome"),
            "valor_mm": round(valor, 3),
        })
    if not candidatos:
        return None, fontes
    return max(candidatos), fontes
 
 
def _gxa_calcular_propagacao_grafo_v03(segmentos_saida, componente):
    """Calcula apenas metricas geometricas do componente conectado ao 30960.
 
    V0.6 preserva a remocao de velocidade, atenuacao temporal e pesos sem calibracao. O grafo
    continua nao direcionado; portanto nenhuma distancia e tratada como tempo de
    viagem ou sentido hidraulico ate existir suporte altimetrico/hidraulico.
    """
    resultado = {
        "versao": "GXA-V0.8-CONTROLE-HIDRAULICO-BUEIRO",
        "status": "indisponivel",
        "segmento_referencia": GUAXANDUVA_SEGMENTO_REFERENCIA,
        "grafo_direcionado": False,
        "metodo": "dijkstra_geometrico_em_grafo_de_segmentos_sem_velocidade_ou_atenuacao_arbitraria",
        "uso_operacional": False,
        "observacao": "Distancias representam conectividade geometrica. Nao representam tempo de propagacao nem sentido de fluxo confirmado.",
    }
    if not isinstance(segmentos_saida, list) or not segmentos_saida:
        resultado["motivo"] = "segmentos_indisponiveis"
        return resultado
 
    por_id = {s.get("objectid"): s for s in segmentos_saida if isinstance(s, dict) and isinstance(s.get("objectid"), int)}
    ids = set(componente or []) & set(por_id)
    if GUAXANDUVA_SEGMENTO_REFERENCIA not in ids:
        resultado["motivo"] = "segmento_referencia_fora_do_componente"
        return resultado
 
    def comprimento(oid):
        valor = _gxa_numero_finito(por_id[oid].get("comprimento_m"))
        if valor is not None and valor > 0:
            return valor
        geom = por_id[oid].get("geometria") or []
        total = 0.0
        for i in range(len(geom) - 1):
            try:
                total += _gxa_haversine_m(tuple(geom[i]), tuple(geom[i + 1]))
            except Exception:
                pass
        return total if total > 0 else 1.0
 
    import heapq
    dist = {GUAXANDUVA_SEGMENTO_REFERENCIA: 0.0}
    fila = [(0.0, GUAXANDUVA_SEGMENTO_REFERENCIA)]
    while fila:
        d_atual, oid = heapq.heappop(fila)
        if d_atual > dist.get(oid, float("inf")):
            continue
        for vizinho in por_id[oid].get("conectado_a") or []:
            if vizinho not in ids:
                continue
            custo = 0.5 * comprimento(oid) + 0.5 * comprimento(vizinho)
            novo = d_atual + custo
            if novo < dist.get(vizinho, float("inf")):
                dist[vizinho] = novo
                heapq.heappush(fila, (novo, vizinho))
 
    total_comp = sum(comprimento(oid) for oid in ids)
    detalhes = []
    for oid in sorted(ids):
        d = dist.get(oid)
        if d is None:
            continue
        detalhes.append({
            "objectid": oid,
            "comprimento_m": round(comprimento(oid), 3),
            "distancia_geometrica_aprox_ao_30960_m": round(d, 3),
            "conexoes_no_componente": sum(1 for v in (por_id[oid].get("conectado_a") or []) if v in ids),
        })
 
    resultado.update({
        "status": "calculado_geometrico",
        "motivo": None,
        "segmentos_participantes": len(detalhes),
        "comprimento_total_componente_m": round(total_comp, 3),
        "distancia_maxima_geometrica_aprox_m": round(max(dist.values()) if dist else 0.0, 3),
        "segmentos": detalhes,
        "parametros_arbitrarios_removidos": [
            "velocidade_referencia_m_s",
            "velocidades_sensibilidade_m_s",
            "janela_resposta_referencia_h",
            "fator_propagacao_grafo",
        ],
    })
    return resultado
 
 
def _gxa_calcular_nivel_experimental_v02(guaxanduva166, propagacao_grafo=None):
    """V0.8: geometria vertical C2 + triagem de controle hidraulico do bypass.
 
    Mantem o nome da funcao por compatibilidade com a arquitetura existente.
    As declividades A1/A2/A3 do projeto 3999/21 entram na camada fisica.
    A faixa n=0,010-0,015 vem da literatura FHWA HEC-22 (2024) para tubos
    de concreto e e usada somente como envelope de referencia, nao como
    rugosidade local medida/calibrada. As cotas C2 do perfil 3999/21 sao
    registradas separando leituras documentais de valores derivados pela
    declividade. O nivel do rio permanece nulo enquanto faltarem vinculacao
    altimetrica completa, areas contribuintes e calibracao observacional.
    """
    diametro_m = 1.50
    raio_m = diametro_m / 2.0
    area_um_tubo_m2 = math.pi * raio_m * raio_m
    area_bueiro_duplo_m2 = 2.0 * area_um_tubo_m2
    area_victor_konder_m2 = 3.50 * 2.50
    raio_hidraulico_tubo_cheio_m = diametro_m / 4.0
    manning_n_min_literatura = 0.010
    manning_n_max_literatura = 0.015
    # Geometria vertical do perfil longitudinal 3999/21.
    # As cotas 1,800 / 1,431 / 0,909 m sao leituras documentais C2 do perfil.
    # A cota 0,849 m e DERIVADA de 0,909 - (0,0020 * 30), nao lida diretamente.
    # A cota 0,600 m aparece junto a estrutura de saida/ALA-02 e fica separada:
    # ela NAO e usada como invert final de A3, pois isso contrariaria i=0,0020.
    cota_c2_a1_m = 1.800
    cota_c2_a2_m = 1.431
    cota_c2_a3_inicio_m = 0.909
    cota_c2_a3_fim_derivada_m = round(
        cota_c2_a3_inicio_m - (0.0020 * 30.0), 3
    )
    cota_estrutura_saida_ala02_m = 0.600
    trechos_bypass = [
        {
            "trecho": "A1",
            "extensao_m": 17.0,
            "declividade_m_m": 0.0220,
            "cota_c2_montante_m": cota_c2_a1_m,
            "cota_c2_jusante_documental_m": cota_c2_a2_m,
            "natureza_cota_jusante": "leitura_documental_do_perfil",
        },
        {
            "trecho": "A2",
            "extensao_m": 126.0,
            "declividade_m_m": 0.0041,
            "cota_c2_montante_m": cota_c2_a2_m,
            "cota_c2_jusante_documental_m": cota_c2_a3_inicio_m,
            "natureza_cota_jusante": "leitura_documental_do_perfil",
        },
        {
            "trecho": "A3",
            "extensao_m": 30.0,
            "declividade_m_m": 0.0020,
            "cota_c2_montante_m": cota_c2_a3_inicio_m,
            "cota_c2_jusante_documental_m": None,
            "cota_c2_jusante_derivada_m": cota_c2_a3_fim_derivada_m,
            "natureza_cota_jusante": "derivada_de_cota_montante_declividade_e_extensao_documentadas",
        },
    ]
    for trecho in trechos_bypass:
        # Fator geometrico de Manning para os DOIS tubos cheios: Q = fator / n.
        # Nao escolhemos n sem fonte documental/calibracao.
        trecho["fator_geometrico_manning_m_8_3"] = round(
            area_bueiro_duplo_m2
            * (raio_hidraulico_tubo_cheio_m ** (2.0 / 3.0))
            * math.sqrt(trecho["declividade_m_m"]),
            6,
        )
        fator_manning = trecho["fator_geometrico_manning_m_8_3"]
        trecho["vazao_uniforme_referencia_m3_s"] = {
            "min_com_n_0_015": round(fator_manning / manning_n_max_literatura, 3),
            "max_com_n_0_010": round(fator_manning / manning_n_min_literatura, 3),
            "natureza": "envelope_de_literatura_para_escoamento_uniforme_em_tubos_cheios",
            "nao_representa_capacidade_definitiva_do_bueiro": True,
        }
        trecho["capacidade_vazao_m3_s"] = None
        trecho["equacao_capacidade"] = "Q_m3_s = fator_geometrico_manning_m_8_3 / n_manning_s_m_1_3"

    # V0.8 - estrutura de decisao para controle de entrada/saida segundo FHWA HDS-5.
    # Nao executa as equacoes de inlet/outlet control enquanto faltarem dados de
    # carga de montante, tailwater/submergencia e geometria/coficientes da entrada.
    # Assim, nenhum coeficiente de entrada e presumido a partir apenas do termo ALA.
    controle_hidraulico_bueiro = {
        "versao_metodo": "FHWA-HDS-5-3a-edicao-2012",
        "publicacao": "FHWA-HIF-12-026",
        "fonte": "Hydraulic Design of Highway Culverts, Third Edition",
        "status": "estrutura_de_calculo_preparada_dados_insuficientes_para_resolver",
        "uso_operacional": False,
        "controle_governante": None,
        "vazao_capacidade_definitiva_m3_s": None,
        "headwater_m": None,
        "tailwater_m": None,
        "inlet_control": {
            "calculavel": False,
            "condicao_submersao_entrada": None,
            "coeficientes_hds5_selecionados": False,
            "motivo": "faltam_headwater_e_identificacao_inequivoca_da_geometria_de_entrada_para_selecionar_coeficientes_HDS5",
            "regra_fisica": "entrada_nao_submersa_comporta_se_como_controle_tipo_vertedor; entrada_submersa_comporta_se_como_orificio; zona_de_transicao_exige_metodo_HDS5",
        },
        "outlet_control": {
            "calculavel": False,
            "coeficiente_perda_entrada_ke": None,
            "coeficiente_perda_saida_ko": None,
            "perdas_atrito_calculadas": False,
            "motivo": "faltam_tailwater_submergencia_condicao_de_saida_e_coeficientes_de_perda_confirmados",
        },
        "dados_documentados_disponiveis": {
            "quantidade_tubos": 2,
            "diametro_nominal_m": diametro_m,
            "material": "concreto_armado_PA-1",
            "extensao_total_aprox_m": 173.0,
            "trechos_com_declividade_documentada": ["A1", "A2", "A3"],
            "cotas_c2_parciais_documentadas": [1.800, 1.431, 0.909],
            "sentido_escoamento_no_perfil": True,
        },
        "dados_ainda_necessarios": {
            "headwater_referenciado_ao_invert_de_entrada": False,
            "tailwater_referenciado_ao_invert_de_saida": False,
            "geometria_exata_da_boca_de_entrada_para_coeficientes_HDS5": False,
            "coeficiente_perda_entrada_ke_confirmado": False,
            "coeficiente_perda_saida_ko_confirmado": False,
            "rugosidade_local_ou_calibrada": False,
            "cota_invert_final_A3_confirmada_documentalmente": False,
            "condicao_real_dos_tubos_obstrucao_assoreamento": False,
        },
        "criterio_liberacao": "calcular_controle_de_entrada_e_controle_de_saida_separadamente_e_comparar_somente_quando_as_entradas_exigidas_estiverem_documentadas",
        "observacao": "A V0.8 nao converte o envelope Manning de tubo cheio em capacidade definitiva e nao inventa coeficientes HDS-5.",
    }
 
    resultado = {
        "versao": "GXA-V0.8-CONTROLE-HIDRAULICO-BUEIRO",
        "status": "restricoes_fisicas_integradas_nivel_absoluto_ainda_indisponivel",
        "nivel_estimado_m": None,
        "incerteza_m": None,
        "confianca": "fisica_parcial_sem_calibracao_de_nivel",
        "metodo": "restricoes_geometricas_documentadas_mais_forcantes_observadas_sem_coeficientes_empiricos_arbitrarios",
        "instante": agora().isoformat(),
        "uso_operacional": False,
        "alerta_operacional_liberado": False,
        "representa_medicao_instrumental": False,
        "geometria_hidraulica_documentada": {
            "bypass_montezuma_odilon": {
                "quantidade_tubos": 2,
                "diametro_nominal_m": diametro_m,
                "extensao_aprox_m": 173.0,
                "area_secao_um_tubo_m2": round(area_um_tubo_m2, 4),
                "area_secao_total_geometrica_m2": round(area_bueiro_duplo_m2, 4),
                "escavacao_media_m": [2.5, 3.0],
                "classe_documentada": "PA-1",
                "tipo_documentado": "BDTC",
                "fonte_documental": "Projeto executivo municipal 3999/21 - perfil longitudinal",
                "declividades_documentadas": trechos_bypass,
                "extensao_trechos_soma_m": round(sum(t["extensao_m"] for t in trechos_bypass), 3),
                "raio_hidraulico_tubo_cheio_m": round(raio_hidraulico_tubo_cheio_m, 4),
                "sentido_escoamento_documentado_no_perfil": True,
                "c2_definicao_documentada": "cota_da_tubulacao_na_geratriz_inferior",
                "geometria_vertical_c2": {
                    "fonte": "Projeto executivo municipal 3999/21 - perfil longitudinal",
                    "cotas_documentais_m": [1.800, 1.431, 0.909],
                    "a3_cota_jusante_derivada_m": cota_c2_a3_fim_derivada_m,
                    "a3_derivacao": "0.909 - (0.0020 * 30.0) = 0.849 m",
                    "cota_estrutura_saida_ala02_m": cota_estrutura_saida_ala02_m,
                    "cota_0_600_e_invert_final_a3": False,
                    "regra": "0.600_m_permanece_separada_da_geratriz_inferior_final_A3; nao_forcar_como_invert_sem_confirmacao_documental",
                    "uso_para_nivel_do_rio": False,
                },
                "manning_literatura_referencia": {
                    "n_min": manning_n_min_literatura,
                    "n_max": manning_n_max_literatura,
                    "material": "tubo_de_concreto",
                    "fonte": "FHWA HEC-22 Urban Drainage Design Manual, 4th ed., 2024, Table 4.4",
                    "publicacao": "FHWA-HIF-24-006",
                    "uso": "envelope_de_referencia_nao_calibrado_localmente",
                    "observacao": "valores_menores_em_geral_correspondem_a_tubos_mais_lisos_bem_construidos_e_mantidos",
                },
                "manning_referencia_secundaria": {
                    "n_min": 0.011,
                    "n_max": 0.013,
                    "fonte": "FHWA HDS-4 Introduction to Highway Hydraulics, 2008, Table B.3",
                    "uso": "checagem_bibliografica_secundaria",
                },
                "capacidade_vazao_m3_s": None,
                "motivo_capacidade_indisponivel": "envelope_Manning_de_literatura_calculado; capacidade_definitiva_exige_rugosidade_local_ou_calibrada_e_analise_de_controle_de_entrada_saida_e_submergencia",
                "controle_hidraulico_hds5": controle_hidraulico_bueiro,
            },
            "estrutura_victor_konder_canoas": {
                "largura_aprox_m": 3.5,
                "altura_aprox_m": 2.5,
                "area_secao_retangular_geometrica_aprox_m2": round(area_victor_konder_m2, 4),
                "capacidade_vazao_m3_s": None,
                "motivo_capacidade_indisponivel": "declividade_rugosidade_e_condicao_de_escoamento_nao_confirmadas",
            },
        },
        "parametros_necessarios_para_nivel_hidraulico": {
            "cotas_c2_do_bypass_documentadas_no_perfil": True,
            "cota_c2_final_a3_derivada_matematicamente": True,
            "cota_estrutura_saida_0_600_confirmada_como_invert_final_a3": False,
            "cota_invert_ou_fundo_do_rio_em_datum_confirmado": False,
            "declividade_hidraulica_numerica_confirmada_bypass_3999_21": True,
            "rugosidade_manning_literatura_para_tubo_concreto_disponivel": True,
            "rugosidade_manning_documentada_no_projeto_ou_calibrada_localmente": False,
            "areas_contribuintes_por_ramo_ou_subbacia": False,
            "direcao_hidraulica_bypass_3999_21_confirmada": True,
            "direcao_hidraulica_do_grafo_completo_confirmada": False,
            "calibracao_com_nivel_observado_ou_referencia_visual": False,
            "estrutura_metodologica_controle_entrada_saida_hds5_integrada": True,
            "controle_entrada_hds5_calculavel_com_dados_atuais": False,
            "controle_saida_hds5_calculavel_com_dados_atuais": False,
        },
        "regras": [
            "Nenhum coeficiente chuva-para-nivel e aplicado sem proveniencia ou calibracao.",
            "As declividades A1=0,0220; A2=0,0041; A3=0,0020 m/m sao documentadas no perfil longitudinal 3999/21.",
            "As cotas C2 1,800; 1,431; 0,909 m sao registradas como leituras documentais do perfil longitudinal 3999/21.",
            "A cota C2 de jusante de A3 = 0,849 m e derivada de 0,909 - (0,0020 x 30), e nao apresentada como leitura direta do desenho.",
            "A cota 0,600 m junto a estrutura de saida/ALA-02 nao e usada como invert final de A3 sem confirmacao documental adicional.",
            "A faixa n=0,010-0,015 e referencia bibliografica FHWA HEC-22 para tubo de concreto; nao e medicao nem calibracao local.",
            "Publica-se um envelope de vazao uniforme Q=fator/n para os dois tubos cheios, sem chama-lo de capacidade definitiva do bueiro.",
            "Capacidade definitiva exige verificacao de controle de entrada/saida, carga de montante, jusante/submergencia, perdas e condicao real dos tubos.",
            "A metodologia FHWA HDS-5 (FHWA-HIF-12-026) foi integrada como estrutura de decisao; nenhuma equacao de controle e resolvida sem as entradas documentais exigidas.",
            "Nenhum coeficiente de entrada/saida HDS-5 e inferido apenas pela presenca das estruturas ALA-01/ALA-02 no desenho.",
            "Nenhuma velocidade de propagacao e presumida sem suporte fisico.",
            "Escavacao de 2,5 a 3,0 m nao e convertida em cota absoluta do leito.",
            "A cota experimental antiga de 0,50 m nao e usada como datum hidraulico.",
            "Mare de Joinville/Babitonga permanece somente condicao observada de jusante.",
            "Nivel observado e nivel estimado permanecem nulos enquanto a equacao fisica nao puder ser fechada.",
        ],
        "parametros_arbitrarios_v03_desativados": [
            "cota_fundo_experimental_m=0.50 como cota absoluta",
            "lamina_base_experimental_m=0.35",
            "coef_chuva_p3_m_por_mm=0.008",
            "coef_chuva_incremental_p6_m_por_mm=0.004",
            "coef_chuva_incremental_p24_m_por_mm=0.0015",
            "coef_remanso_anomalia_mare=0.35",
            "velocidade_propagacao_referencia_m_s=0.35",
            "janela_atenuacao_grafo_h=3.0",
        ],
    }
 
    if isinstance(propagacao_grafo, dict):
        resultado["grafo"] = {
            "status": propagacao_grafo.get("status"),
            "segmentos_participantes": propagacao_grafo.get("segmentos_participantes"),
            "comprimento_total_componente_m": propagacao_grafo.get("comprimento_total_componente_m"),
            "distancia_maxima_geometrica_aprox_m": propagacao_grafo.get("distancia_maxima_geometrica_aprox_m"),
            "grafo_direcionado": propagacao_grafo.get("grafo_direcionado"),
        }
 
    if not isinstance(guaxanduva166, dict):
        resultado["forcantes"] = {"status": "historico_166_indisponivel"}
        return resultado
 
    chuvas = guaxanduva166.get("chuva_por_estacao") or []
    p1, f1 = _gxa_maior_chuva_valida(chuvas, "P1h")
    p3, f3 = _gxa_maior_chuva_valida(chuvas, "P3h")
    p6, f6 = _gxa_maior_chuva_valida(chuvas, "P6h")
    p24, f24 = _gxa_maior_chuva_valida(chuvas, "P24h")
 
    mare = guaxanduva166.get("mare_jusante_mais_recente") or {}
    nivel_mare = _gxa_numero_finito(mare.get("nivel_m"))
    nmm_cm = _gxa_numero_finito(mare.get("nmm_cm"))
    anomalia_mare_m = None
    if nivel_mare is not None and nmm_cm is not None:
        anomalia_mare_m = nivel_mare - (nmm_cm / 100.0)
 
    resultado["forcantes"] = {
        "chuva": {
            "P1h_mm": p1, "P3h_mm": p3, "P6h_mm": p6, "P24h_mm": p24,
            "fontes_P1h": f1, "fontes_P3h": f3, "fontes_P6h": f6, "fontes_P24h": f24,
            "regra": "estacoes_independentes_nao_somadas; maior_acumulado_valido_apenas_para_resumo_regional",
        },
        "mare_jusante": {
            "nivel_m": round(nivel_mare, 3) if nivel_mare is not None else None,
            "nmm_m": round(nmm_cm / 100.0, 3) if nmm_cm is not None else None,
            "anomalia_relativa_ao_nmm_m": round(anomalia_mare_m, 3) if anomalia_mare_m is not None else None,
            "horario_medicao": mare.get("horario_medicao"),
            "representa_nivel_rio_guaxanduva": False,
        },
    }
    return resultado
 
 
def construir_modelo_computacional_guaxanduva_v01(guaxanduva166=None):
    base = {
        "versao": GUAXANDUVA_MODELO_VERSAO,
        "gerado_em": agora().isoformat(),
        "status": "indisponivel",
        "fonte_hidrografia": "Prefeitura de Joinville / SIMGeo - camada 44",
        "microbacia": GUAXANDUVA_MICROBACIA,
        "segmento_referencia": GUAXANDUVA_SEGMENTO_REFERENCIA,
        "ponto_referencia": {
            "longitude": GUAXANDUVA_PONTO_REFERENCIA[0],
            "latitude": GUAXANDUVA_PONTO_REFERENCIA[1],
            "uso": "ponto_tecnico_publico_do_modelo",
        },
        "rio": {
            "nome": "Rio Guaxanduva",
            "nivel_observado_m": None,
            "nivel_estimado_m": None,
            "incerteza_m": None,
            "confianca": "experimental",
        },
        "parametros_hidraulicos_documentados": {
            "bypass_montezuma_odilon": {
                "extensao_aprox_m": 173.0,
                "quantidade_tubos": 2,
                "diametro_nominal_m": 1.5,
                "escavacao_media_m": [2.5, 3.0],
                "trechos_declividade": [
                    {"trecho": "A1", "extensao_m": 17.0, "declividade_m_m": 0.0220},
                    {"trecho": "A2", "extensao_m": 126.0, "declividade_m_m": 0.0041},
                    {"trecho": "A3", "extensao_m": 30.0, "declividade_m_m": 0.0020},
                ],
                "manning_literatura_tubo_concreto": {
                    "n_min": 0.010,
                    "n_max": 0.015,
                    "fonte": "FHWA HEC-22 4th ed. 2024 Table 4.4",
                    "publicacao": "FHWA-HIF-24-006",
                    "uso": "envelope_de_referencia_nao_calibrado_localmente",
                },
                "sentido_escoamento_documentado_no_perfil": True,
                "uso": "restricao_geometrica_e_declividade_documentada_do_modelo",
            },
            "estrutura_victor_konder_canoas": {
                "largura_aprox_m": 3.5,
                "altura_aprox_m": 2.5,
                "uso": "restricao_geometrica_do_modelo",
            },
            "cota_fundo_experimental_v01": {
                "estimada_m": 0.5,
                "incerteza_m": 0.9,
                "confianca": "baixa",
                "uso_operacional": False,
            },
        },
        "forcantes": {
            "historico_166_integrado": isinstance(guaxanduva166, dict),
            "chuva_por_estacao": (guaxanduva166 or {}).get("chuva_por_estacao") if isinstance(guaxanduva166, dict) else None,
            "mare_jusante": (guaxanduva166 or {}).get("mare_jusante_mais_recente") if isinstance(guaxanduva166, dict) else None,
            "mare_representa_nivel_do_rio": False,
        },
        "alerta_operacional_liberado": False,
    }
    try:
        geojson = _gxa_baixar_geojson()
        segmentos = []
        descartados = []
        for feature in geojson.get("features", []):
            s = _gxa_normalizar_feature(feature)
            if s is None:
                descartados.append(feature.get("id"))
            else:
                segmentos.append(s)
        if not segmentos:
            raise ValueError("nenhum segmento valido retornado pelo SIMGeo")
 
        clusters, endpoints, por_no, adj, ligacoes = _gxa_construir_topologia(segmentos)
        componente = _gxa_componente(adj, GUAXANDUVA_SEGMENTO_REFERENCIA)
        if not componente:
            raise ValueError("segmento 30960 nao localizado na topologia retornada")
 
        melhor = None
        for s in segmentos:
            d, q, indice = _gxa_distancia_ponto_linha_m(GUAXANDUVA_PONTO_REFERENCIA, s["_coords"])
            if melhor is None or d < melhor["distancia_m"]:
                melhor = {"objectid": s["objectid"], "distancia_m": d, "projecao": q, "indice": indice}
 
        nos_saida = []
        for cid, c in sorted(clusters.items()):
            incidentes = sorted(por_no.get(cid, set()))
            nos_saida.append({
                "id": cid,
                "coordenada": [c["centro"][0], c["centro"][1]],
                "segmentos": incidentes,
                "grau_topologico": len(incidentes),
                "classe": _gxa_classificar_no(len(incidentes)),
                "incidencias": c["incidencias"],
            })
 
        segmentos_saida = []
        for s in sorted(segmentos, key=lambda x: x["objectid"]):
            oid = s["objectid"]
            segmentos_saida.append({
                "objectid": oid,
                "nome_rio": s["nome_rio"],
                "tipo": s["tipo"],
                "comprimento_m": s["comprimento_m"],
                "auc": s["auc"],
                "contribuicao": s["contribuicao"],
                "drenagem": s["drenagem"],
                "microbacia": s["microbacia"],
                "nos_extremidade": endpoints[oid],
                "conectado_a": sorted(adj[oid]),
                "pertence_componente_30960": oid in componente,
                "geometria": s["geometria"],
            })
 
        erros = _gxa_validar(segmentos_saida, nos_saida)
        base.update({
            "status": "grafo_hidrografico_integrado" if not erros else "grafo_com_inconsistencias",
            "crs_geometria": "EPSG:4326",
            "tolerancia_topologica_m": GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M,
            "resumo": {
                "segmentos_microbacia": len(segmentos_saida),
                "nos_endpoints": len(nos_saida),
                "ligacoes_endpoint_interior": len(ligacoes),
                "segmentos_componente_30960": len(componente),
                "juncoes_grau_3_ou_mais": sum(1 for n in nos_saida if n["grau_topologico"] >= 3),
                "features_descartadas": descartados,
            },
            "ponto_referencia_topologia": {
                "segmento_mais_proximo": melhor["objectid"],
                "distancia_ao_eixo_m": round(melhor["distancia_m"], 3),
                "projecao_no_eixo": [melhor["projecao"][0], melhor["projecao"][1]],
                "coincide_com_30960": melhor["objectid"] == GUAXANDUVA_SEGMENTO_REFERENCIA and melhor["distancia_m"] <= GUAXANDUVA_TOLERANCIA_TOPOLOGICA_M,
            },
            "nos": nos_saida,
            "ligacoes_endpoint_interior": ligacoes,
            "segmentos": segmentos_saida,
            "validacao": {
                "adjacencia_simetrica_e_referencias_validas": not erros,
                "erros": erros,
            },
        })
 
        propagacao_grafo = _gxa_calcular_propagacao_grafo_v03(segmentos_saida, componente)
        base["propagacao_grafo"] = propagacao_grafo
        camada_matematica = _gxa_calcular_nivel_experimental_v02(guaxanduva166, propagacao_grafo)
        base["camada_matematica"] = camada_matematica
        base["rio"]["nivel_estimado_m"] = camada_matematica.get("nivel_estimado_m")
        base["rio"]["incerteza_m"] = camada_matematica.get("incerteza_m")
        base["rio"]["confianca"] = camada_matematica.get("confianca")
        base["rio"]["metodo"] = camada_matematica.get("metodo")
        base["rio"]["instante"] = camada_matematica.get("instante")
 
        with open(GUAXANDUVA_GRAFO_ARQUIVO, "w", encoding="utf-8") as arquivo:
            json.dump(base, arquivo, ensure_ascii=False, indent=2)
    except Exception as exc:
        base["erro"] = str(exc)
        base["status"] = "indisponivel_sem_interromper_monitor"
    return base
 
 
# =========================================================
# #166 - HISTÓRICO HIDROMETEOROLÓGICO DO RIO GUAXANDUVA
# =========================================================
# Esta camada NÃO mede o nível do Rio Guaxanduva. Ela preserva, com o
# timestamp real de cada fonte, chuva horária observada e maré observada em
# Joinville/Babitonga para permitir calibração temporal futura chuva x maré.
# Ausência de dado permanece ausência; nunca é convertida em 0 mm.
 
HISTORICO_GUAXANDUVA_166_ARQUIVO = "historico_guaxanduva_166.json"
VERSAO_GUAXANDUVA_166 = "166-v0.2-historico-integrado"
 
 
def _numero_finito_nao_negativo_166(valor):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    valor = float(valor)
    if not math.isfinite(valor) or valor < 0:
        return None
    return valor
 
 
def _instante_iso_166(valor):
    if not valor:
        return None
    try:
        instante = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=FUSO)
        return instante.astimezone(FUSO)
    except Exception:
        return None
 
 
def _carregar_historico_guaxanduva_166():
    try:
        with open(HISTORICO_GUAXANDUVA_166_ARQUIVO, "r", encoding="utf-8") as arquivo:
            payload = json.load(arquivo)
        if not isinstance(payload, dict):
            raise ValueError("histórico #166 não é objeto JSON")
        registros = payload.get("registros")
        if not isinstance(registros, list):
            registros = []
        return registros
    except FileNotFoundError:
        return []
    except Exception:
        # Falha de leitura não apaga nem inventa observações. O chamador
        # registra o estado atual em nova estrutura, mantendo a segurança.
        return []
 
 
def _chave_registro_166(registro):
    return (
        str(registro.get("tipo") or ""),
        str(registro.get("fonte") or ""),
        str(registro.get("codigo_estacao") or ""),
        str(registro.get("horario_medicao") or ""),
    )
 
 
def _deduplicar_registros_166(registros):
    unicos = {}
    for registro in registros:
        if not isinstance(registro, dict):
            continue
        chave = _chave_registro_166(registro)
        if not chave[0] or not chave[3]:
            continue
        unicos[chave] = registro
    return sorted(
        unicos.values(),
        key=lambda r: (
            str(r.get("horario_medicao") or ""),
            str(r.get("tipo") or ""),
            str(r.get("codigo_estacao") or ""),
        ),
    )
 
 
def _novos_registros_chuva_epagri_166(chuva_epagri165):
    novos = []
    if not isinstance(chuva_epagri165, dict):
        return novos
    for estacao in chuva_epagri165.get("estacoes") or []:
        if not isinstance(estacao, dict):
            continue
        valor = _numero_finito_nao_negativo_166(estacao.get("precipitacao_1h_mm"))
        instante = _instante_iso_166(estacao.get("horario_medicao"))
        if valor is None or instante is None:
            continue
        novos.append({
            "tipo": "chuva_horaria_observada",
            "fonte": "EPAGRI/CIRAM",
            "codigo_estacao": str(estacao.get("codigo") or ""),
            "nome_estacao": estacao.get("nome"),
            "horario_medicao": instante.isoformat(),
            "janela_h": 1,
            "precipitacao_mm": round(valor, 3),
            "equivale_medicao_no_comasa": False,
        })
    return novos
 
 
def _novo_registro_mare_166(mare_observada160):
    if not isinstance(mare_observada160, dict):
        return []
    nivel_cm = _numero_finito_nao_negativo_166(mare_observada160.get("nivel_cm"))
    instante = _instante_iso_166(mare_observada160.get("horario"))
    if nivel_cm is None or instante is None:
        return []
    return [{
        "tipo": "mare_observada_jusante",
        "fonte": "EPAGRI/CIRAM",
        "codigo_estacao": "maregrafo_joinville_2913",
        "nome_estacao": "Joinville / Babitonga",
        "horario_medicao": instante.isoformat(),
        "nivel_cm": round(nivel_cm, 2),
        "nivel_m": round(nivel_cm / 100.0, 3),
        "mare_astronomica_cm": mare_observada160.get("mare_astronomica_cm"),
        "residual_cm": mare_observada160.get("residual_cm"),
        "nmm_cm": mare_observada160.get("nmm_cm"),
        "representa_nivel_rio_guaxanduva": False,
        "uso": "condicao_de_jusante_para_calibracao_futura",
    }]
 
 
def _acumulado_horario_estacao_166(registros, codigo_estacao, horas):
    serie = []
    for registro in registros:
        if registro.get("tipo") != "chuva_horaria_observada":
            continue
        if str(registro.get("codigo_estacao") or "") != str(codigo_estacao):
            continue
        valor = _numero_finito_nao_negativo_166(registro.get("precipitacao_mm"))
        instante = _instante_iso_166(registro.get("horario_medicao"))
        if valor is None or instante is None:
            continue
        serie.append((instante, valor))
    if not serie:
        return {
            "disponivel": False,
            "valor_mm": None,
            "horas_necessarias": horas,
            "horas_validas": 0,
            "motivo": "sem_leituras_horarias",
        }
 
    # Uma medição por hora civil. O Actions pode rodar quatro vezes na mesma
    # hora; a deduplicação por estação + timestamp impede contagem repetida.
    por_hora = {}
    for instante, valor in serie:
        chave_hora = instante.replace(minute=0, second=0, microsecond=0)
        anterior = por_hora.get(chave_hora)
        if anterior is None or instante >= anterior[0]:
            por_hora[chave_hora] = (instante, valor)
 
    ultima_hora = max(por_hora)
    esperadas = [ultima_hora - timedelta(hours=i) for i in range(horas)]
    presentes = [h for h in esperadas if h in por_hora]
    if len(presentes) != horas:
        return {
            "disponivel": False,
            "valor_mm": None,
            "horas_necessarias": horas,
            "horas_validas": len(presentes),
            "horario_final": por_hora[ultima_hora][0].isoformat(),
            "motivo": "janela_horaria_incompleta",
        }
 
    total = sum(por_hora[h][1] for h in esperadas)
    return {
        "disponivel": True,
        "valor_mm": round(total, 3),
        "horas_necessarias": horas,
        "horas_validas": horas,
        "horario_final": por_hora[ultima_hora][0].isoformat(),
        "motivo": None,
    }
 
 
def _resumo_chuva_166(registros, chuva_epagri165):
    saida = []
    estacoes = chuva_epagri165.get("estacoes") if isinstance(chuva_epagri165, dict) else []
    for estacao in estacoes or []:
        if not isinstance(estacao, dict):
            continue
        codigo = str(estacao.get("codigo") or "")
        if not codigo:
            continue
        saida.append({
            "codigo": codigo,
            "nome": estacao.get("nome"),
            "fonte": "EPAGRI/CIRAM",
            "equivale_medicao_no_comasa": False,
            "P1h": _acumulado_horario_estacao_166(registros, codigo, 1),
            "P3h": _acumulado_horario_estacao_166(registros, codigo, 3),
            "P6h": _acumulado_horario_estacao_166(registros, codigo, 6),
            "P24h": _acumulado_horario_estacao_166(registros, codigo, 24),
        })
    return saida
 
 
def atualizar_historico_guaxanduva_166(chuva_epagri165, mare_observada160):
    existentes = _carregar_historico_guaxanduva_166()
    novos = []
    novos.extend(_novos_registros_chuva_epagri_166(chuva_epagri165))
    novos.extend(_novo_registro_mare_166(mare_observada160))
    registros = _deduplicar_registros_166(existentes + novos)
 
    chuvas = [r for r in registros if r.get("tipo") == "chuva_horaria_observada"]
    mares = [r for r in registros if r.get("tipo") == "mare_observada_jusante"]
    diagnostico = {
        "versao": VERSAO_GUAXANDUVA_166,
        "status": "historico_em_formacao",
        "arquivo_historico": HISTORICO_GUAXANDUVA_166_ARQUIVO,
        "gerado_em": agora().isoformat(),
        "quantidade_registros": len(registros),
        "quantidade_chuva_horaria": len(chuvas),
        "quantidade_mare_observada": len(mares),
        "chuva_por_estacao": _resumo_chuva_166(registros, chuva_epagri165),
        "mare_jusante_mais_recente": mares[-1] if mares else None,
        "rio": {
            "nome": "Rio Guaxanduva",
            "nivel_m": None,
            "nivel_estimado_m": None,
            "status": "sem_sensor_publico_confirmado",
        },
        "cota_fundo_modelo_v01": {
            "cota_fundo_oficial_m": None,
            "cota_fundo_estimada_m": 0.5,
            "incerteza_cota_fundo_m": 0.9,
            "confianca": "baixa",
            "uso_no_calculo_operacional": False,
            "observacao": "Hipotese experimental antiga preservada apenas como referencia de investigacao; nao representa cota oficial nem nivel observado do rio.",
        },
        "analise_lag_liberada": False,
        "nivel_estimado_liberado": False,
        "alerta_operacional_liberado": False,
        "regras_seguranca": [
            "Ausencia ou falha de leitura nunca e convertida em zero.",
            "Pluviometros diferentes permanecem series independentes e nao sao somados entre si.",
            "CEMADEN 24 h nao e tratado como chuva horaria.",
            "Mare de Joinville/Babitonga e condicao de jusante e nao nivel do Rio Guaxanduva.",
            "P3h, P6h e P24h so existem quando todas as horas da janela estao presentes.",
            "A camada historica #166 nao aplica pesos chuva x mare; coeficientes experimentais, quando existentes, pertencem exclusivamente ao GUAXANDUVA-MODEL e permanecem nao operacionais.",
        ],
    }
 
    payload = {
        "versao": VERSAO_GUAXANDUVA_166,
        "atualizado_em": agora().isoformat(),
        "politica_retencao": "sem_poda_automatica_nesta_fase_de_calibracao",
        "registros": registros,
    }
    with open(HISTORICO_GUAXANDUVA_166_ARQUIVO, "w", encoding="utf-8") as arquivo:
        json.dump(payload, arquivo, ensure_ascii=False, indent=2)
    return diagnostico
 
 
def main():
    chuva_cemaden = buscar_chuva_cemaden_136()
    chuva_epagri165 = buscar_chuva_epagri_165()
    rede165 = construir_rede_pluviometrica_multifonte_165(chuva_cemaden, chuva_epagri165)
    diag155 = diagnosticar_cap_recente_inmet_155()
    diag156 = diagnosticar_conteudo_cap_inmet_156(diag155)
    granizo157 = granizo_operacional_inmet_157(diag156)
    previsao = buscar_previsao()
    mare_observada160 = buscar_mare_observada_joinville_160()
    criterio163 = calcular_criterio_hidrometeorologico_plancon_163(previsao, mare_observada160)
    mare_prevista164 = calcular_pico_mare_previsto_24h_164(previsao)
    guaxanduva166 = atualizar_historico_guaxanduva_166(chuva_epagri165, mare_observada160)
    modelo_guaxanduva_v01 = construir_modelo_computacional_guaxanduva_v01(guaxanduva166)
    dados = {
        "monitor":
            "Monitor Guaxanduva",
 
        "local":
            "Comasa - Joinville/SC",
 
        "gerado_em":
            agora().isoformat(),
 
        "chuva":
            chuva_cemaden,
 
        "chuva_observada_epagri_165":
            chuva_epagri165,
 
        "rede_pluviometrica_multifonte_165":
            rede165,
 
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
 
        "mare_observada_joinville_160":
            mare_observada160,
 
        "mare_prevista_24h_164":
            mare_prevista164,
 
        "historico_hidrometeorologico_guaxanduva_166":
            guaxanduva166,
 
        "modelo_computacional_guaxanduva_v01":
            modelo_guaxanduva_v01,
 
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
 
        "criterio_hidrometeorologico_plancon_163":
            criterio163,
 
        "radar":
            buscar_radar(),
        "granizo": granizo157,
 
        "diagnostico_wis2_inmet_149": diagnosticar_wis2_inmet_149(),
 
        "diagnostico_historico_cap_inmet_150": diagnosticar_historico_cap_inmet_150(),
 
        "diagnostico_filtro_cap_inmet_151": diagnosticar_filtro_cap_inmet_151(),
 
        "diagnostico_data_id_cap_inmet_152": diagnosticar_data_id_cap_inmet_152(),
 
        "diagnostico_cap_por_metadata_id_153": diagnosticar_cap_por_metadata_id_153(),
 
        "diagnostico_xml_cap_inmet_154": diagnosticar_xml_cap_inmet_154(),
 
        "diagnostico_cap_recente_inmet_155": diag155,
 
        "diagnostico_conteudo_cap_inmet_156": diag156,
 
        "granizo_operacional_inmet_157": granizo157,
 
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
