#!/usr/bin/env python3
"""#174-A — Monitor Oceânico experimental do Monitor Guaxanduva.

Lê o diagnóstico GOES-19/TATHU do CPTEC/INPE, faz triagem ampla de sistemas
convectivos no entorno da América do Sul e calcula, de forma fail-closed,
distância, rumo para Joinville, compatibilidade angular e ETA cinemático
SOMENTE quando velocidade/direção são válidas.

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
    vel_kmh = None if vel_ms is None else vel_ms * 3.6
    dif = None if direcao is None else diferenca_angular(direcao, rumo)

    if dif is None:
        compat = "SEM_VETOR_VALIDO"
    elif dif <= 30:
        compat = "FORTE_COMPATIBILIDADE_GEOMETRICA"
    elif dif <= 60:
        compat = "COMPATIBILIDADE_GEOMETRICA_PARCIAL"
    elif dif <= 100:
        compat = "TRAJETORIA_LATERAL"
    else:
        compat = "AFASTAMENTO_GEOMETRICO"

    # ETA puramente cinemático; não é previsão meteorológica. Restrito para
    # evitar extrapolação absurda de sistemas muito distantes/lentos.
    eta_h = None
    if vel_kmh and vel_kmh >= 5 and dif is not None and dif <= 45 and dist <= 2000:
        eta_h = dist / vel_kmh
        if eta_h > 72:
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
        "fracao_convectiva_pct": numero(p.get("FracConv")),
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


def processar(payload, horario_produto=None, url=None, tentativas=None):
    agora = datetime.now(UTC)
    sistemas = []
    for f in (payload or {}).get("features", []):
        x = normalizar(f)
        if x:
            sistemas.append(x)
    sistemas.sort(key=lambda x: x["distancia_joinville_km"])
    compativeis = [x for x in sistemas if x["compatibilidade_trajetoria"] in {
        "FORTE_COMPATIBILIDADE_GEOMETRICA", "COMPATIBILIDADE_GEOMETRICA_PARCIAL"
    }]
    return {
        "versao": "#174-A",
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
        "sistemas_geometricamente_compativeis": len(compativeis),
        "sistema_compativel_mais_proximo": compativeis[0] if compativeis else None,
        "sistemas": sistemas,
        "tentativas_fonte": tentativas or [],
        "regras_seguranca": [
            "Compatibilidade angular nao significa que o sistema chegara a Joinville.",
            "ETA cinemático usa apenas distancia/velocidade instantaneas e nao e previsao meteorologica.",
            "Vel do TATHU e tratado como m/s e convertido explicitamente para km/h por fator 3.6.",
            "Valores sentinela <= -900 sao tratados como ausentes.",
            "Ausencia/erro da fonte nunca significa ausencia de tempestade.",
            "#174-A nao altera dados.json, nao dispara alerta e nao substitui Defesa Civil/INMET/CPTEC.",
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
                "versao": "#174-A", "status": "fonte_indisponivel_fail_closed",
                "uso_operacional": False, "fonte": "CPTEC/INPE DSAT - GOES-19 / TATHU",
                "sistemas_no_dominio": None, "sistemas_geometricamente_compativeis": None,
                "sistema_compativel_mais_proximo": None, "sistemas": [], "tentativas_fonte": tentativas,
                "regra_seguranca": "Falha de consulta nao equivale a ausencia de tempestade."
            }
        else:
            resultado = processar(payload, horario, url, tentativas)

    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: resultado.get(k) for k in ("versao", "status", "sistemas_no_dominio", "sistemas_geometricamente_compativeis")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
