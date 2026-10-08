#!/usr/bin/env python3
"""#224: amostra EXAUSTIVA de pixels RGBA visiveis em 50 km, sem classificar chuva."""
import argparse, hashlib, json, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image
from auditar_geometria_radarsc_221 import EXT, LAT, LON, hav

PADRAO = re.compile(r'^\d{14}\d*dBZ\.cappi_top\.png$')

def analisar(manifesto, diretorio, saida, limite=5000):
    origem=json.loads(Path(manifesto).read_text(encoding='utf-8'))
    relatorios=[]
    for item in origem['quadros']:
        nome=item['arquivo_oficial']
        if not PADRAO.fullmatch(nome): raise ValueError('Nome de arquivo inesperado')
        arquivo=Path(diretorio)/nome
        if hashlib.sha256(arquivo.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('SHA256 divergente: '+nome)
        with Image.open(arquivo) as imagem:
            rgba=imagem.convert('RGBA')
        w,h=rgba.size
        pixels=[]; cores=Counter(); aneis=Counter(); total=0; menor=None
        for y in range(h):
            lat=EXT[3]-(y/(h-1))*(EXT[3]-EXT[1])
            if abs(lat-LAT)>0.46: continue
            for x in range(w):
                r,g,b,a=rgba.getpixel((x,y))
                if a==0: continue
                lon=EXT[0]+(x/(w-1))*(EXT[2]-EXT[0])
                if abs(lon-LON)>0.51: continue
                d=hav(LAT,LON,lat,lon)
                if d>50: continue
                total+=1
                cores[(r,g,b,a)]+=1
                faixa='0-2' if d<=2 else '2-5' if d<=5 else '5-10' if d<=10 else '10-25' if d<=25 else '25-50'
                aneis[faixa]+=1
                menor=d if menor is None else min(menor,d)
                if len(pixels)<limite:
                    pixels.append({'x':x,'y':y,'lat':round(lat,6),'lon':round(lon,6),
                                   'distancia_km':round(d,3),'rgba':[r,g,b,a],'faixa_km':faixa})
        relatorios.append({'arquivo':nome,'sha256':item['sha256'],'tls':item.get('tls'),
          'dimensoes':[w,h],'pixels_visiveis_50km':total,'pixels_exportados':len(pixels),
          'exportacao_truncada':total>limite,'distancia_minima_km':round(menor,3) if menor is not None else None,
          'faixas_nao_cumulativas_km':dict(aneis),
          'cores_rgba':[{'rgba':list(c),'quantidade':n} for c,n in cores.most_common()],
          'pixels':pixels})
    saida=Path(saida)
    saida.write_text(json.dumps({'versao':'#224','gerado_em_utc':datetime.now(timezone.utc).isoformat(),
      'natureza':'DIAGNOSTICO_RGBA_SEM_VALIDACAO_METEOROLOGICA',
      'referencia':{'lat':LAT,'lon':LON},'extensao_comp_epsg4326':list(EXT),
      'metodo':'Centro do pixel por interpolacao linear no imageExtent COMP; distancia Haversine.',
      'quadros':relatorios,'limites':'Pixel visivel nao confirma eco meteorologico nem chuva no solo. TLS nao validado implica autenticidade nao comprovada. Nao alterar paleta ou alertas.'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Quadros:',len(relatorios),'pixels visiveis 50 km:',sum(r['pixels_visiveis_50km'] for r in relatorios))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--manifesto',default='origens_quadros_223.json')
    p.add_argument('--diretorio',default='quadros_223')
    p.add_argument('--saida',default='auditoria_pixels_geolocalizados_224.json')
    a=p.parse_args();analisar(a.manifesto,a.diretorio,a.saida)
