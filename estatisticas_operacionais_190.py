#!/usr/bin/env python3
"""#190 — Estatística Operacional Contínua do Monitor Guaxanduva.

Camada descritiva/auditável. Não altera alertas, modelos, gates científicos nem
os contadores congelados da validação histórica #175.
"""
import json, math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ=ZoneInfo('America/Sao_Paulo')
DADOS=Path('dados.json'); H166=Path('historico_guaxanduva_166.json')
FUSION=Path('fusion_guaxanduva_175.json'); HIST=Path('historico_operacional_190.json')
OUT=Path('estatisticas_operacionais_190.json')
JANELAS={'24h':24,'7d':168,'30d':720}

def ler(p, padrao=None):
    try:
        x=json.loads(Path(p).read_text(encoding='utf-8'))
        return x
    except Exception:
        return {} if padrao is None else padrao

def dt(v):
    if not v: return None
    try:
        x=datetime.fromisoformat(str(v).replace('Z','+00:00'))
        return x.replace(tzinfo=TZ) if x.tzinfo is None else x.astimezone(TZ)
    except Exception: return None

def num(v):
    return float(v) if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(float(v)) else None

def pct(a,b): return round(100*a/b,1) if b else None

def snapshot(d,f,hregs):
    rad=d.get('radar') or {}; rede=d.get('rede_pluviometrica_multifonte_165') or {}
    cq=rad.get('classificacao_qualitativa_local_130') or {}; pr=cq.get('por_raio') or {}
    def eco(r):
        x=pr.get(str(r)) or {}
        return True if x.get('eco_qualitativo_detectado') is True or x.get('eco_oficial_detectado') is True else False
    est=[]
    for e in rede.get('estacoes') or []:
        if not isinstance(e,dict) or e.get('aquisicao_automatica_integrada') is not True: continue
        est.append({'rede':e.get('rede'),'codigo':str(e.get('codigo') or e.get('id') or ''),'nome':e.get('nome'),
                    'recebida':e.get('leitura_atual_disponivel') is True,
                    'fresca':e.get('dados_frescos') if e.get('dados_frescos') in (True,False) else None})
    v=d.get('nivel_guaxanduva_v021') or {}; tend=v.get('tendencia') or {}
    agora=dt(d.get('gerado_em')) or datetime.now(TZ)
    # #206-B: memória compacta chuva + maré + resposta no MESMO snapshot.
    # P3h = maior acumulado de uma estação; nunca soma estações diferentes.
    chuva=[r for r in hregs if r.get('tipo')=='chuva_horaria_observada']
    por={}
    for r in chuva:
        tr=dt(r.get('horario_medicao')); vv=num(r.get('precipitacao_mm'))
        if tr and vv is not None and timedelta(0)<=agora-tr<=timedelta(hours=3):
            por.setdefault(str(r.get('codigo_estacao')),[]).append(vv)
    p3=max((sum(vals) for vals in por.values()),default=None)
    mo=d.get('mare_observada_joinville_160') or {}
    mare=num(mo.get('nivel_m')) if mo.get('status')=='observado_disponivel' else None
    return {'horario':d.get('gerado_em') or datetime.now(TZ).isoformat(),
      'radar':{'online':rad.get('status')=='online','fresco':rad.get('dados_frescos') is True,
               'idade_min':num(rad.get('idade_ultimo_quadro_min')),'eco_10km':eco(10),'eco_25km':eco(25),'eco_50km':eco(50),
               'tem_raio_50km':'50' in pr},
      'estacoes':est,
      'guaxanduva_v021':{'nivel_m':num(v.get('nivel_estimado_m')),'cm_h':num(tend.get('cm_h')),'natureza':v.get('natureza')},
      'fusion_175':{'indice':num(f.get('indice_pressao_hidrometeorologica')),'classe':f.get('classe_experimental'),
                    'confianca_pct':num(f.get('confianca_dados_pct'))},
      'memoria_bacia_206':{'p3h_max_estacao_mm':round(p3,2) if p3 is not None else None,
                           'mare_observada_m':mare,
                           'mare_horario':mo.get('horario') if mare is not None else None,
                           'nivel_modelado_m':num(v.get('nivel_estimado_m')),
                           'natureza':'DESCRITIVO_NAO_CAUSAL'}}

def dedup_snapshots(regs):
    out={}
    for r in regs:
        if isinstance(r,dict) and dt(r.get('horario')): out[str(r['horario'])]=r
    vals=sorted(out.values(),key=lambda r:dt(r['horario']))
    if not vals:return []
    corte=dt(vals[-1]['horario'])-timedelta(days=31)
    return [r for r in vals if dt(r['horario'])>=corte]

def janela_regs(regs, horas, campo_h='horario_medicao'):
    valid=[r for r in regs if dt(r.get(campo_h))]
    if not valid:return [],None
    fim=max(dt(r[campo_h]) for r in valid); ini=fim-timedelta(hours=horas)
    return [r for r in valid if ini < dt(r[campo_h]) <= fim],fim

def chuva_stats(regs):
    chuva=[r for r in regs if r.get('tipo')=='chuva_horaria_observada' and num(r.get('precipitacao_mm')) is not None]
    estacoes={}
    for r in chuva:
        k=f"{r.get('fonte')}:{r.get('codigo_estacao')}"; estacoes.setdefault(k,{'nome':r.get('nome_estacao'),'fonte':r.get('fonte'),'codigo':r.get('codigo_estacao')})
    out={}
    for rot,h in {'1h':1,'3h':3,'6h':6,'24h':24,'7d':168,'30d':720}.items():
        wr,fim=janela_regs(chuva,h); por=[]
        for k,meta in estacoes.items():
            rr=[r for r in wr if f"{r.get('fonte')}:{r.get('codigo_estacao')}"==k]
            vals=[num(r.get('precipitacao_mm')) for r in rr]; vals=[v for v in vals if v is not None]
            n=len({r.get('horario_medicao') for r in rr}); cobertura=min(100.0,pct(n,h) or 0.0)
            por.append({**meta,'acumulado_mm':round(sum(vals),2) if vals else None,'max_horario_mm':round(max(vals),2) if vals else None,
                        'leituras_horarias':n,'cobertura_pct':cobertura,'janela_completa':n>=h})
        out[rot]={'fim_referencia':fim.isoformat() if fim else None,'estacoes':por,
                  'nota':'Acumulados por estação; estações não são somadas entre si.'}
    return out

def mare_stats(regs, chuva):
    mares=[r for r in regs if r.get('tipo')=='mare_observada_jusante' and num(r.get('nivel_m')) is not None]
    out={}
    for rot,h in JANELAS.items():
        wr,fim=janela_regs(mares,h); vals=[num(r['nivel_m']) for r in wr]
        out[rot]={'n':len(vals),'min_m':round(min(vals),3) if vals else None,'max_m':round(max(vals),3) if vals else None,
                  'amplitude_m':round(max(vals)-min(vals),3) if vals else None,'fim_referencia':fim.isoformat() if fim else None}
    altas=[r for r in mares if num(r.get('nivel_m'))>=1.5]
    chuva_pos=[r for r in chuva if num(r.get('precipitacao_mm'))>0]
    coinc=0
    for m in altas:
        tm=dt(m.get('horario_medicao'))
        if any(abs((dt(c.get('horario_medicao'))-tm).total_seconds())<=3600 for c in chuva_pos if dt(c.get('horario_medicao'))): coinc+=1
    out['coincidencia_chuva_mare_alta']={'limiar_mare_m':1.5,'amostras_mare_alta':len(altas),'amostras_com_chuva_regional_mais_ou_menos_1h':coinc,
      'frequencia_pct':pct(coinc,len(altas)),'natureza':'COINCIDENCIA_DESCRITIVA_REGIONAL_NAO_CAUSAL'}
    return out

def snapshot_stats(regs):
    if not regs:return {'status':'historico_inicia_com_#190','janelas':{}}
    fim=max(dt(r['horario']) for r in regs); jout={}
    for rot,h in JANELAS.items():
        ini=fim-timedelta(hours=h); w=[r for r in regs if dt(r['horario'])>ini]
        rad=[r.get('radar') or {} for r in w]; ages=[num(x.get('idade_min')) for x in rad]; ages=[x for x in ages if x is not None]
        radar={'coletas':len(rad),'online_pct':pct(sum(x.get('online') is True for x in rad),len(rad)),
               'frescas_pct':pct(sum(x.get('fresco') is True for x in rad),len(rad)),'atraso_medio_min':round(sum(ages)/len(ages),2) if ages else None}
        for rr in (10,25,50):
            eleg=[x for x in rad if rr!=50 or x.get('tem_raio_50km') is True]
            radar[f'eco_ate_{rr}km_pct']=pct(sum(x.get(f'eco_{rr}km') is True for x in eleg),len(eleg)) if eleg else None
            radar[f'eco_ate_{rr}km_n']=sum(x.get(f'eco_{rr}km') is True for x in eleg) if eleg else 0
        station={}
        for r in w:
            for e in r.get('estacoes') or []:
                k=f"{e.get('rede')}:{e.get('codigo')}"; z=station.setdefault(k,{'nome':e.get('nome'),'rede':e.get('rede'),'codigo':e.get('codigo'),'coletas':0,'recebidas':0})
                z['coletas']+=1; z['recebidas']+=e.get('recebida') is True
        for z in station.values():
            # #198: uma coleta isolada descreve presença/ausência naquele instante, não disponibilidade histórica.
            z['disponibilidade_pct']=pct(z['recebidas'],z['coletas']) if z['coletas'] >= 8 else None
            z['maturidade']='amostra_em_formacao' if z['coletas'] < 8 else 'descritiva'
            # #206-A: quarentena significa falha de RECEPÇÃO pelo Monitor, não defeito físico da estação.
            z['quarentena_operacional']=z['coletas'] >= 8 and z['recebidas']==0
            z['motivo_quarentena']=(f"0/{z['coletas']} coletas recebidas na janela #190" if z['quarentena_operacional'] else None)
        nv=[r.get('guaxanduva_v021') or {} for r in w]; nvals=[num(x.get('nivel_m')) for x in nv]; nvals=[x for x in nvals if x is not None]
        cm=[num(x.get('cm_h')) for x in nv]; cm=[x for x in cm if x is not None]
        # #198: subida e queda são sinais diferentes; uma subida positiva nunca pode virar 'queda'.
        # Exigimos ao menos 2 snapshots para chamar extremos de estatística temporal da janela.
        subidas=[x for x in cm if x > 0]; quedas=[x for x in cm if x < 0]; temporal_ok=len(nvals) >= 2
        gx={'amostras':len(nvals),'min_m':round(min(nvals),3) if nvals else None,'media_m':round(sum(nvals)/len(nvals),3) if nvals else None,'max_m':round(max(nvals),3) if nvals else None,
            'maior_subida_cm_h':round(max(subidas),2) if temporal_ok and subidas else None,
            'maior_queda_cm_h':round(abs(min(quedas)),2) if temporal_ok and quedas else None,
            'variacao_temporal_disponivel':temporal_ok,'natureza':'MODELADO_NAO_INSTRUMENTAL'}
        fu=[r.get('fusion_175') or {} for r in w]; inds=[num(x.get('indice')) for x in fu]; inds=[x for x in inds if x is not None]; conf=[num(x.get('confianca_pct')) for x in fu]; conf=[x for x in conf if x is not None]
        classes={}
        for x in fu:
            c=x.get('classe') or 'SEM_CLASSE'; classes[c]=classes.get(c,0)+1
        fusion={'amostras':len(inds),'max_indice':round(max(inds),1) if inds else None,'media_indice':round(sum(inds)/len(inds),1) if inds else None,
                'confianca_media_pct':round(sum(conf)/len(conf),1) if conf else None,
                'tempo_por_classe_pct':{k:pct(v,len(fu)) for k,v in classes.items()} if len(fu) >= 8 else {},
                'classe_observada_atual':fu[-1].get('classe') if fu else None,
                'distribuicao_temporal_disponivel':len(fu) >= 8,
                'natureza':'EXPERIMENTAL_NAO_OPERACIONAL'}
        jout[rot]={'inicio':ini.isoformat(),'fim':fim.isoformat(),'snapshots':len(w),'radar':radar,'rede_meteorologica':list(station.values()),'guaxanduva_v021':gx,'fusion_175':fusion,
                   'cobertura_temporal_desde_implantacao_h':round((fim-min(dt(r['horario']) for r in w)).total_seconds()/3600,2) if len(w)>1 else 0.0}
    return {'status':'calculado','janelas':jout}

def relacao_chuva_mare_rio(regs190,h166):
    # #206-B: snapshots novos preservam P3h + maré observada + V0.21.
    # Snapshots antigos continuam válidos, mas não recebem maré retroativamente.
    chuva=[r for r in h166 if r.get('tipo')=='chuva_horaria_observada']
    saida=[]
    for s in regs190:
        t=dt(s.get('horario')); nv=num((s.get('guaxanduva_v021') or {}).get('nivel_m'))
        if not t or nv is None: continue
        mem=s.get('memoria_bacia_206') or {}
        p3=num(mem.get('p3h_max_estacao_mm')); mare=num(mem.get('mare_observada_m'))
        if p3 is None:
            por={}
            for r in chuva:
                tr=dt(r.get('horario_medicao')); vv=num(r.get('precipitacao_mm'))
                if tr and vv is not None and timedelta(0)<=t-tr<=timedelta(hours=3):
                    por.setdefault(str(r.get('codigo_estacao')),[]).append(vv)
            p3=max((sum(v) for v in por.values()),default=None)
        saida.append({'horario':s.get('horario'),'p3h_max_estacao_mm':round(p3,2) if p3 is not None else None,
                      'mare_observada_m':mare,'nivel_modelado_m':nv})
    def resumo(campo):
        vals=[num(x.get(campo)) for x in saida]; vals=[v for v in vals if v is not None]
        return {'n':len(vals),'min':round(min(vals),3) if vals else None,'media':round(sum(vals)/len(vals),3) if vals else None,'max':round(max(vals),3) if vals else None}
    completos=[x for x in saida if x.get('p3h_max_estacao_mm') is not None and x.get('mare_observada_m') is not None and x.get('nivel_modelado_m') is not None]
    return {'status':'amostra_descritiva_disponivel' if len(completos)>=8 else 'em_formacao','n':len(saida),'n_triplas_completas':len(completos),'minimo_triplas_maturidade':8,
            'estatisticas':{'p3h_mm':resumo('p3h_max_estacao_mm'),'mare_observada_m':resumo('mare_observada_m'),'nivel_modelado_m':resumo('nivel_modelado_m')},
            'amostra_recente':saida[-24:],
            'regra_seguranca':'Relação descritiva; maré é condição de jusante; não aprende coeficientes, não altera V0.21/Fusion e não implica causalidade.'}

def main():
    d=ler(DADOS); f=ler(FUSION); h=ler(H166); hregs=h.get('registros') or []
    old=ler(HIST,{'registros':[]}); regs=dedup_snapshots((old.get('registros') or [])+[snapshot(d,f,hregs)])
    hist={'versao':'#190','atualizado_em':datetime.now(TZ).isoformat(),'retencao':'31 dias de snapshots operacionais compactos','registros':regs}
    HIST.write_text(json.dumps(hist,ensure_ascii=False,indent=2),encoding='utf-8')
    chuva=[r for r in hregs if r.get('tipo')=='chuva_horaria_observada']
    produto={'versao':'#190','status':'calculado','gerado_em':datetime.now(TZ).isoformat(),'natureza':'ESTATISTICA_DESCRITIVA_NAO_OPERACIONAL',
      'historico_166':{'registros_total':len(hregs),'chuva':chuva_stats(hregs),'mare':mare_stats(hregs,chuva)},
      'historico_snapshots_190':{'registros_total':len(regs),**snapshot_stats(regs)},
      'chuva_mare_resposta_modelada':relacao_chuva_mare_rio(regs,hregs),
      'validacao_historica_175':{'alterada_pelo_190':False,'nota':'Casos/replay/20% permanecem congelados; #190 não incrementa validação histórica.'},
      'regras_seguranca':['Ausência não vira zero.','Estações permanecem séries independentes.','Maré é condição de jusante, não nível do Guaxanduva.','V0.21 é MODELADO/NÃO INSTRUMENTAL.','Fusion #175 é EXPERIMENTAL/NÃO OPERACIONAL.','#190 não altera alertas, modelos ou gates científicos.']}
    OUT.write_text(json.dumps(produto,ensure_ascii=False,indent=2),encoding='utf-8')
    d['estatistica_operacional_continua_190']=produto
    DADOS.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f"#190 OK snapshots={len(regs)} chuva166={len(chuva)}")
if __name__=='__main__': main()
