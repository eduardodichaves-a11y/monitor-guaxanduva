#!/usr/bin/env python3
"""#175 GUAXANDUVA FUSION — índice experimental, auditável e fail-closed.
Não é probabilidade de inundação, alerta oficial nem substituto da Defesa Civil.
"""
from __future__ import annotations
import json, math
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

TZ=ZoneInfo('America/Sao_Paulo')
SRC=Path('dados.json'); OUT=Path('fusion_guaxanduva_175.json')

def num(x):
    try:
        v=float(x); return v if math.isfinite(v) else None
    except (TypeError,ValueError): return None

def clamp(x,a=0,b=100): return max(a,min(b,x))
def scale(v, full): return None if v is None else round(clamp(v/full*100),1)
def piece(v, pts):
    if v is None:return None
    pts=sorted(pts)
    if v<=pts[0][0]:return pts[0][1]
    for (x0,y0),(x1,y1) in zip(pts,pts[1:]):
        if v<=x1:
            return round(y0+(y1-y0)*(v-x0)/(x1-x0),1)
    return pts[-1][1]
def label(s):
    if s<25:return ('BAIXO','baixo')
    if s<50:return ('ATENÇÃO','atencao')
    if s<75:return ('ALERTA EXPERIMENTAL','alerta')
    return ('MUITO ELEVADO','emergencia')

def main():
    d=json.loads(SRC.read_text(encoding='utf-8'))
    rede=d.get('rede_pluviometrica_multifonte_165') or {}
    est=rede.get('estacoes') or []
    c24=[num(x.get('acumulado_24h_mm')) for x in est if x.get('leitura_atual_disponivel')]
    c1=[num(x.get('precipitacao_1h_mm')) for x in est if x.get('leitura_atual_disponivel')]
    max24=max([x for x in c24 if x is not None],default=None); max1=max([x for x in c1 if x is not None],default=None)
    chuva_obs=max([x for x in (scale(max24,80),scale(max1,40)) if x is not None],default=None)

    p=d.get('previsao') or {}; p24=p.get('proximas_24h') or {}; prev24=num(p24.get('precipitacao_acumulada_mm'))
    chuva_prev=scale(prev24,80) if p24.get('integridade') is True else None

    n=d.get('nivel_guaxanduva_v021') or {}; tend=n.get('tendencia') or {}; cmh=num(tend.get('cm_h'))
    # Sem cotas de perigo validadas: nível absoluto NÃO gera pontos; só tendência modelada crescente.
    rio=None if cmh is None else round(clamp(max(0,cmh)/20*100),1)
    mem=num((n.get('entradas') or {}).get('chuva_memoria_mm_h_equivalente')); memoria=scale(mem,10)

    mo=d.get('mare_observada_joinville_160') or {}; m24=d.get('mare_prevista_24h_164') or {}
    mare_obs=num(mo.get('nivel_m')) if mo.get('frescor')=='atual' else None
    mare_pico=num(m24.get('pico_previsto_m')) if m24.get('integridade') is True else None
    mare_ref=max([x for x in (mare_obs,mare_pico) if x is not None],default=None)
    # Âncoras do PLANCON #163 (1,5 m / 1,8 m); não equivalem a estágio oficial.
    mare=piece(mare_ref,[(0.8,0),(1.2,15),(1.5,50),(1.8,80),(2.2,100)])

    rad=d.get('radar') or {}; radar=None
    if rad.get('dados_frescos') is True:
        eco=(rad.get('eco_oficial_local_129') or {}).get('eco_oficial_mais_proximo')
        mov=rad.get('analise_movimento') or {}
        radar=20.0 if eco else 0.0
        if str(mov.get('tendencia','')).lower().startswith('aproxim'): radar=max(radar,45.0)
        if mov.get('candidato_eta') is True: radar=max(radar,55.0) # ETA segue bloqueado; apenas evidência de tendência.

    fatores={
      'chuva_observada':{'peso':0.24,'score':chuva_obs,'valor':{'max_1h_mm':max1,'max_24h_mm':max24},'nota':'Máximo entre estações disponíveis; não equivale a chuva medida no Comasa.'},
      'chuva_prevista_24h':{'peso':0.12,'score':chuva_prev,'valor':prev24,'nota':'Open-Meteo; previsão, não observação.'},
      'memoria_bacia':{'peso':0.12,'score':memoria,'valor':mem,'nota':'Forçante de memória hidrológica do V0.21.'},
      'radar_tendencia':{'peso':0.14,'score':radar,'valor':{'fresco':rad.get('dados_frescos'),'tendencia':(rad.get('analise_movimento') or {}).get('tendencia')},'nota':'Eco/tendência qualitativos; sem conversão automática para chuva no solo.'},
      'rio_tendencia_modelada':{'peso':0.16,'score':rio,'valor':{'nivel_m':num(n.get('nivel_estimado_m')),'cm_h':cmh},'nota':'MODELADO/NÃO INSTRUMENTAL; nível absoluto não usa cotas de perigo não validadas.'},
      'mare_jusante':{'peso':0.16,'score':mare,'valor':{'observada_m':mare_obs,'pico_24h_m':mare_pico},'nota':'Condição de jusante; não é nível do Guaxanduva.'},
      'drenagem_urbana':{'peso':0.06,'score':None,'valor':None,'nota':'Sem sensor operacional/estado de obstrução validado; excluído do cálculo em fail-closed.'},
    }
    valid=[v for v in fatores.values() if v['score'] is not None]
    den=sum(v['peso'] for v in valid)
    score=round(sum(v['peso']*v['score'] for v in valid)/den,1) if den else None
    cobertura=round(den/sum(v['peso'] for v in fatores.values())*100,1)
    # Confiança mede cobertura + maturidade, não probabilidade de acerto.
    maturidade=0.70 # penalidade explícita: rio modelado e #175 ainda sem replay histórico calibrado.
    confianca=round(cobertura*maturidade,1)
    rot,classe=label(score or 0)

    # Tendência curta é deliberadamente conservadora: sem hidrodinâmica validada por horizonte, não inventa ETA.
    horizontes={k:{'score':None,'status':'NAO_CALIBRADO','nota':'Aguardando replay histórico #175 e calibração independente.'} for k in ('+30min','+60min','+120min')}

    out={
      'versao':'#175-A1','status':'EXPERIMENTAL_NAO_OPERACIONAL','gerado_em':datetime.now(TZ).isoformat(),
      'indice_pressao_hidrometeorologica':score,'classe_experimental':rot,'classe_css':classe,
      'confianca_dados_pct':confianca,'cobertura_fatores_pct':cobertura,
      'natureza_indice':'Índice composto de pressão hidrometeorológica; NÃO é probabilidade percentual de inundação.',
      'fatores':fatores,'horizontes':horizontes,
      'historico':{'status':'BASE_EM_CONSTRUCAO','evento_benchmark':'EH-001 • 31/12/2020–01/01/2021','uso_na_pontuacao':False,'nota':'Eventos históricos serão usados em replay cego antes de liberar pesos/limiares calibrados.'},
      'regras_seguranca':['Ausência de dado não vira zero; fator indisponível é retirado e reduz cobertura/confiança.','PLANCON oficial não é inferido pelo #175.','Nível do Guaxanduva permanece MODELADO/NÃO INSTRUMENTAL.','Maré de Joinville/Babitonga é condição de jusante, não nível do rio.','Radar não é convertido automaticamente em chuva no solo.','Horizontes +30/+60/+120 e ETA permanecem bloqueados até validação histórica.','Defesa Civil/199 permanece referência oficial para emergência.'],
      'metodo':{'tipo':'fusão determinística transparente com renormalização por disponibilidade','pesos_nominais':{k:v['peso'] for k,v in fatores.items()},'calibrado_historicamente':False,'probabilidade_inundacao':False}
    }
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':out['status'],'indice':score,'classe':rot,'confianca_dados_pct':confianca},ensure_ascii=False))
if __name__=='__main__': main()
