#!/usr/bin/env python3
"""Auditoria conservadora do RadarSC #227; não altera dados nem libera ETA."""
import json, sys, zipfile
from pathlib import Path

def carregar(arquivo, nome):
    if zipfile.is_zipfile(arquivo):
        with zipfile.ZipFile(arquivo) as z:
            candidatos=[n for n in z.namelist() if n.endswith('/'+nome) or n==nome]
            if not candidatos: raise FileNotFoundError(nome)
            return json.loads(z.read(candidatos[0]))
    return json.loads((Path(arquivo)/nome).read_text(encoding='utf-8'))

def auditar(caminho):
    d=carregar(caminho,'dados.json'); h=carregar(caminho,'historico_ecos_rgb_217.json')
    radar=d.get('radar',{}); mov=radar.get('analise_movimento',{})
    quadros=h.get('quadros',[])
    geo=radar.get('classificacao_qualitativa_local_130',{}).get('geolocalizacao_ecos_211',{})
    grupos=geo.get('agrupamentos',[])
    mistos=[{'pixels':g.get('pixels'), 'distancia_min_km':g.get('distancia_min_comasa_km'),
             'distancia_max_km':g.get('distancia_max_comasa_km'),
             'familias': [f.get('familia') for f in g.get('familias_cromaticas',[])]}
            for g in grupos if len(g.get('familias_cromaticas',[]))>1]
    distancia=mov.get('distancia_atual_comasa_km')
    avisos=[]
    if isinstance(distancia,(int,float)) and distancia>50:
        avisos.append('TRAJETORIA_REGIONAL_FORA_DO_RAIO_50KM')
    if mistos: avisos.append('AGRUPAMENTOS_MULTICOR_NAO_APTOS_PARA_TRAJETORIA_POR_FAMILIA')
    if len(quadros)<2: avisos.append('HISTORICO_INSUFICIENTE')
    avisos.append('CENTROIDES_NAO_COMPROVAM_IDENTIDADE_NEM_MOVIMENTO_DO_MESMO_ECO')
    return {'auditoria':'#227_trajetorias_conservadora','fonte':'ZIP local sem consulta ao vivo',
      'quadros_arquivados':len(quadros),'primeiro_quadro':quadros[0].get('quadro_radar') if quadros else None,
      'ultimo_quadro':quadros[-1].get('quadro_radar') if quadros else None,
      'agrupamentos_atuais':len(grupos),'agrupamentos_multicor':len(mistos),
      'maior_agrupamento_multicor':max(mistos,key=lambda g:g['pixels']) if mistos else None,
      'movimento_regional_reportado':{'tendencia':mov.get('tendencia'),
          'velocidade_media_kmh':mov.get('velocidade_media_kmh'),
          'distancia_comasa_km':distancia,'validado_para_eta':mov.get('validado_para_eta')},
      'avisos':avisos,'eta_local_liberado':False,
      'proxima_exigencia':'Arquivar coordenadas dos pixels por familia e por quadro, associar componentes espacialmente e testar movimento com incerteza.'}

if __name__=='__main__':
    if len(sys.argv)<2: raise SystemExit('Uso: python auditar_trajetorias_227.py arquivo.zip [saida.json]')
    resultado=auditar(sys.argv[1]); saida=json.dumps(resultado,ensure_ascii=False,indent=2)
    if len(sys.argv)>2: Path(sys.argv[2]).write_text(saida+'\n',encoding='utf-8')
    print(saida)
