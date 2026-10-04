#!/usr/bin/env python3
"""#174-E — Monitor Oceânico experimental do Monitor Guaxanduva.

Lê o diagnóstico GOES-19/TATHU do CPTEC/INPE, faz triagem ampla de sistemas
convectivos no entorno da América do Sul e calcula, de forma fail-closed,
distância e rumo para Joinville e compara uma janela temporal de até 60 minutos para verificar
se a distância do mesmo sistema diminui de forma persistente e fisicamente plausível. Vetores instantâneos são apenas
diagnóstico secundário; ETA continua bloqueado para uso operacional.

Este módulo NÃO altera dados.json e NÃO gera alerta operacional.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

UTC = ZoneInfo("UTC")
FUSO = ZoneInfo("America/Sao_Paulo")
LAT_JOINVILLE = -26.27
LON_JOINVILLE = -48.81
TATHU_BASE = "https://ftp.cptec.inpe.br/goes/goes19/goes19_web/tathu_web/diag/"
SAIDA_PADRAO = "monitor_oceanico_174.json"


def numero(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        x = float(str(v).strip().replace(",", "."))
        if not math.isfinite(x) or x <= -900:
            return None
        return x
    except Exception:
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def diferenca_angular(a, b):
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def centro_geojson(geometry):
    pontos = []
    def walk(obj):
        if not isinstance(obj, (list, tuple)):
            return
        if len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
            lon, lat = float(obj[0]), float(obj[1])
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                pontos.append((lat, lon))
            return
        for item in obj:
            walk(item)
    if isinstance(geometry, dict):
        walk(geometry.get("coordinates"))
    if not pontos:
        return None
    return sum(x[0] for x in pontos) / len(pontos), sum(x[1] for x in pontos) / len(pontos)


def posicao(feature):
    p = feature.get("properties") or {}
    lat, lon = numero(p.get("Latitude")), numero(p.get("Longitude"))
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon, "properties_Latitude_Longitude"
    c = centro_geojson(feature.get("geometry"))
    return (*c, "media_vertices_geojson") if c else None


def setor_origem(lat, lon):
    # Rótulo geográfico, não afirma gênese meteorológica do sistema.
    if lon <= -70:
        return "PACIFICO_CHILE_OESTE_ANDES"
    if lon >= -55:
        return "ATLANTICO_SUL_OU_FAIXA_COSTEIRA"
    return "CONTINENTE_SUL_AMERICA"


def dentro_dominio(lat, lon):
    # Triagem ampla: Pacífico SE + Cone Sul + Atlântico SW.
    return -60 <= lat <= 5 and -100 <= lon <= -20


def normalizar(feature):
    if not isinstance(feature, dict):
        return None
    p = feature.get("properties") or {}
    pos = posicao(feature)
    if not pos:
        return None
    lat, lon, metodo = pos
    if not dentro_dominio(lat, lon):
        return None

    dist = haversine_km(lat, lon, LAT_JOINVILLE, LON_JOINVILLE)
    rumo = bearing(lat, lon, LAT_JOINVILLE, LON_JOINVILLE)
    direcao = numero(p.get("Dir"))
    vel_ms = numero(p.get("Vel"))
    # Vel=0 não define direção de deslocamento. Mantemos o valor bruto, mas o
    # vetor só é utilizável quando há velocidade estritamente positiva.
    vetor_valido = vel_ms is not None and vel_ms > 0 and direcao is not None
    vel_kmh = None if vel_ms is None else vel_ms * 3.6
    dif = diferenca_angular(direcao, rumo) if vetor_valido else None

    if not vetor_valido:
        compat = "SEM_VETOR_VALIDO"
    elif dif <= 30:
        compat = "ALINHAMENTO_ANGULAR_FORTE_NAO_CONFIRMADO"
    elif dif <= 60:
        compat = "ALINHAMENTO_ANGULAR_PARCIAL_NAO_CONFIRMADO"
    elif dif <= 100:
        compat = "ALINHAMENTO_LATERAL"
    else:
        compat = "VETOR_NAO_ALINHADO"

    # #174-D: ETA fica bloqueado até a convenção de Dir/Vel ser documentalmente
    # validada e a aproximação ser confirmada em múltiplos quadros.
    eta_h = None

    return {
        "id_sistema": p.get("name"),
        "evento": p.get("event"),
        "fase": p.get("phase"),
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "metodo_posicao": metodo,
        "setor_geografico": setor_origem(lat, lon),
        "distancia_joinville_km": round(dist, 1),
        "rumo_sistema_para_joinville_graus": round(rumo, 1),
        "direcao_movimento_graus": None if direcao is None else round(direcao, 1),
        "diferenca_angular_graus": None if dif is None else round(dif, 1),
        "velocidade_movimento_m_s": None if vel_ms is None else round(vel_ms, 2),
        "velocidade_movimento_km_h": None if vel_kmh is None else round(vel_kmh, 1),
        "compatibilidade_trajetoria": compat,
        "eta_cinematico_h": None if eta_h is None else round(eta_h, 1),
        "eta_liberado_como_previsao": False,
        "temperatura_minima_topo_k": numero(p.get("Tmin")),
        "taxa_resfriamento_k_10min": numero(p.get("TxResf")),
        "fracao_convectiva_bruta": numero(p.get("FracConv")),
        "timestamp_fonte": p.get("timestamp"),
    }


def buscar_ultimo(timeout=4, max_tentativas=13):
    agora = datetime.now(UTC)
    base = agora.replace(minute=(agora.minute // 10) * 10, second=0, microsecond=0)
    tentativas = []
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "Monitor-Guaxanduva/174-A"})
    for passo in range(max_tentativas):
        t = base - timedelta(minutes=10 * passo)
        url = TATHU_BASE + t.strftime("%Y/%m/") + "goes19_diagnostic_" + t.strftime("%Y%m%d%H%M") + ".json"
        try:
            r = sessao.get(url, timeout=timeout)
            tentativas.append({"horario_utc": t.isoformat(), "http": r.status_code, "url": url})
            if r.status_code != 200:
                continue
            data = r.json()
            if isinstance(data, dict) and isinstance(data.get("features"), list):
                return data, t, url, tentativas
        except Exception as e:
            tentativas.append({"horario_utc": t.isoformat(), "http": None, "url": url, "erro": str(e)[:160]})
    return None, None, None, tentativas


def indexar_distancias(payload):
    """Indexa distância por ID no quadro anterior, sem inferir trajetória."""
    out = {}
    for f in (payload or {}).get("features", []):
        x = normalizar(f)
        if x and x.get("id_sistema"):
            out[str(x["id_sistema"])] = x["distancia_joinville_km"]
    return out


def aplicar_tendencia_observada(sistemas, payload_anterior, intervalo_minutos=10):
    anteriores = indexar_distancias(payload_anterior) if payload_anterior else {}
    for s in sistemas:
        anterior = anteriores.get(str(s.get("id_sistema")))
        s["distancia_quadro_anterior_km"] = anterior
        s["delta_distancia_km"] = None
        s["tendencia_distancia_observada"] = "SEM_PAREAMENTO_QUADRO_ANTERIOR"
        if anterior is None:
            continue
        delta = round(s["distancia_joinville_km"] - anterior, 1)
        s["delta_distancia_km"] = delta
        # Coordenadas TATHU aparecem centesimais; banda morta de 2 km evita
        # transformar quantização/ruído de centroide em tendência meteorológica.
        s["velocidade_centroide_implicita_km_h"] = round(abs(delta) / (intervalo_minutos / 60.0), 1)
        s["continuidade_apta_trajetoria"] = str(s.get("evento") or "").upper() == "CONTINUITY"
        s["salto_centroide_plausivel"] = s["velocidade_centroide_implicita_km_h"] <= 250.0
        if not s["continuidade_apta_trajetoria"]:
            s["tendencia_distancia_observada"] = "EVENTO_DESCONTINUO_NAO_USAR_TRAJETORIA"
        elif not s["salto_centroide_plausivel"]:
            s["tendencia_distancia_observada"] = "SALTO_CENTROIDE_INCOMPATIVEL"
        elif delta <= -2.0:
            s["tendencia_distancia_observada"] = "APROXIMANDO_OBSERVADO_CONTINUO"
        elif delta >= 2.0:
            s["tendencia_distancia_observada"] = "AFASTANDO_OBSERVADO_CONTINUO"
        else:
            s["tendencia_distancia_observada"] = "SEM_TENDENCIA_SIGNIFICATIVA"
        s["intervalo_comparacao_min"] = intervalo_minutos
    return sistemas


def confirmar_ecmwf_850(sistemas, horario_produto, timeout=8, limite=20, lote=5, tentativas=2):
    """Gate #174-F: confirmação sinótica robusta e explicitamente triestatal.

    FAVORAVEL/CONTRARIO só existem quando uma amostra ECMWF 850 hPa válida foi obtida.
    Falha HTTP, timeout, JSON inválido ou ausência de amostra produz FONTE_INDISPONIVEL
    (ou SEM_AMOSTRA), nunca CONTRARIO. Consultas são feitas em lotes pequenos com retry.
    """
    candidatos = [s for s in sistemas if s.get("tendencia_distancia_observada") == "APROXIMANDO_OBSERVADO_CONTINUO"]
    candidatos.sort(key=lambda x: x["distancia_joinville_km"])
    candidatos = candidatos[:max(1, limite)]
    for s in sistemas:
        s["confirmacao_sinotica_850hpa"] = "NAO_AVALIADA"
        s["estado_sinotico_174f"] = "NAO_AVALIADO"
        s["ecmwf_850hpa"] = None
    fonte = "ECMWF via Open-Meteo ECMWF API"
    if not candidatos:
        return {"status": "sem_candidatos_continuos", "estado_fonte": "NAO_NECESSARIA", "avaliados": 0,
                "favoraveis": 0, "contrarios": 0, "inconclusivos": 0, "indisponiveis": 0, "fonte": fonte}

    endpoint = "https://api.open-meteo.com/v1/ecmwf"
    alvo = horario_produto.replace(minute=0, second=0, microsecond=0) if horario_produto else datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    avaliados = favoraveis = contrarios = inconclusivos = indisponiveis = 0
    erros = []

    for ini in range(0, len(candidatos), max(1, lote)):
        bloco = candidatos[ini:ini + max(1, lote)]
        params = {
            "latitude": ",".join(str(s["latitude"]) for s in bloco),
            "longitude": ",".join(str(s["longitude"]) for s in bloco),
            "hourly": "wind_speed_850hPa,wind_direction_850hPa",
            "forecast_days": 2, "timezone": "UTC", "cell_selection": "nearest"
        }
        locais = None
        ultimo_erro = None
        for tentativa in range(1, max(1, tentativas) + 1):
            try:
                r = requests.get(endpoint, params=params, timeout=timeout,
                                 headers={"User-Agent": "Monitor-Guaxanduva/174-F"})
                r.raise_for_status()
                payload = r.json()
                locais = payload if isinstance(payload, list) else [payload]
                break
            except Exception as e:
                ultimo_erro = f"lote={ini//max(1,lote)+1} tentativa={tentativa}: {str(e)[:160]}"
        if locais is None:
            erros.append(ultimo_erro or "erro_desconhecido")
            for s in bloco:
                s["confirmacao_sinotica_850hpa"] = "FONTE_INDISPONIVEL"
                s["estado_sinotico_174f"] = "FONTE_INDISPONIVEL"
                indisponiveis += 1
            continue

        # Resposta incompleta também é ausência de fonte/amostra, não oposição meteorológica.
        while len(locais) < len(bloco):
            locais.append(None)
        for s, loc in zip(bloco, locais):
            h = (loc or {}).get("hourly") or {}; tempos = h.get("time") or []
            def parse_t(t):
                try: return datetime.fromisoformat(str(t)).replace(tzinfo=UTC)
                except Exception: return None
            pares = [(abs((tt-alvo).total_seconds()), i, tt) for i,t in enumerate(tempos) if (tt:=parse_t(t)) is not None]
            if not pares:
                s["confirmacao_sinotica_850hpa"] = "SEM_AMOSTRA_MODELO"
                s["estado_sinotico_174f"] = "FONTE_INDISPONIVEL"
                indisponiveis += 1
                continue
            _, j, tt = min(pares)
            vs = h.get("wind_speed_850hPa") or []; ds = h.get("wind_direction_850hPa") or []
            sp = numero(vs[j]) if j < len(vs) else None; dfrom = numero(ds[j]) if j < len(ds) else None
            if sp is None or dfrom is None:
                s["confirmacao_sinotica_850hpa"] = "SEM_AMOSTRA_MODELO"
                s["estado_sinotico_174f"] = "FONTE_INDISPONIVEL"
                indisponiveis += 1
                continue
            dto = (dfrom + 180.0) % 360.0
            erro = diferenca_angular(dto, s["rumo_sistema_para_joinville_graus"])
            if sp < 10:
                status = "INCONCLUSIVO_VENTO_FRACO"; estado = "INCONCLUSIVO"; inconclusivos += 1
            elif erro <= 60:
                status = "APOIA_CORREDOR_PARA_JOINVILLE"; estado = "FAVORAVEL"; favoraveis += 1
            else:
                status = "NAO_APOIA_CORREDOR_PARA_JOINVILLE"; estado = "CONTRARIO"; contrarios += 1
            avaliados += 1
            s["confirmacao_sinotica_850hpa"] = status
            s["estado_sinotico_174f"] = estado
            s["ecmwf_850hpa"] = {"horario_utc": tt.isoformat(), "vento_km_h": round(sp,1),
                                  "direcao_de_graus": round(dfrom,1), "vetor_para_graus": round(dto,1),
                                  "erro_para_joinville_graus": round(erro,1), "natureza": "MODELADO_NAO_OPERACIONAL"}

    if avaliados and indisponiveis:
        status_geral = "coletado_parcial"
    elif avaliados:
        status_geral = "coletado"
    else:
        status_geral = "fonte_indisponivel_fail_closed"
    return {"status": status_geral, "estado_fonte": "PARCIAL" if indisponiveis and avaliados else ("DISPONIVEL" if avaliados else "INDISPONIVEL"),
            "avaliados": avaliados, "favoraveis": favoraveis, "contrarios": contrarios,
            "inconclusivos": inconclusivos, "indisponiveis": indisponiveis, "apoiam": favoraveis,
            "nao_apoiam": contrarios, "erros": erros[:5], "lote_maximo": lote, "tentativas_por_lote": tentativas,
            "fonte": fonte, "regra": "FAVORAVEL/CONTRARIO exigem amostra ECMWF valida; falha de fonte nunca equivale a CONTRARIO."}


def indexar_quadro_completo(payload):
    out = {}
    for f in (payload or {}).get("features", []):
        x = normalizar(f)
        if x and x.get("id_sistema"):
            out[str(x["id_sistema"])] = x
    return out


def aplicar_persistencia_temporal(sistemas, historico_quadros):
    """Gate #174-E: exige continuidade e aproximação em todos os passos da janela.

    30 min = quadro atual + 3 anteriores (4 observações).
    60 min = quadro atual + 6 anteriores (7 observações).
    Um passo só é válido se ambos os registros forem CONTINUITY, o deslocamento
    implícito não exceder 250 km/h e a distância cair ao menos 2 km/10 min.
    """
    indices = [(h, indexar_quadro_completo(p)) for h, p, _ in historico_quadros if p]
    for s in sistemas:
        sid = str(s.get("id_sistema"))
        serie = [{"horario_utc": None, "distancia_km": s["distancia_joinville_km"], "evento": s.get("evento")}]
        for h, idx in indices:
            x = idx.get(sid)
            if x:
                serie.append({"horario_utc": h.isoformat(), "distancia_km": x["distancia_joinville_km"], "evento": x.get("evento")})
            else:
                serie.append(None)
        # historico vem do mais recente para o mais antigo; avaliamos pares atual<-anterior.
        passos = []
        for i in range(min(6, len(serie)-1)):
            atual, ant = serie[i], serie[i+1]
            if atual is None or ant is None:
                passos.append({"valido": False, "motivo": "SEM_PAREAMENTO"}); continue
            eventos_ok = str(atual.get("evento") or "").upper() == "CONTINUITY" and str(ant.get("evento") or "").upper() == "CONTINUITY"
            delta = round(atual["distancia_km"] - ant["distancia_km"], 1)
            vel = round(abs(delta) * 6.0, 1)
            plausivel = vel <= 250.0
            aproxima = delta <= -2.0
            passos.append({"valido": eventos_ok and plausivel, "delta_distancia_km": delta, "velocidade_centroide_implicita_km_h": vel, "continuidade": eventos_ok, "plausivel": plausivel, "aproxima": aproxima})
        def gate(n):
            if len(passos) < n: return False
            q = passos[:n]
            return all(x.get("valido") and x.get("aproxima") for x in q)
        p30, p60 = gate(3), gate(6)
        s["persistencia_30min"] = "CONFIRMADA" if p30 else "NAO_CONFIRMADA"
        s["persistencia_60min"] = "CONFIRMADA" if p60 else "NAO_CONFIRMADA"
        s["passos_temporais_avaliados"] = passos
        s["trajetoria_persistente_gate"] = "PERSISTENTE_60MIN" if p60 else ("PERSISTENTE_30MIN" if p30 else "NAO_PERSISTENTE")
    return sistemas


def processar(payload, horario_produto=None, url=None, tentativas=None, payload_anterior=None, horario_anterior=None, url_anterior=None, historico_quadros=None):
    agora = datetime.now(UTC)
    sistemas = []
    for f in (payload or {}).get("features", []):
        x = normalizar(f)
        if x:
            sistemas.append(x)
    sistemas = aplicar_tendencia_observada(sistemas, payload_anterior)
    sistemas = aplicar_persistencia_temporal(sistemas, historico_quadros or [])
    sistemas.sort(key=lambda x: x["distancia_joinville_km"])
    sinotica = confirmar_ecmwf_850(sistemas, horario_produto)
    aproximando = [x for x in sistemas if x["tendencia_distancia_observada"] == "APROXIMANDO_OBSERVADO_CONTINUO"]
    aproximando.sort(key=lambda x: x["distancia_joinville_km"])
    confirmados = [x for x in aproximando if x.get("confirmacao_sinotica_850hpa") == "APOIA_CORREDOR_PARA_JOINVILLE"]
    persist30 = [x for x in sistemas if x.get("persistencia_30min") == "CONFIRMADA"]
    persist60 = [x for x in sistemas if x.get("persistencia_60min") == "CONFIRMADA"]
    persist30_sinotica = [x for x in persist30 if x.get("confirmacao_sinotica_850hpa") == "APOIA_CORREDOR_PARA_JOINVILLE"]
    return {
        "versao": "#174-F",
        "status": "experimental_dados_processados",
        "uso_operacional": False,
        "fonte": "CPTEC/INPE DSAT - GOES-19 / TATHU",
        "familia_metodo": "FORTRACC/TATHU",
        "gerado_em_utc": agora.isoformat(),
        "produto_horario_utc": horario_produto.isoformat() if horario_produto else None,
        "produto_horario_local": horario_produto.astimezone(FUSO).isoformat() if horario_produto else None,
        "url_produto": url,
        "referencia": {"local": "Joinville/SC - coordenada publica aproximada", "lat": LAT_JOINVILLE, "lon": LON_JOINVILLE},
        "dominio_triagem": {"lat_min": -60, "lat_max": 5, "lon_min": -100, "lon_max": -20},
        "sistemas_no_dominio": len(sistemas),
        "sistemas_geometricamente_compativeis": None,
        "sistemas_aproximando_observado_continuo": len(aproximando),
        "sistemas_aproximando_com_apoio_sinotico_850hpa": len(confirmados),
        "sistemas_persistencia_30min_confirmada": len(persist30),
        "sistemas_persistencia_60min_confirmada": len(persist60),
        "sistemas_persistencia_30min_com_apoio_sinotico": len(persist30_sinotica),
        "sistema_aproximando_mais_proximo": aproximando[0] if aproximando else None,
        "confirmacao_sinotica": sinotica,
        "quadro_anterior_horario_utc": horario_anterior.isoformat() if horario_anterior else None,
        "quadro_anterior_url": url_anterior,
        "sistemas": sistemas,
        "tentativas_fonte": tentativas or [],
        "regras_seguranca": [
            "Alinhamento angular isolado nao significa que o sistema chegara a Joinville.",
            "Aproximacao observada exige mesmo ID, evento CONTINUITY, dois quadros e reducao de distancia superior a banda morta de 2 km.",
            "MERGE, SPLIT e SPONTANEOUS_GENERATION nunca sustentam trajetoria continua.",
            "Deslocamento de centroide acima de 250 km/h e rejeitado como salto incompativel neste gate experimental.",
            "ECMWF 850 hPa e confirmacao sinotica auxiliar; vento meteorologico DE e convertido para vetor PARA antes da comparacao.",
            "Persistencia de 30 min exige 3 passos consecutivos de 10 min, todos CONTINUITY, plausiveis e aproximando >=2 km por passo.",
            "Persistencia de 60 min exige 6 passos consecutivos sob a mesma regra.",
            "ETA permanece bloqueado no #174-F.",
            "Vel do TATHU e preservado e convertido de m/s para km/h apenas como diagnostico; Vel=0 invalida o vetor direcional.",
            "Valores sentinela <= -900 sao tratados como ausentes.",
            "Ausencia/erro da fonte nunca significa ausencia de tempestade.",
            "#174-F nao altera dados.json, nao dispara alerta e nao substitui Defesa Civil/INMET/CPTEC.",
            "FAVORAVEL, CONTRARIO e FONTE_INDISPONIVEL sao estados distintos; indisponibilidade jamais conta como rejeicao meteorologica.",
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", help="GeoJSON TATHU local para teste reprodutivel")
    ap.add_argument("--saida", default=SAIDA_PADRAO)
    ap.add_argument("--timeout", type=float, default=4.0, help="Timeout HTTP por tentativa em segundos")
    ap.add_argument("--tentativas", type=int, default=13, help="Quantidade maxima de quadros de 10 min a procurar")
    args = ap.parse_args()

    if args.entrada:
        payload = json.loads(Path(args.entrada).read_text(encoding="utf-8"))
        resultado = processar(payload)
    else:
        payload, horario, url, tentativas = buscar_ultimo(timeout=max(1.0, args.timeout), max_tentativas=max(1, min(args.tentativas, 25)))
        if payload is None:
            resultado = {
                "versao": "#174-F", "status": "fonte_indisponivel_fail_closed",
                "uso_operacional": False, "fonte": "CPTEC/INPE DSAT - GOES-19 / TATHU",
                "sistemas_no_dominio": None, "sistemas_geometricamente_compativeis": None,
                "sistema_compativel_mais_proximo": None, "sistemas": [], "tentativas_fonte": tentativas,
                "regra_seguranca": "Falha de consulta nao equivale a ausencia de tempestade."
            }
        else:
            # #174-F: preserva a janela de persistência de 60 min do #174-E (janela de 60 min).
            # Não pula lacunas: quadro ausente quebra a persistência, em fail-closed.
            historico = []
            for passo in range(1, 7):
                hh = horario - timedelta(minutes=10 * passo)
                uu = TATHU_BASE + hh.strftime("%Y/%m/") + "goes19_diagnostic_" + hh.strftime("%Y%m%d%H%M") + ".json"
                pp = None
                try:
                    rr = requests.get(uu, timeout=max(1.0, args.timeout), headers={"User-Agent": "Monitor-Guaxanduva/174-F"})
                    if rr.status_code == 200:
                        candidato = rr.json()
                        if isinstance(candidato, dict) and isinstance(candidato.get("features"), list):
                            pp = candidato
                except Exception:
                    pp = None
                historico.append((hh, pp, uu))
            horario_anterior, payload_anterior, url_anterior = historico[0]
            resultado = processar(payload, horario, url, tentativas, payload_anterior, horario_anterior if payload_anterior else None, url_anterior if payload_anterior else None, historico)

    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: resultado.get(k) for k in ("versao", "status", "sistemas_no_dominio", "sistemas_geometricamente_compativeis")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
