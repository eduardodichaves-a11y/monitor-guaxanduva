#!/usr/bin/env python3
"""#223: compara PNGs COMP oficiais; diagnostico, nao validacao de chuva."""
import argparse, json, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image
from auditar_geometria_radarsc_221 import auditar

PADRAO = re.compile(r'^\d{14}\d*dBZ\.cappi_top\.png$')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--manifesto',type=Path,default=Path('origens_quadros_223.json'))
    ap.add_argument('--diretorio',type=Path,default=Path('quadros_223'))
    ap.add_argument('--saida',type=Path,default=Path('auditoria_serie_radarsc_223.json'))
    a=ap.parse_args()
    manifesto=json.loads(a.manifesto.read_text(encoding='utf-8'))
    linhas=[]
    for item in manifesto['quadros']:
        nome=item['arquivo_oficial']
        if not PADRAO.fullmatch(nome): raise ValueError('Nome nao oficial: '+nome)
        caminho=a.diretorio/nome
        if hashlib.sha256(caminho.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Hash divergente: '+nome)
        rel=auditar(caminho, None, None)
        aneis=rel['aneis_cumulativos_km']
        linhas.append({'arquivo_oficial':nome,'timestamp_utc':nome[:14],
          'sha256':item['sha256'],'tls':item['tls'],
          'dimensoes':rel['dimensoes'],
          'pixels_visiveis_imagem':rel['imagem_completa']['visiveis'],
          'pixels_visiveis_50km':aneis['50']['visiveis'],
          'pixels_examinados_50km':aneis['50']['pixels'],
          'pixels_visiveis_25km':aneis['25']['visiveis'],
          'limites_pixels_visiveis':rel['limites_pixels_visiveis']})
    resultado={'versao':'#223','gerado_em_utc':datetime.now(timezone.utc).isoformat(),
      'natureza':'DIAGNOSTICO_TEMPORAL_ESPACIAL_SEM_VALIDACAO_METEOROLOGICA',
      'fonte_lista':manifesto.get('fonte_lista'),
      'numero_quadros':len(linhas),'quadros':linhas,
      'limites':'Pixels visiveis nao provam chuva; ausencia de pixels nao prova ausencia de chuva. TLS nao validado impede confirmar autenticidade. Nao alterar paleta ou operacao.',
      'resumo':{'quadros_com_pixel_visivel_50km':sum(x['pixels_visiveis_50km']>0 for x in linhas),
                'quadros_com_pixel_visivel_imagem':sum(x['pixels_visiveis_imagem']>0 for x in linhas)}}
    a.saida.write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Quadros:',len(linhas),'com pixels visiveis a 50km:',resultado['resumo']['quadros_com_pixel_visivel_50km'])
if __name__=='__main__':main()
