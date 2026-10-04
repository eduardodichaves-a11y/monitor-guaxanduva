#!/usr/bin/env python3
"""#175-R3C — envelope matemático corrigido do EH-001.

Usa como restrição geradora apenas o agregado contemporâneo de 139 mm entre
22:00 e 00:00. O máximo de 90 mm/1h (CEMADEN-Iririú), 120 mm/2h (Epagri/Ciram)
e ~169 mm/6h permanecem evidências independentes de validação, pois não há base
para tratá-los como a mesma série temporal/local nem para fixar a janela de 6 h.
"""
from __future__ import annotations
import json, random
from pathlib import Path
from datetime import datetime, timedelta

CFG=Path("restricoes_EH001_175_R3.json")
OUT=Path("envelope_EH001_175_R3.json")
SEED=175031
N=2000

def clamp(x,a=0.0,b=100.0): return max(a,min(b,x))
def score_chuva_a1(p1=None,p24=None):
    vals=[]
    if p1 is not None: vals.append(clamp(p1/40.0*100.0))
    if p24 is not None: vals.append(clamp(p24/80.0*100.0))
    return max(vals) if vals else None

def candidate(rng,total=139.0,n=12):
    # Amostragem positiva simples; representa possibilidades, não probabilidades.
    w=[rng.expovariate(1.0) for _ in range(n)]
    s=sum(w)
    return [total*x/s for x in w]

def rolling_max_1h(a):
    return max(sum(a[i:i+6]) for i in range(0,7))

def main():
    cfg=json.loads(CFG.read_text(encoding="utf-8"))
    rng=random.Random(SEED)
    samples=[candidate(rng) for _ in range(N)]

    # Limites analíticos para qualquer distribuição não-negativa de 139 mm em 2 h:
    # as duas metades de 1 h somam 139, então pelo menos uma tem >= 69,5 mm.
    # O máximo possível em 1 h é 139 mm.
    p1_min=139.0/2.0
    p1_max=139.0
    score_min=score_chuva_a1(p1=p1_min)
    score_max=score_chuva_a1(p1=p1_max)

    start=datetime.fromisoformat("2020-12-31T22:00:00-03:00")
    frames=[]
    for i in range(12):
        vals=[s[i] for s in samples]
        frames.append({
          "t":(start+timedelta(minutes=10*i)).isoformat(),
          "chuva_10min_amostrada_mm":{
            "min":round(min(vals),3),
            "mediana":round(sorted(vals)[len(vals)//2],3),
            "max":round(max(vals),3)
          },
          "natureza":"AMOSTRAS_DE_POSSIBILIDADES_NAO_PROBABILISTICAS",
          "observacao":False
        })

    p1_samples=[rolling_max_1h(s) for s in samples]
    out={
      "versao":"#175-R3C",
      "evento":"EH-001",
      "status":"LABORATORIO_NAO_OPERACIONAL",
      "restricao_geradora":"139 mm entre 22:00 e 00:00",
      "amostras_ilustrativas_admissiveis":N,
      "resultado_analitico":{
        "maximo_movel_1h_mm":{
          "limite_inferior":p1_min,
          "limite_superior":p1_max,
          "demonstracao":"As duas janelas disjuntas 22–23h e 23–00h somam 139 mm; portanto pelo menos uma acumula >= 69,5 mm. Concentrar toda a chuva em uma hora fornece o limite superior de 139 mm."
        },
        "fator_chuva_observada_equivalente_A1":{
          "limite_inferior":round(score_min,1),
          "limite_superior":round(score_max,1),
          "resultado":"SATURADO_EM_100_PARA_A_JANELA_RETROSPECTIVA",
          "cuidado":"Isto é equivalência matemática do fator chuva do A1, não prova que o Monitor operacional teria recebido essa informação entre 22h e 00h."
        }
      },
      "amostragem":{
        "seed":SEED,
        "nota":"As 2.000 trajetórias ajudam a explorar formas possíveis, mas não definem probabilidade nem substituem os limites analíticos.",
        "maximo_1h_amostrado_mm":{"min":round(min(p1_samples),3),"max":round(max(p1_samples),3)}
      },
      "causalidade":{
        "agregado_139_disponivel_em":"2021-01-01T01:42:00-03:00",
        "regra":"Não retroagir a informação para 22h–00h.",
        "risco_total_175":"N/D",
        "motivo":"O Fusion A1 operacional usa leituras de estações e outros fatores históricos (rio, maré numérica, radar, memória e drenagem) não estão reconstruídos de forma suficiente."
      },
      "evidencias_independentes_nao_fundidas":[
        "90 mm/1h máximo no CEMADEN-Iririú",
        "120 mm/2h Epagri/Ciram com estação não identificada no decreto",
        "aprox. 169 mm/6h com posição temporal exata ainda N/D"
      ],
      "frames_amostrados":frames,
      "regras_seguranca":cfg["regras"]
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({
      "status":out["status"],
      "amostras":N,
      "p1h_limites_mm":[p1_min,p1_max],
      "fator_chuva_equivalente":[round(score_min,1),round(score_max,1)],
      "risco_total_175":"N/D"
    },ensure_ascii=False))

if __name__=="__main__":
    main()
