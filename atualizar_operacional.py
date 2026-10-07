#!/usr/bin/env python3
"""Atualização operacional rápida do Monitor Guaxanduva."""
import json
import time
import math
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
    construir_estatisticas_automaticas_186, get, LAT, LON, hav,
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
    raio_eco=next((r for r in (2,5,10,25) if (por_raio.get(str(r)) or {}).get("eco_qualitativo_detectado") is True),None)
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
    dados.update({"gerado_em":agora().isoformat(),"previsao":previsao,"malha_meteorologica_207_r2":malha207r,"mare":mare,"radar":radar,"chuva":cemaden,"chuva_observada_cemaden_144":cemaden144,"chuva_observada_epagri_165":epagri,"rede_pluviometrica_multifonte_165":rede,"geometria_rede_observacional_172":geometria,"chuva_observada_inmet":inmet,"mare_observada_joinville_160":mare160,"historico_hidrometeorologico_guaxanduva_166":h166,"hidrologia_guaxanduva_v019":h019,"nivel_guaxanduva_v021":v021,"criterio_hidrometeorologico_plancon_163":criterio163,"mare_prevista_24h_164":mare164,"projecao_guaxanduva_174":proj174,"liberacao_experimental_168":liberacao168,"diagnostico_cap_recente_inmet_155":cap155,"diagnostico_conteudo_cap_inmet_156":cap156,"granizo":granizo,"super_el_nino_173":super_el_nino173,"impactos_locais_173":impactos173,"estado_canonico_operacional":estado_canonico,"estado_agora_operacional":estado_operacional,"validacao_campo_guaxanduva":{"versao":"GXA-CAMPO-207-G","status":"serie_de_calibracao_em_formacao","natureza":"MEDICAO_MANUAL_DE_CAMPO","referencia_historica_2026_10_03_m":0.607,"referencia_historica_status":"HIPOTESE_DE_CALIBRACAO_A_REAVALIAR","regra":"0,607 m e preservado como calibracao historica de 03/10; novas medicoes formam a serie #207-G e nao recalibram automaticamente o V0.21.","medicoes":[{"data":"2026-10-03","nivel_m":1.34,"origem":"medicao_manual_usuario"},{"data":"2026-10-03","hora_local":"15:49","timezone":"America/Sao_Paulo","nivel_m":1.33,"origem":"medicao_manual_usuario"},{"data":"2026-10-07","hora_local_aproximada":"12:50","timezone":"America/Sao_Paulo","nivel_m":1.75,"origem":"medicao_manual_usuario","condicao_visual":"agua_aparentemente_parada"}],"quantidade_medicoes":3,"maturidade":"AMOSTRA_EM_FORMACAO","uso_operacional":False,"altera_v021":False},"estatisticas_automaticas_186":estat186,"atualizacao_operacional_rapida":{"status":"concluida","gerado_em":agora().isoformat(),"objetivo":"Atualizar meteorologia/radar antes das auditorias científicas pesadas.","fail_closed":True}})
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
