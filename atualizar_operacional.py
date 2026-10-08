#!/usr/bin/env python3
"""Atualização operacional rápida do Monitor Guaxanduva."""
import json
import time
import math
from io import BytesIO
from PIL import Image
from datetime import datetime
from pathlib import Path
from atualizar_dados import (
    agora, buscar_previsao, buscar_radar, buscar_chuva_cemaden_136,
    chuva_observada_cemaden_144, buscar_chuva_epagri_165,
    construir_rede_pluviometrica_multifonte_165,
    construir_geometria_rede_observacional_172, buscar_chuva_observada_inmet,
    buscar_mare, buscar_mare_observada_joinville_160,
    atualizar_historico_guaxanduva_166, calcular_hidrologia_guaxanduva_v019,
    calcular_nivel_guaxanduva_v021, calcular_criterio_hidrometeorologico_plancon_163,
    calcular_pico_mare_previsto_24h_164, projetar_guaxanduva_24h_174,
    construir_liberacao_experimental_168, construir_impactos_locais_173_a2,
    diagnosticar_cap_recente_inmet_155, diagnosticar_conteudo_cap_inmet_156,
    granizo_operacional_inmet_157, buscar_super_el_nino_173,
    construir_estatisticas_automaticas_186, get, LAT, LON, hav, IMAGEM,
    _mapa_classes_dbz_170, _amostrar_estacao_na_imagem_170,
    _diagnostico_espacial_estacao_170_b3,
)
ARQUIVO = Path("dados.json")

def seguro(nome, func):
    inicio = time.monotonic()
    try:
        resultado = func()
        print(f"[PERF #208.1] {nome}: {time.monotonic()-inicio:.2f}s", flush=True)
        return resultado
    except Exception as exc:
        print(f"[PERF #208.1] {nome}: FALHA após {time.monotonic()-inicio:.2f}s — {exc}", flush=True)
        return {"status":"indisponivel","erro":str(exc),
                "regra_seguranca":"Falha de coleta não equivale a ausência do fenômeno.",
                "fonte_operacional":nome}

def super_el_nino_operacional(dados, max_idade_h=3.0):
    """Evita 12+ consultas climáticas pesadas a cada ciclo de 15 min.

    ENSO/PMEL/OISST não é variável de alerta instantâneo. Reutiliza o último
    bloco oficial por até 3 h, preservando seu timestamp original. Depois
    disso a coleta oficial é refeita normalmente. Nenhum valor é inventado.
    """
    anterior = dados.get("super_el_nino_173") if isinstance(dados, dict) else None
    if isinstance(anterior, dict):
        bruto = anterior.get("coletado_em")
        try:
            instante = datetime.fromisoformat(str(bruto).replace("Z", "+00:00"))
            atual = agora()
            if instante.tzinfo is None:
                instante = instante.replace(tzinfo=atual.tzinfo)
            idade_h = max(0.0, (atual - instante.astimezone(atual.tzinfo)).total_seconds()/3600.0)
            if idade_h <= max_idade_h:
                copia = dict(anterior)
                copia["cache_operacional_208_1"] = True
                copia["idade_cache_operacional_h"] = round(idade_h, 2)
                copia["regra_cache_operacional"] = "ENSO/PMEL/OISST reutilizado por no máximo 3 h; timestamp oficial original preservado."
                return copia
        except Exception:
            pass
    novo = buscar_super_el_nino_173()
    if isinstance(novo, dict):
        novo["cache_operacional_208_1"] = False
    return novo


def construir_malha_modelada_207_r():
    """#207-R2: segunda camada modelada para TODOS os raios operacionais.

    Consulta uma unica vez uma malha centro + 8 azimutes nos raios
    2/5/10/25/50 km. O resultado e SUPORTE MODELADO, nunca observacao.
    """
    raios=(2,5,10,25,50)
    azimutes=(0,45,90,135,180,225,270,315)
    pontos=[{"id":"centro","raio_km":0,"azimute_graus":None,"latitude":LAT,"longitude":LON}]
    r_terra=6371.0088
    lat1=math.radians(LAT); lon1=math.radians(LON)
    for raio in raios:
        for az in azimutes:
            brng=math.radians(az); delta=raio/r_terra
            lat2=math.asin(math.sin(lat1)*math.cos(delta)+math.cos(lat1)*math.sin(delta)*math.cos(brng))
            lon2=lon1+math.atan2(math.sin(brng)*math.sin(delta)*math.cos(lat1),math.cos(delta)-math.sin(lat1)*math.sin(lat2))
            pontos.append({"id":f"r{raio}_{az:03d}","raio_km":raio,"azimute_graus":az,"latitude":round(math.degrees(lat2),6),"longitude":round(math.degrees(lon2),6)})
    params={
        "latitude":",".join(str(p["latitude"]) for p in pontos),
        "longitude":",".join(str(p["longitude"]) for p in pontos),
        "current":"precipitation,rain,showers,weather_code",
        "hourly":"precipitation,precipitation_probability",
        "forecast_hours":2,
        "timezone":"America/Sao_Paulo",
    }
    resposta=get("https://api.open-meteo.com/v1/forecast",params).json()
    blocos=resposta if isinstance(resposta,list) else [resposta]
    leituras=[]
    for i,ponto in enumerate(pontos):
        bloco=blocos[i] if i<len(blocos) and isinstance(blocos[i],dict) else {}
        cur=bloco.get("current") or {}; hor=bloco.get("hourly") or {}
        probs=hor.get("precipitation_probability") or []; precs=hor.get("precipitation") or []
        leitura=dict(ponto)
        leitura.update({
            "modelo_latitude":bloco.get("latitude"),"modelo_longitude":bloco.get("longitude"),
            "horario_modelo":cur.get("time"),"intervalo_s":cur.get("interval"),
            "precipitacao_atual_mm":cur.get("precipitation"),"chuva_atual_mm":cur.get("rain"),"pancadas_atual_mm":cur.get("showers"),
            "codigo_tempo":cur.get("weather_code"),
            "precipitacao_proxima_hora_mm":precs[0] if precs else None,
            "probabilidade_proxima_hora_pct":probs[0] if probs else None,
            "natureza":"MODELADO_NAO_OBSERVACIONAL",
        })
        leituras.append(leitura)
    por_raio={}
    for raio in raios:
        # cumulativo: centro + todos os pontos dos aneis internos ate o raio
        grupo=[x for x in leituras if x["raio_km"]<=raio]
        atuais=[float(x["precipitacao_atual_mm"]) for x in grupo if isinstance(x.get("precipitacao_atual_mm"),(int,float))]
        futuras=[float(x["precipitacao_proxima_hora_mm"]) for x in grupo if isinstance(x.get("precipitacao_proxima_hora_mm"),(int,float))]
        probs=[float(x["probabilidade_proxima_hora_pct"]) for x in grupo if isinstance(x.get("probabilidade_proxima_hora_pct"),(int,float))]
        positivos=[x for x in grupo if isinstance(x.get("precipitacao_atual_mm"),(int,float)) and float(x["precipitacao_atual_mm"])>0]
        por_raio[str(raio)]={
            "raio_km":raio,"pontos_consultados":len(grupo),"pontos_com_precipitacao_modelada_agora":len(positivos),
            "precipitacao_modelada_atual_max_mm":round(max(atuais),3) if atuais else None,
            "precipitacao_modelada_proxima_hora_max_mm":round(max(futuras),3) if futuras else None,
            "probabilidade_proxima_hora_max_pct":round(max(probs),1) if probs else None,
            "suporte_modelado_precipitacao_agora":bool(positivos),
            "natureza":"SUPORTE_MODELADO_NAO_CONFIRMATORIO",
        }
    return {
        "status":"online" if leituras else "indisponivel","versao":"#207-R2",
        "fonte":"Open-Meteo Weather Forecast API","referencia":{"latitude":LAT,"longitude":LON},
        "raios_km":list(raios),"desenho_malha":"centro + 8 azimutes por anel; resumo cumulativo por raio",
        "por_raio":por_raio,"pontos":leituras,
        "regra_seguranca":"Segunda camada por coordenadas. Modelo/previsao apenas corrobora contexto meteorologico quando a cobertura observacional e insuficiente; nunca vira pluviometro, chuva observada ou RADAR_CONFIRMADO.",
        "gerado_em":agora().isoformat(),
    }


def construir_pareamento_espacial_207_r4(radar, rede):
    """#207-R4: RadarSC x modelo x pluviometro na coordenada da estacao.

    Usa somente o quadro RadarSC mais recente ja selecionado por buscar_radar().
    O radar e amostrado no ponto da estacao (janela 5x5) e tambem procura o eco
    oficial mais proximo em ate 40 px. O Open-Meteo e consultado nas MESMAS
    coordenadas. Apenas pluviometro fresco com produto 1 h comparavel e
    observacao; modelo nunca confirma chuva no solo e nenhuma relacao Z-R e
    liberada aqui.
    """
    saida={
        "versao":"#207-R4","status":"indisponivel","natureza":"PAREAMENTO_ESPACIAL_EXPERIMENTAL_FAIL_CLOSED",
        "estacoes":[],"resumo":{},"uso_operacional":False,"radar_confirmado":False,
        "libera_calibracao_zr":False,"libera_conversao_dbz_mm_h":False,
        "regra_seguranca":"Coincidencia RadarSC 5x5 + chuva observada 1 h na estacao e evidencia espacial forte, mas permanece experimental e nao libera Z-R/dBZ->mm/h. Open-Meteo e apenas suporte modelado."
    }
    if not isinstance(radar,dict) or radar.get("status")!="online" or radar.get("dados_frescos") is not True:
        saida["status"]="bloqueado_radar_indisponivel_ou_antigo"; return saida
    quadros=radar.get("quadros") or []
    validos=[q for q in quadros if isinstance(q,dict) and q.get("download")=="ok" and q.get("arquivo")]
    if not validos:
        saida["status"]="bloqueado_sem_quadro_radar_valido"; return saida
    ultimo=validos[-1]; nome=ultimo.get("arquivo")
    classes=_mapa_classes_dbz_170(radar)
    if not classes:
        saida["status"]="bloqueado_paleta_dbz_nao_validada"; return saida
    bruto=get(IMAGEM,{"prod":4,"radar":"COMP","file":nome},True).content
    imagem=Image.open(BytesIO(bruto)).convert("RGBA")

    candidatos=[]
    for e in (rede or {}).get("estacoes",[]):
        if not isinstance(e,dict) or e.get("aquisicao_automatica_integrada") is not True: continue
        lat,lon=e.get("latitude"),e.get("longitude")
        if not isinstance(lat,(int,float)) or isinstance(lat,bool) or not isinstance(lon,(int,float)) or isinstance(lon,bool): continue
        dist=e.get("distancia_comasa_aprox_km")
        if not isinstance(dist,(int,float)): dist=hav(LAT,LON,float(lat),float(lon))
        if float(dist)>50: continue
        candidatos.append((e,float(lat),float(lon),float(dist)))
    if not candidatos:
        saida["status"]="bloqueado_sem_estacoes_integradas_georreferenciadas_50km"; return saida

    params={
        "latitude":",".join(str(round(x[1],6)) for x in candidatos),
        "longitude":",".join(str(round(x[2],6)) for x in candidatos),
        "current":"precipitation,rain,showers,weather_code",
        "hourly":"precipitation,precipitation_probability","forecast_hours":2,
        "timezone":"America/Sao_Paulo",
    }
    resposta=get("https://api.open-meteo.com/v1/forecast",params).json()
    blocos=resposta if isinstance(resposta,list) else [resposta]

    for i,(e,lat,lon,dist) in enumerate(candidatos):
        amostra=_amostrar_estacao_na_imagem_170(imagem,lat,lon,classes)
        prox=_diagnostico_espacial_estacao_170_b3(imagem,lat,lon,classes,raio_max_px=40)
        bloco=blocos[i] if i<len(blocos) and isinstance(blocos[i],dict) else {}
        cur=bloco.get("current") or {}; hor=bloco.get("hourly") or {}
        precs=hor.get("precipitation") or []; probs=hor.get("precipitation_probability") or []
        obs_ok=e.get("leitura_1h_comparavel") is True and isinstance(e.get("precipitacao_1h_mm"),(int,float)) and not isinstance(e.get("precipitacao_1h_mm"),bool)
        obs=float(e.get("precipitacao_1h_mm")) if obs_ok else None
        eco_ponto=amostra.get("eco_oficial_detectado_5x5") is True
        modelo_agora=cur.get("precipitation") if isinstance(cur.get("precipitation"),(int,float)) else None
        classe=("COINCIDENCIA_RADAR_CHUVA_OBSERVADA_NO_PONTO" if eco_ponto and obs is not None and obs>0 else
                "ECO_NO_PONTO_SEM_CHUVA_1H_OBSERVADA" if eco_ponto and obs is not None else
                "ECO_NO_PONTO_SEM_OBSERVACAO_1H_COMPARAVEL" if eco_ponto else
                "CHUVA_OBSERVADA_SEM_ECO_5X5" if obs is not None and obs>0 else
                "SEM_COINCIDENCIA_RADAR_CHUVA_NO_PONTO")
        saida["estacoes"].append({
            "nome":e.get("nome"),"rede":e.get("rede") or e.get("fonte"),"codigo":e.get("codigo"),
            "latitude":round(lat,6),"longitude":round(lon,6),"distancia_guaxanduva_km":round(dist,3),
            "radar":{"arquivo":nome,"horario_local":ultimo.get("horario_local"),**amostra,
                     "eco_mais_proximo_ate_40px":prox.get("eco_oficial_mais_proximo")},
            "observacao":{"leitura_1h_comparavel":obs_ok,"precipitacao_1h_mm":obs,
                          "horario_medicao":e.get("horario_medicao"),"dados_frescos":e.get("dados_frescos")},
            "modelo":{"horario":cur.get("time"),"precipitacao_atual_mm":modelo_agora,
                      "precipitacao_proxima_hora_mm":precs[0] if precs else None,
                      "probabilidade_proxima_hora_pct":probs[0] if probs else None,
                      "natureza":"MODELADO_NAO_OBSERVACIONAL"},
            "classificacao_experimental":classe,"confirma_radar_operacionalmente":False,
        })
    coinc=[x for x in saida["estacoes"] if x["classificacao_experimental"]=="COINCIDENCIA_RADAR_CHUVA_OBSERVADA_NO_PONTO"]
    eco=[x for x in saida["estacoes"] if (x.get("radar") or {}).get("eco_oficial_detectado_5x5") is True]
    obspos=[x for x in saida["estacoes"] if isinstance((x.get("observacao") or {}).get("precipitacao_1h_mm"),(int,float)) and x["observacao"]["precipitacao_1h_mm"]>0]
    modpos=[x for x in saida["estacoes"] if isinstance((x.get("modelo") or {}).get("precipitacao_atual_mm"),(int,float)) and x["modelo"]["precipitacao_atual_mm"]>0]
    saida["resumo"]={"estacoes_pareadas":len(saida["estacoes"]),"estacoes_com_eco_5x5":len(eco),"estacoes_com_chuva_observada_1h":len(obspos),"estacoes_com_modelo_chuva_agora":len(modpos),"coincidencias_radar_chuva_observada_5x5":len(coinc),"coincidencias_nomes":[x.get("nome") for x in coinc]}
    saida["status"]="coleta_experimental_concluida"
    saida["quadro_radar"]={"arquivo":nome,"horario_local":ultimo.get("horario_local")}
    saida["gerado_em"]=agora().isoformat()
    return saida

def construir_auditoria_pixel_eco_207_r5(radar, rede):
    """#207-R5 — parte do próprio RGB mais próximo e procura evidência independente.

    Não presume que uma cor da paleta operacional represente chuva. O RGB é
    tratado como observação bruta do PNG; modelo e pluviômetro são camadas
    independentes. Fail-closed por construção.
    """
    saida={
        "versao":"#207-R5","status":"indisponivel",
        "natureza":"AUDITORIA_RGB_RADAR_X_MODELO_X_PLUVIOMETRO_FAIL_CLOSED",
        "uso_operacional":False,"radar_confirmado":False,
        "libera_calibracao_zr":False,"libera_conversao_dbz_mm_h":False,
        "regra_seguranca":"RGB do PNG RadarSC é observação bruta. Cor sem vínculo documental C1-C16 permanece com significado meteorológico em validação; modelo não confirma chuva no solo."
    }
    if not isinstance(radar,dict) or radar.get("status")!="online" or radar.get("dados_frescos") is not True:
        saida["status"]="bloqueado_radar_indisponivel_ou_antigo"; return saida
    quadros=[q for q in (radar.get("quadros") or []) if isinstance(q,dict) and q.get("download")=="ok"]
    if not quadros:
        saida["status"]="bloqueado_sem_quadro_radar_valido"; return saida
    q=quadros[-1]
    diag=q.get("eco_oficial_local_129") or {}
    alvo=diag.get("eco_oficial_mais_proximo") if isinstance(diag,dict) else None
    if not isinstance(alvo,dict) or not isinstance(alvo.get("latitude"),(int,float)) or not isinstance(alvo.get("longitude"),(int,float)):
        saida["status"]="sem_rgb_candidato_ate_25km"; saida["quadro_radar"]={"arquivo":q.get("arquivo"),"horario_local":q.get("horario_local")}; return saida
    lat=float(alvo["latitude"]); lon=float(alvo["longitude"]); rgb=alvo.get("rgb"); classe=alvo.get("classe")
    # Modelo exatamente na coordenada do RGB/pixel, não agregado por círculo.
    bloco=get("https://api.open-meteo.com/v1/forecast",{
        "latitude":lat,"longitude":lon,
        "current":"precipitation,rain,showers,weather_code",
        "hourly":"precipitation,precipitation_probability","forecast_hours":2,
        "timezone":"America/Sao_Paulo",
    }).json()
    cur=bloco.get("current") or {}; hor=bloco.get("hourly") or {}
    precs=hor.get("precipitation") or []; probs=hor.get("precipitation_probability") or []
    # Estação integrada mais próxima do próprio pixel candidato.
    ests=[]
    for e in (rede or {}).get("estacoes",[]):
        if not isinstance(e,dict) or e.get("aquisicao_automatica_integrada") is not True: continue
        ela,elo=e.get("latitude"),e.get("longitude")
        if not isinstance(ela,(int,float)) or isinstance(ela,bool) or not isinstance(elo,(int,float)) or isinstance(elo,bool): continue
        ests.append((hav(lat,lon,float(ela),float(elo)),e))
    ests.sort(key=lambda x:x[0])
    prox=None
    if ests:
        d,e=ests[0]
        obs_ok=e.get("leitura_1h_comparavel") is True and isinstance(e.get("precipitacao_1h_mm"),(int,float)) and not isinstance(e.get("precipitacao_1h_mm"),bool)
        prox={"nome":e.get("nome"),"rede":e.get("rede") or e.get("fonte"),"codigo":e.get("codigo"),
              "latitude":e.get("latitude"),"longitude":e.get("longitude"),"distancia_ao_rgb_km":round(d,3),
              "leitura_1h_comparavel":obs_ok,"precipitacao_1h_mm":float(e.get("precipitacao_1h_mm")) if obs_ok else None,
              "horario_medicao":e.get("horario_medicao"),"dados_frescos":e.get("dados_frescos")}
    modelo_agora=cur.get("precipitation") if isinstance(cur.get("precipitation"),(int,float)) else None
    # Sem classe C1-C16, a cor não recebe significado de precipitação.
    status_cor="RGB_COM_CLASSE_C1_C16_DOCUMENTADA" if classe is not None else "RGB_OBSERVADO_SIGNIFICADO_EM_VALIDACAO"
    saida.update({
        "status":"coleta_experimental_concluida","gerado_em":agora().isoformat(),
        "quadro_radar":{"arquivo":q.get("arquivo"),"horario_local":q.get("horario_local")},
        "rgb_alvo":{"rgb":rgb,"classe_c1_c16":classe,"status_interpretacao":status_cor,
                    "latitude":round(lat,6),"longitude":round(lon,6),
                    "distancia_guaxanduva_km":alvo.get("distancia_comasa_km")},
        "modelo_no_rgb":{"horario":cur.get("time"),"precipitacao_atual_mm":modelo_agora,
                         "precipitacao_proxima_hora_mm":precs[0] if precs else None,
                         "probabilidade_proxima_hora_pct":probs[0] if probs else None,
                         "natureza":"MODELADO_NAO_OBSERVACIONAL"},
        "pluviometro_mais_proximo_do_rgb":prox,
        "interpretacao_experimental":(
            "RGB_COM_SUPORTE_MODELADO_AGORA" if isinstance(modelo_agora,(int,float)) and modelo_agora>0 else
            "RGB_SEM_SUPORTE_MODELADO_AGORA"
        ),
    })
    return saida

def main():
    try:
        dados=json.loads(ARQUIVO.read_text(encoding="utf-8"))
        if not isinstance(dados,dict): dados={}
    except Exception: dados={}
    previsao=seguro("Open-Meteo",buscar_previsao)
    malha207r=seguro("malha modelada #207-R2",construir_malha_modelada_207_r)
    radar=seguro("RadarSC",buscar_radar)
    cemaden=seguro("CEMADEN",buscar_chuva_cemaden_136)
    cemaden144=seguro("CEMADEN #144",lambda:chuva_observada_cemaden_144(cemaden))
    epagri=seguro("EPAGRI/CIRAM",buscar_chuva_epagri_165)
    rede=seguro("rede multifonte #165",lambda:construir_rede_pluviometrica_multifonte_165(cemaden,epagri))
    geometria=seguro("geometria #172",lambda:construir_geometria_rede_observacional_172(rede))
    pareamento207r4=seguro("pareamento espacial #207-R4",lambda:construir_pareamento_espacial_207_r4(radar,rede))
    auditoria207r5=seguro("auditoria RGB/pixel #207-R5",lambda:construir_auditoria_pixel_eco_207_r5(radar,rede))
    inmet=seguro("INMET",buscar_chuva_observada_inmet)
    mare=seguro("tábua de maré prevista",buscar_mare)
    mare160=seguro("maré observada #160",buscar_mare_observada_joinville_160)
    h166=seguro("histórico Guaxanduva #166",lambda:atualizar_historico_guaxanduva_166(epagri,mare160))
    h019=seguro("hidrologia Guaxanduva V0.19",calcular_hidrologia_guaxanduva_v019)
    v021=seguro("nível Guaxanduva V0.21",lambda:calcular_nivel_guaxanduva_v021(h166,h019))
    criterio163=seguro("critério hidrometeorológico #163",lambda:calcular_criterio_hidrometeorologico_plancon_163(previsao,mare160))
    mare164=seguro("maré prevista #164",lambda:calcular_pico_mare_previsto_24h_164(previsao))
    proj174=seguro("projeção Guaxanduva #174",lambda:projetar_guaxanduva_24h_174(previsao,mare160,mare164,v021,h019))
    tathu167=dados.get("goes19_tathu_167",{}) if isinstance(dados,dict) else {}
    liberacao168=seguro("liberação experimental #168",lambda:construir_liberacao_experimental_168(radar,tathu167,v021,mare160,mare164))
    cap155=seguro("CAP recente INMET #155",diagnosticar_cap_recente_inmet_155)
    cap156=seguro("conteúdo CAP INMET #156",lambda:diagnosticar_conteudo_cap_inmet_156(cap155))
    granizo=seguro("granizo operacional INMET #157",lambda:granizo_operacional_inmet_157(cap156))
    super_el_nino173=seguro("NOAA/CPC + PMEL #173/#185",lambda:super_el_nino_operacional(dados))
    impactos173=seguro("impactos locais #173",lambda:construir_impactos_locais_173_a2(previsao,granizo,mare160,mare164,criterio163,v021,super_el_nino173))
    estat186=seguro("estatísticas automáticas #186",construir_estatisticas_automaticas_186)
    estacoes_rede=rede.get("estacoes",[]) if isinstance(rede,dict) else []
    obs_frescas=[e for e in estacoes_rede if isinstance(e,dict) and e.get("dados_frescos") is True and e.get("leitura_atual_disponivel") is True and isinstance(e.get("precipitacao_1h_mm"),(int,float))]
    obs_max=max((float(e["precipitacao_1h_mm"]) for e in obs_frescas),default=None)
    obs_media=(sum(float(e["precipitacao_1h_mm"]) for e in obs_frescas)/len(obs_frescas)) if obs_frescas else None
    qrad={}
    if isinstance(radar,dict):
        quadros=radar.get("quadros") or []
        if quadros and isinstance(quadros[-1],dict): qrad=quadros[-1].get("classificacao_qualitativa_local_130") or {}
    por_raio=qrad.get("por_raio",{}) if isinstance(qrad,dict) else {}
    raio_eco=next((r for r in (2,5,10,25,50) if (por_raio.get(str(r)) or {}).get("eco_qualitativo_detectado") is True),None)
    radar_fresco=isinstance(radar,dict) and radar.get("status")=="online" and radar.get("dados_frescos") is True
    eco_local=radar_fresco and raio_eco is not None

    # #207-R — pareamento radial observacional, sem promover raio a coincidencia de pixel.
    # A rede EPAGRI dinamica fornece coordenadas oficiais do proprio Agroconnect.
    # Uma estacao positiva dentro do raio do eco reforca a evidencia de chuva na regiao,
    # mas RADAR_CONFIRMADO fica bloqueado ate existir amostragem do pixel do radar na estacao.
    obs_com_dist=[]
    for e in obs_frescas:
        d=e.get("distancia_guaxanduva_km")
        if not isinstance(d,(int,float)):
            try:
                lat=float(e.get("latitude")); lon=float(e.get("longitude"))
                from atualizar_dados import hav, LAT, LON
                d=hav(LAT,LON,lat,lon)
            except Exception: d=None
        if isinstance(d,(int,float)):
            obs_com_dist.append((float(d),e))
    obs_positivas=[(d,e) for d,e in obs_com_dist if float(e.get("precipitacao_1h_mm") or 0)>0]
    obs_no_raio_eco=[(d,e) for d,e in obs_positivas if eco_local and d<=float(raio_eco)]
    cobertura_no_raio=[(d,e) for d,e in obs_com_dist if eco_local and d<=float(raio_eco)]
    suporte_modelado_raio={}
    if eco_local and isinstance(malha207r,dict):
        suporte_modelado_raio=(malha207r.get("por_raio") or {}).get(str(raio_eco)) or {}
    modelo_sustenta_eco=bool(suporte_modelado_raio.get("suporte_modelado_precipitacao_agora"))

    if eco_local and obs_no_raio_eco:
        d,e=min(obs_no_raio_eco,key=lambda x:x[0])
        estado_agora="ECO_RADAR_COM_CHUVA_OBSERVADA_NO_MESMO_RAIO"
        mensagem_agora=(f"Eco qualitativo RadarSC em até {raio_eco} km e chuva observada por {e.get('rede') or e.get('fonte')} "
                        f"a {d:.1f} km do Guaxanduva ({float(e.get('precipitacao_1h_mm')):.1f} mm/1h). Evidência regional concordante; "
                        "ainda não classificada como RADAR CONFIRMADO porque falta coincidência com o pixel do eco.")
    elif eco_local and cobertura_no_raio:
        estado_agora="ECO_RADAR_NAO_CONFIRMADO_NO_SOLO"
        mensagem_agora=(f"Eco qualitativo RadarSC em até {raio_eco} km; há pluviômetro(s) fresco(s) nesse raio, mas sem chuva positiva nesta coleta. "
                        "Isso não prova erro do radar: o eco pode não coincidir com o ponto da estação.")
    elif eco_local and modelo_sustenta_eco:
        estado_agora="ECO_RADAR_COM_SUPORTE_MODELADO_SEM_OBSERVACAO_LOCAL"
        mensagem_agora=(f"Eco qualitativo RadarSC em até {raio_eco} km sem cobertura pluviometrica suficiente; a malha Open-Meteo por coordenadas indica precipitacao modelada dentro desse raio. "
                        "Evidencia apenas modelada: nao confirma chuva no solo nem valida o pixel do radar.")
    elif eco_local:
        estado_agora="ECO_RADAR_SEM_COBERTURA_PLUVIOMETRICA_SUFICIENTE"
        mensagem_agora=(f"Eco qualitativo RadarSC em até {raio_eco} km, porém sem pluviômetro fresco georreferenciado dentro do mesmo raio. "
                        "A segunda camada modelada tambem nao fornece confirmacao observacional; sem cobertura suficiente para confirmar ou contradizer o eco.")
    elif obs_max is not None and obs_max>0:
        estado_agora="CHUVA_OBSERVADA_REGIONAL_AGORA"; mensagem_agora=f"Rede regional registra chuva (máx. {obs_max:.1f} mm/1h); isso não equivale a medição no Comasa."
    else:
        estado_agora="SEM_CONFIRMACAO_LOCAL_DE_CHUVA"; mensagem_agora="Sem confirmação local suficiente nesta coleta; ausência de evidência não é tratada como ausência de chuva."
    estado_operacional={"status":estado_agora,"mensagem":mensagem_agora,"radar_fresco":radar_fresco,"eco_qualitativo_local":eco_local,"menor_raio_eco_km":raio_eco,"chuva_observada_regional_max_1h_mm":obs_max,"chuva_observada_regional_media_1h_mm":obs_media,"estacoes_regionais_frescas":len(obs_frescas),"estacoes_frescas_georreferenciadas":len(obs_com_dist),"estacoes_frescas_dentro_raio_eco":len(cobertura_no_raio),"estacoes_com_chuva_dentro_raio_eco":len(obs_no_raio_eco),"confirmacao_pixel_radar_estacao":False,"suporte_modelado_raio_eco":suporte_modelado_raio,"modelo_sustenta_eco":modelo_sustenta_eco,"chuva_modelo_openmeteo_mm":((previsao.get("atual") or {}).get("precipitacao_mm") if isinstance(previsao,dict) else None),"regra_seguranca":"#207-R: radar indica eco; pluviometros medem chuva em pontos. Concordancia no mesmo raio aumenta a evidencia regional, mas somente coincidencia espacial com o pixel do eco pode liberar RADAR_CONFIRMADO. Open-Meteo e contexto de modelo, nao prova observacional.","gerado_em":agora().isoformat()}
    estado_canonico={"gerado_em":agora().isoformat(),"rio":{"nivel_modelado_m":v021.get("nivel_estimado_m") if isinstance(v021,dict) else None,"faixa_m":v021.get("faixa_estimativa_m") if isinstance(v021,dict) else None,"tendencia":v021.get("tendencia") if isinstance(v021,dict) else None,"natureza":"MODELADO_NAO_INSTRUMENTAL","fonte":"GXA-V0.21"},"mare":{"observada_m":mare160.get("nivel_m") if isinstance(mare160,dict) else None,"horario_observado":mare160.get("horario") if isinstance(mare160,dict) else None,"proximo_extremo":mare.get("proximo") if isinstance(mare,dict) else None,"fonte":"EPAGRI/CIRAM"},"radar":{"status":radar.get("status") if isinstance(radar,dict) else "indisponivel","dados_frescos":radar_fresco,"eco_qualitativo_local":eco_local,"menor_raio_eco_km":raio_eco,"classe_dbz_atual":(liberacao168.get("radar_estimativa_quantitativa") or {}).get("classe_radar") if isinstance(liberacao168,dict) else None},"chuva":{"estado":estado_agora,"observada_regional_max_1h_mm":obs_max,"observada_regional_media_1h_mm":obs_media,"previsao_proxima_hora_mm":((previsao.get("proxima_hora") or {}).get("precipitacao_mm") if isinstance(previsao,dict) else None)}}
    dados.update({"gerado_em":agora().isoformat(),"previsao":previsao,"malha_meteorologica_207_r2":malha207r,"pareamento_espacial_radar_modelo_pluviometro_207_r4":pareamento207r4,"auditoria_rgb_pixel_radar_207_r5":auditoria207r5,"mare":mare,"radar":radar,"chuva":cemaden,"chuva_observada_cemaden_144":cemaden144,"chuva_observada_epagri_165":epagri,"rede_pluviometrica_multifonte_165":rede,"geometria_rede_observacional_172":geometria,"chuva_observada_inmet":inmet,"mare_observada_joinville_160":mare160,"historico_hidrometeorologico_guaxanduva_166":h166,"hidrologia_guaxanduva_v019":h019,"nivel_guaxanduva_v021":v021,"criterio_hidrometeorologico_plancon_163":criterio163,"mare_prevista_24h_164":mare164,"projecao_guaxanduva_174":proj174,"liberacao_experimental_168":liberacao168,"diagnostico_cap_recente_inmet_155":cap155,"diagnostico_conteudo_cap_inmet_156":cap156,"granizo":granizo,"super_el_nino_173":super_el_nino173,"impactos_locais_173":impactos173,"estado_canonico_operacional":estado_canonico,"estado_agora_operacional":estado_operacional,"validacao_campo_guaxanduva":{"versao":"GXA-CAMPO-207-G","status":"serie_de_calibracao_em_formacao","natureza":"MEDICAO_MANUAL_DE_CAMPO","referencia_historica_2026_10_03_m":0.607,"referencia_historica_status":"HIPOTESE_DE_CALIBRACAO_A_REAVALIAR","regra":"0,607 m e preservado como calibracao historica de 03/10; novas medicoes formam a serie #207-G e nao recalibram automaticamente o V0.21.","medicoes":[{"data":"2026-10-03","nivel_m":1.34,"origem":"medicao_manual_usuario"},{"data":"2026-10-03","hora_local":"15:49","timezone":"America/Sao_Paulo","nivel_m":1.33,"origem":"medicao_manual_usuario"},{"data":"2026-10-07","hora_local_aproximada":"12:50","timezone":"America/Sao_Paulo","nivel_m":1.75,"origem":"medicao_manual_usuario","condicao_visual":"agua_aparentemente_parada"}],"quantidade_medicoes":3,"maturidade":"AMOSTRA_EM_FORMACAO","uso_operacional":False,"altera_v021":False},"estatisticas_automaticas_186":estat186,"atualizacao_operacional_rapida":{"status":"concluida","gerado_em":agora().isoformat(),"objetivo":"Atualizar meteorologia/radar antes das auditorias científicas pesadas.","fail_closed":True}})
    # #187-A — compactação JSON sem perda de dados/estrutura.
    # #187-B — relatório espacial completo preservado em auditoria_espacial_170i.json.
    # O index.html não consulta esta cópia dentro de dados.json.
    dados.pop("auditoria_espacial_zr_170_i", None)

    # #187-D — contrato operacional mínimo do RadarSC.
    # Mantém a projeção leve do #187-C, mas preserva também os campos pequenos
    # consumidos pela Fusion #175 e a telemetria #176/#178 necessária à auditoria.
    # Estruturas volumosas (como "quadros" e "ultimo_quadro") continuam fora
    # do dados.json público para não reintroduzir a saturação removida no #187.
    if isinstance(dados.get("radar"), dict):
        _radar_completo_187d = dados["radar"]
        _campos_radar_operacionais_187d = (
            "status",
            "dados_frescos",
            "limite_frescor_min",
            "quadros_png_validos",
            "quantidade_quadros",
            "todos_png_validos",
            "dimensoes_consistentes",
            "horario_ultimo_quadro",
            "idade_ultimo_quadro_min",
            "diagnostico_lista_fonte_176",
            "timestamp_radar_178",
            "legenda_oficial",
            "validacao_paleta_radar",
            "dicionario_cores_130",
            "classificacao_qualitativa_local_130",
            "eco_oficial_local_129",
            "analise_movimento",
            "rastreamento_temporal",
            "avaliacao_trajetorias",
        )
        dados["radar"] = {
            campo: _radar_completo_187d[campo]
            for campo in _campos_radar_operacionais_187d
            if campo in _radar_completo_187d
        }

    ARQUIVO.write_text(json.dumps(dados,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    print("Atualização operacional rápida concluída:",dados["gerado_em"])
if __name__=="__main__": main()
