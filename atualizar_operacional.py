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
