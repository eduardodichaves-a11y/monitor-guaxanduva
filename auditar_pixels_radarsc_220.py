#!/usr/bin/env python3
"""#220: diagnóstico de pixels RadarSC; SOMENTE LEITURA, sem calibrar chuva.
Uso: python auditar_pixels_radarsc_220.py --png quadro.png --dados dados.json
Requer Pillow: pip install pillow
"""
import argparse, json, math
from collections import Counter
from pathlib import Path
from PIL import Image

PALETA={(165,255,255),(110,200,255),(55,145,255),(0,90,255),
 (170,255,0),(128,206,0),(85,156,0),(43,107,0),(0,57,0),
 (255,255,0),(255,192,0),(255,128,0),(255,64,0),(190,0,0),(255,0,255)}
EXT=(-58.0651279,-33.8163446,-46.4999942,-24.7653703)
LAT,LON=-26.27,-48.81

def distancia(lat,lon):
    r1,r2=map(math.radians,(LAT,lat));dl=math.radians(lon-LON)
    h=math.sin((r2-r1)/2)**2+math.cos(r1)*math.cos(r2)*math.sin(dl/2)**2
    return 12742*math.asin(min(1,math.sqrt(h)))

def auditar(png,dados):
    radar=dados.get('radar') or {}
    classes=((radar.get('legenda_oficial') or {}).get('classes') or [])
    oficiais=set()
    for c in classes:
        if isinstance(c,dict) and isinstance(c.get('rgb'),list) and len(c['rgb'])==3:
            oficiais.add(tuple(c['rgb']))
    aceitas=PALETA|oficiais
    img=Image.open(png).convert('RGBA');w,h=img.size
    hist=Counter(); alphas=Counter(); exatos=Counter(); candidatos=Counter()
    # Mesma transformação espacial usada no diagnóstico #211.
    for y in range(h):
        lat=EXT[3]-(y/max(1,h-1))*(EXT[3]-EXT[1])
        if abs(lat-LAT)>0.5: continue
        for x in range(w):
            lon=EXT[0]+(x/max(1,w-1))*(EXT[2]-EXT[0])
            if abs(lon-LON)>0.6 or distancia(lat,lon)>50: continue
            rgba=img.getpixel((x,y)); rgb=rgba[:3];a=rgba[3]
            alphas[str(a)]+=1
            if not a: continue
            hist[rgb]+=1
            if rgb in aceitas: exatos[rgb]+=1
            elif any(max(abs(rgb[k]-ref[k]) for k in range(3))<=8 for ref in aceitas):
                candidatos[rgb]+=1
    esperado=((radar.get('classificacao_qualitativa_local_130') or {}).get('por_raio') or {}).get('50') or {}
    return {'versao':'#220','natureza':'DIAGNOSTICO_RGB_SEM_VALIDACAO_METEOROLOGICA',
      'png':str(png),'dimensoes': [w,h],'quadro_declarado_dados_json':radar.get('horario_ultimo_quadro'),
      'observacao':'A correspondencia entre PNG e timestamp deve ser confirmada pelo nome do arquivo de origem.',
      'pixels_opacos_ou_semitransparentes_no_raio':sum(hist.values()),
      'pixels_rgb_exato_paleta':sum(exatos.values()),
      'pixels_rgb_proximos_ate_8_por_canal_nao_aceitos':sum(candidatos.values()),
      'top_rgb_exatos':[{'rgb':list(c),'pixels':n} for c,n in exatos.most_common(20)],
      'top_rgb_nao_reconhecidos':[{'rgb':list(c),'pixels':n} for c,n in (hist-exatos).most_common(30)],
      'top_rgb_proximos':[{'rgb':list(c),'pixels':n} for c,n in candidatos.most_common(20)],
      'alpha_histograma':alphas.most_common(12),
      'pixels_eco_50km_reportados_pelo_monitor':esperado.get('pixels_eco_qualitativo'),
      'alerta':'Proximidade RGB NAO confirma eco: fundo, transparencias e artefatos podem parecer cores radar. Nao mudar a paleta automaticamente.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--png',type=Path,required=True);p.add_argument('--dados',type=Path,default=Path('dados.json'));p.add_argument('--saida',type=Path,default=Path('auditoria_pixels_radarsc_220.json'))
    a=p.parse_args();resultado=auditar(a.png,json.loads(a.dados.read_text(encoding='utf8')))
    a.saida.write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Auditoria somente leitura:',a.saida,'| RGB exatos:',resultado['pixels_rgb_exato_paleta'])
if __name__=='__main__': main()
