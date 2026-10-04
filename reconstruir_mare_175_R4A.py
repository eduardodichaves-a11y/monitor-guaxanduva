#!/usr/bin/env python3
"""#175-R4A — envelope harmônico RELATIVO da maré para EH-001.

Não reconstrói altura observada. Sem constantes harmônicas/âncora de 2020,
produz apenas um envelope de FASE RELATIVA adimensional em 73 frames.
"""
from __future__ import annotations
import json, math, random
from datetime import datetime, timedelta
from pathlib import Path

CFG=Path("config_mare_EH001_175_R4A.json")
OUT=Path("mare_reconstruida_EH001_175_R4A.json")

def q(v,p):
    s=sorted(v); x=(len(s)-1)*p; a=int(x); b=min(a+1,len(s)-1); f=x-a
    return s[a]*(1-f)+s[b]*f

def main():
    c=json.loads(CFG.read_text(encoding="utf-8"))
    random.seed(c["modelo"]["seed"])
    start=datetime.fromisoformat(c["janela"]["inicio"])
    end=datetime.fromisoformat(c["janela"]["fim"])
    step=timedelta(minutes=c["janela"]["passo_min"])
    times=[]; t=start
    while t<=end: times.append(t); t+=step
    assert len(times)==73

    periods={x["nome"]:x["periodo_h"] for x in c["modelo"]["constituintes"]}
    ensembles=[[] for _ in times]
    n=c["modelo"]["amostras"]

    # Exploratory shape ensemble only: random amplitudes/phases, normalized per realization.
    for _ in range(n):
        sd=random.uniform(.55,.90); di=1-sd
        m2=sd*random.uniform(.45,.70); s2=sd-m2
        n2=random.uniform(0,.12)
        k1=di*random.uniform(.45,.70); o1=di-k1
        amps={"M2":m2,"S2":s2,"N2":n2,"K1":k1,"O1":o1}
        phases={k:random.uniform(0,2*math.pi) for k in amps}
        vals=[]
        for tt in times:
            h=(tt-start).total_seconds()/3600
            vals.append(sum(a*math.cos(2*math.pi*h/periods[k]+phases[k]) for k,a in amps.items()))
        scale=max(abs(x) for x in vals) or 1
        vals=[x/scale for x in vals]
        for i,x in enumerate(vals): ensembles[i].append(x)

    frames=[]
    for i,t in enumerate(times):
        v=ensembles[i]
        frames.append({
          "t":t.isoformat(),
          "fase_relativa":{"p05":round(q(v,.05),4),"p50":round(q(v,.50),4),"p95":round(q(v,.95),4)},
          "mare_observada_m":None,
          "mare_reconstruida_absoluta_m":None
        })
    result={
      "versao":"#175-R4A","status":"LABORATORIO_NAO_OPERACIONAL","evento":"EH-001",
      "estacao_referencia":"DHN 60222 — Joinville Iate Clube",
      "frames_total":len(frames),"amostras_ensemble":n,
      "natureza":"ENVELOPE_HARMONICO_RELATIVO_ADIMENSIONAL",
      "mare_observada":"N/D","altura_absoluta":"N/D",
      "motivo_altura_nd":"Faltam constantes harmônicas/âncora observacional compatível de 2020 para converter fase relativa em nível absoluto defensável.",
      "meteorologia":"N/D — não assumida zero",
      "frames":frames,
      "uso_permitido":"estrutura temporal exploratória e teste de pipeline; NÃO usar como nível histórico medido ou como alerta.",
      "proximo_gate":"R4B: condicionar o ensemble com tábua DHN/constantes harmônicas/série de estação Babitonga e dados meteorológicos históricos."
    }
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":result["status"],"frames":len(frames),"ensemble":n,"altura_absoluta":"N/D"},ensure_ascii=False))
if __name__=="__main__": main()
