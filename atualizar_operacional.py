#!/usr/bin/env python3
"""Atualização operacional rápida do Monitor Guaxanduva.

Objetivo: publicar primeiro os campos que descrevem o estado meteorológico recente,
sem depender da longa bateria de auditorias científicas do atualizar_dados.py.
Falhas individuais permanecem explícitas e nunca são convertidas em zero.
"""
import json
from pathlib import Path
from atualizar_dados import (
    agora,
    buscar_previsao,
    buscar_radar,
    buscar_chuva_cemaden_136,
    chuva_observada_cemaden_144,
    buscar_chuva_epagri_165,
    construir_rede_pluviometrica_multifonte_165,
    construir_geometria_rede_observacional_172,
    buscar_chuva_observada_inmet,
    buscar_mare_observada_joinville_160,
    atualizar_historico_guaxanduva_166,
    calcular_hidrologia_guaxanduva_v019,
    calcular_nivel_guaxanduva_v021,
    calcular_criterio_hidrometeorologico_plancon_163,
    calcular_pico_mare_previsto_24h_164,
    projetar_guaxanduva_24h_174,
    construir_liberacao_experimental_168,
)

ARQUIVO = Path("dados.json")


def seguro(nome, func):
    try:
        return func()
    except Exception as exc:
        return {
            "status": "indisponivel",
            "erro": str(exc),
            "regra_seguranca": "Falha de coleta não equivale a ausência do fenômeno.",
            "fonte_operacional": nome,
        }


def main():
    try:
        dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            dados = {}
    except Exception:
        dados = {}

    previsao = seguro("Open-Meteo", buscar_previsao)
    radar = seguro("RadarSC", buscar_radar)
    cemaden = seguro("CEMADEN", buscar_chuva_cemaden_136)
    cemaden144 = seguro("CEMADEN #144", lambda: chuva_observada_cemaden_144(cemaden))
    epagri = seguro("EPAGRI/CIRAM", buscar_chuva_epagri_165)
    rede = seguro("rede multifonte #165", lambda: construir_rede_pluviometrica_multifonte_165(cemaden, epagri))
    geometria = seguro("geometria #172", lambda: construir_geometria_rede_observacional_172(rede))
    inmet = seguro("INMET", buscar_chuva_observada_inmet)
    mare160 = seguro("maré observada #160", buscar_mare_observada_joinville_160)
    h166 = seguro("histórico Guaxanduva #166", lambda: atualizar_historico_guaxanduva_166(epagri, mare160))
    h019 = seguro("hidrologia Guaxanduva V0.19", calcular_hidrologia_guaxanduva_v019)
    v021 = seguro("nível Guaxanduva V0.21", lambda: calcular_nivel_guaxanduva_v021(h166, h019))
    criterio163 = seguro("critério hidrometeorológico #163", lambda: calcular_criterio_hidrometeorologico_plancon_163(previsao, mare160))
    mare164 = seguro("maré prevista #164", lambda: calcular_pico_mare_previsto_24h_164(previsao))
    proj174 = seguro("projeção Guaxanduva #174", lambda: projetar_guaxanduva_24h_174(previsao, mare160, mare164, v021, h019))
    # #168 contém cópias de radar/nível/maré. Reconstruí-lo em toda atualização
    # operacional evita que o painel misture o V0.21 atual com um snapshot antigo.
    tathu167 = dados.get("goes19_tathu_167", {}) if isinstance(dados, dict) else {}
    liberacao168 = seguro("liberação experimental #168", lambda: construir_liberacao_experimental_168(radar, tathu167, v021, mare160, mare164))

    # Síntese operacional única para o card principal. Não confunde radar,
    # pluviômetro regional e modelo meteorológico.
    estacoes_rede = rede.get("estacoes", []) if isinstance(rede, dict) else []
    obs_frescas = [e for e in estacoes_rede if isinstance(e, dict) and e.get("dados_frescos") is True
                   and e.get("leitura_atual_disponivel") is True and isinstance(e.get("precipitacao_1h_mm"), (int, float))]
    obs_max = max((float(e["precipitacao_1h_mm"]) for e in obs_frescas), default=None)
    obs_media = (sum(float(e["precipitacao_1h_mm"]) for e in obs_frescas) / len(obs_frescas)) if obs_frescas else None
    qrad = {}
    if isinstance(radar, dict):
        quadros = radar.get("quadros") or []
        if quadros and isinstance(quadros[-1], dict):
            qrad = quadros[-1].get("classificacao_qualitativa_local_130") or {}
    por_raio = qrad.get("por_raio", {}) if isinstance(qrad, dict) else {}
    raio_eco = next((r for r in (2, 5, 10, 25) if (por_raio.get(str(r)) or {}).get("eco_qualitativo_detectado") is True), None)
    radar_fresco = isinstance(radar, dict) and radar.get("status") == "online" and radar.get("dados_frescos") is True
    eco_local = radar_fresco and raio_eco is not None
    if eco_local and obs_max is not None and obs_max > 0:
        estado_agora = "SINAIS_DE_CHUVA_AGORA"
        mensagem_agora = f"Eco RadarSC em até {raio_eco} km e chuva observada na rede regional (máx. {obs_max:.1f} mm/1h)."
    elif eco_local:
        estado_agora = "ECO_RADAR_LOCAL_AGORA"
        mensagem_agora = f"Eco qualitativo RadarSC detectado em até {raio_eco} km; sem pluviômetro no Comasa para confirmar chuva no solo."
    elif obs_max is not None and obs_max > 0:
        estado_agora = "CHUVA_OBSERVADA_REGIONAL_AGORA"
        mensagem_agora = f"Rede regional registra chuva (máx. {obs_max:.1f} mm/1h); isso não equivale a medição no Comasa."
    else:
        estado_agora = "SEM_CONFIRMACAO_LOCAL_DE_CHUVA"
        mensagem_agora = "Sem confirmação local suficiente nesta coleta; ausência de evidência não é tratada como ausência de chuva."
    estado_operacional = {
        "status": estado_agora, "mensagem": mensagem_agora,
        "radar_fresco": radar_fresco, "eco_qualitativo_local": eco_local, "menor_raio_eco_km": raio_eco,
        "chuva_observada_regional_max_1h_mm": obs_max, "chuva_observada_regional_media_1h_mm": obs_media,
        "estacoes_regionais_frescas": len(obs_frescas),
        "chuva_modelo_openmeteo_mm": ((previsao.get("atual") or {}).get("precipitacao_mm") if isinstance(previsao, dict) else None),
        "regra_seguranca": "Radar indica eco; pluviômetros medem chuva em suas estações; Open-Meteo é modelo. Nenhuma dessas fontes isoladamente é pluviômetro no Comasa.",
        "gerado_em": agora().isoformat(),
    }

    dados.update({
        "gerado_em": agora().isoformat(),
        "previsao": previsao,
        "radar": radar,
        "chuva": cemaden,
        "chuva_observada_cemaden_144": cemaden144,
        "chuva_observada_epagri_165": epagri,
        "rede_pluviometrica_multifonte_165": rede,
        "geometria_rede_observacional_172": geometria,
        "chuva_observada_inmet": inmet,
        "mare_observada_joinville_160": mare160,
        "historico_hidrometeorologico_guaxanduva_166": h166,
        "hidrologia_guaxanduva_v019": h019,
        "nivel_guaxanduva_v021": v021,
        "criterio_hidrometeorologico_plancon_163": criterio163,
        "mare_prevista_24h_164": mare164,
        "projecao_guaxanduva_174": proj174,
        "liberacao_experimental_168": liberacao168,
        "estado_agora_operacional": estado_operacional,
        "atualizacao_operacional_rapida": {
            "status": "concluida",
            "gerado_em": agora().isoformat(),
            "objetivo": "Atualizar meteorologia/radar antes das auditorias científicas pesadas.",
            "fail_closed": True,
        },
    })
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Atualização operacional rápida concluída:", dados["gerado_em"])


if __name__ == "__main__":
    main()
