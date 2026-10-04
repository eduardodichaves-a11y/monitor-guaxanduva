#!/usr/bin/env python3
from pathlib import Path
import json, random, math, statistics

CFG=json.loads(Path("config_ensemble_EH001_175.json").read_text(encoding="utf-8"))
N=CFG["ensemble"]["n"]; rng=random.Random(175175)

# Pesos nominais do motor #175-A1 vigente no repositório.
W={"chuva_observada":0.24,"chuva_prevista_24h":0.12,"memoria_bacia":0.12,
   "radar_tendencia":0.14,"rio_tendencia_modelada":0.16,"mare_jusante":0.16,
   "drenagem_urbana":0.06}

def clamp(x): return max(0.0,min(100.0,x))
def q(a,p):
    a=sorted(a); return a[round((len(a)-1)*p)] if a else None
def hhmm(m):
    m%=1440; return f"{m//60:02d}:{m%60:02d}"
def tide_score(minute):
    # Somente FASE relativa do modelo histórico já fechado:
    # alta ~20:24:40, baixa ~02:37:17. Sem altura absoluta.
    hi=20*60+24.67; lo=26*60+37.28
    x=minute
    if x<hi: x+=1440
    phase=(x-hi)/(lo-hi)
    # pressão de jusante relativa: 100 na alta, 0 na baixa.
    return clamp(100*(1-phase))

accepted=[]
for _ in range(N):
    alpha=10**rng.uniform(-0.35,0.55)
    xs=[rng.gammavariate(alpha,1.0) for _ in range(12)]
    rain=[139*x/sum(xs) for x in xs]
    peak=max(sum(rain[i:i+6]) for i in range(7))
    w=math.exp(-0.5*((peak-90)/18)**2)
    early=sum(rain[:3]); w*=0.35+0.65*(1-math.exp(-early/15))
    if rng.random()>w: continue

    cum=0.0; first=None; series=[]
    for i,x in enumerate(rain):
        minute=22*60+(i+1)*10
        cum+=x
        one=sum(rain[max(0,i-5):i+1])
        # Componentes reconstruíveis sem fabricar sensor histórico:
        chuva=clamp(max(cum/80*100,one/40*100))
        memoria=clamp(cum/80*100)
        mare=tide_score(minute)

        # NÃO disponíveis historicamente: previsão24h, radar, rio dH/dt e estado da drenagem.
        # Fail-closed científico: são excluídos e o denominador é renormalizado,
        # exatamente como o A1 faz para fator indisponível.
        factors={"chuva_observada":chuva,"memoria_bacia":memoria,"mare_jusante":mare}
        den=sum(W[k] for k in factors)
        score=sum(W[k]*v for k,v in factors.items())/den
        # Política conservadora pedida: limiar A1 de ATENÇÃO=25 como primeiro alarme.
        if first is None and score>=25: first=minute
        series.append({"hora":hhmm(minute),"indice":round(score,1)})
    accepted.append({"first":first,"series":series})

times=[a["first"] for a in accepted if a["first"] is not None]
impact1=24*60+30
out={
 "id":"EH001_175_MOTOR_INTEGRADO_R1",
 "natureza":"HINDCAST_ENSEMBLE_COM_MOTOR_175_A1_PARCIAL_RECONSTRUIVEL",
 "n_propostas":N,"n_aceitas":len(accepted),
 "motor":{
   "pesos_nominais_175_A1":W,
   "fatores_reconstruidos":["chuva_observada","memoria_bacia","mare_jusante"],
   "fatores_indisponiveis":["chuva_prevista_24h","radar_tendencia","rio_tendencia_modelada","drenagem_urbana"],
   "regra_indisponiveis":"exclusao + renormalizacao, coerente com #175-A1",
   "segmentos_drenagem_modelados":119,
   "segmentos_usados_numericamente_neste_hindcast":0,
   "nota_drenagem":"A topologia de 119 segmentos existe, mas faltam estados/parametros historicos suficientes; não foi inventada resposta hidráulica por segmento."
 },
 "politica_alerta":{"primeiro_limiar":25,"classe":"ATENCAO","custo":"FN >> FP"},
 "resultado":{
   "fracao_ensembles_com_alerta":round(len(times)/len(accepted),4) if accepted else None,
   "hora_alerta_p05":hhmm(q(times,.05)) if times else None,
   "hora_alerta_p50":hhmm(q(times,.50)) if times else None,
   "hora_alerta_p95":hhmm(q(times,.95)) if times else None,
   "impacto_referencia":"00:30",
   "lead_time_vs_00h30_min":{
      "p05":round(impact1-q(times,.95)) if times else None,
      "p50":round(impact1-q(times,.50)) if times else None,
      "p95":round(impact1-q(times,.05)) if times else None
   }
 },
 "interpretacao":"Lead time MODELADO/CONDICIONAL ao ensemble e ao subconjunto reconstruível do #175; não é horário observado nem validação operacional.",
 "uso_operacional":False
}
Path("resultado_motor_integrado_EH001_175.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(out["resultado"],ensure_ascii=False,indent=2))
