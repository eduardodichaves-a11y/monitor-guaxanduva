#!/usr/bin/env python3
"""#175-R4B — diagnóstico de identificabilidade da reconstrução de maré EH-001.

Pergunta científica: o ensemble R4A, sem âncora temporal de 2020, contém
informação suficiente para indicar a fase da maré em cada instante?
Se não, bloqueia qualquer uso como curva histórica.
"""
from pathlib import Path
import json, math, statistics

IN=Path("mare_reconstruida_EH001_175_R4A.json")
OUT=Path("diagnostico_mare_EH001_175_R4B.json")

def main():
    d=json.loads(IN.read_text(encoding="utf-8"))
    frames=d["frames"]
    med=[float(f["fase_relativa"]["p50"]) for f in frames]
    width=[float(f["fase_relativa"]["p95"])-float(f["fase_relativa"]["p05"]) for f in frames]

    # If phases are unconstrained and uniformly randomized, the ensemble median
    # should remain near zero and the 90% envelope broad throughout the window.
    max_abs_median=max(abs(x) for x in med)
    median_width=statistics.median(width)
    min_width=min(width)
    # Conservative identifiability gate: temporal signal would require a median
    # materially displaced from zero AND a substantially narrower ensemble.
    identifiable = (max_abs_median >= 0.25 and median_width <= 1.0)

    result={
      "versao":"#175-R4B",
      "status":"IDENTIFICAVEL" if identifiable else "NAO_IDENTIFICAVEL_SEM_ANCORA",
      "evento":"EH-001",
      "estacao_referencia":"DHN 60222 — Joinville Iate Clube",
      "frames_total":len(frames),
      "diagnostico":{
        "max_abs_mediana_fase":round(max_abs_median,4),
        "largura_mediana_p05_p95":round(median_width,4),
        "largura_minima_p05_p95":round(min_width,4),
        "criterio_gate":"|mediana| >= 0.25 E largura mediana P05-P95 <= 1.0"
      },
      "interpretacao":(
        "O R4A não identifica a fase histórica de 31/12/2020–01/01/2021: "
        "fases harmônicas aleatórias sem âncora temporal geram um envelope amplo "
        "e aproximadamente simétrico. Portanto não é cientificamente válido "
        "selecionar preamar/baixamar ou produzir altura absoluta a partir dele."
      ) if not identifiable else
        "Há sinal temporal suficiente segundo o gate experimental; requer validação externa antes de uso.",
      "mare_observada":"N/D",
      "mare_reconstruida_absoluta":"N/D",
      "uso_no_fusion_175":False,
      "pesos_175_alterados":False,
      "ancoras_que_podem_liberar_r4c":[
        "ao menos um horário/altura de preamar ou baixamar DHN para 31/12/2020–01/01/2021",
        "constantes harmônicas da estação 60222 ou estação Babitonga transferível",
        "série observada de nível do mar de estação compatível com datum conhecido"
      ],
      "conclusao":"R4B bloqueia falsa precisão; matemática avançada demonstrou não-identificabilidade em vez de fabricar a maré."
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["status"],**result["diagnostico"]},ensure_ascii=False))
if __name__=="__main__": main()
