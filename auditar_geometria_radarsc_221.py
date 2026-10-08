#!/usr/bin/env python3
"""#221: auditoria espacial de transparencia RadarSC, somente leitura.

Nao interpreta pixel como chuva, nao calibra dBZ, nao altera dados operacionais.
"""
import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw

# Extensao COMP usada no atualizar_dados.py (longitude minima, latitude minima,
# longitude maxima, latitude maxima). Hipotese de projecao linear a ser testada.
EXT = (-58.0651279, -33.8163446, -46.4999942, -24.7653703)
LAT, LON = -26.27, -48.81

def hav(lat1, lon1, lat2, lon2):
    a1, a2 = math.radians(lat1), math.radians(lat2)
    da, dl = a2-a1, math.radians(lon2-lon1)
    h = math.sin(da/2)**2 + math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))

def ponto(lat, lon, w, h):
    return ((lon-EXT[0])/(EXT[2]-EXT[0])*(w-1),
            (EXT[3]-lat)/(EXT[3]-EXT[1])*(h-1))

def auditar(caminho_png, caminho_dados=None, saida_imagem=None):
    img = Image.open(caminho_png).convert('RGBA')
    w, h = img.size
    x0, y0 = ponto(LAT, LON, w, h)
    contagens = {'total': 0, 'visiveis': 0, 'opacos': 0, 'semitransparentes': 0}
    aneis = {str(k): {'pixels': 0, 'visiveis': 0, 'opacos': 0, 'semitransparentes': 0} for k in (2, 5, 10, 25, 50)}
    quadrantes = {q: {'pixels': 0, 'visiveis': 0} for q in ('NO','NE','SO','SE')}
    fora50 = {'pixels': 0, 'visiveis': 0}
    alfas = Counter()
    limites = [w, h, -1, -1]
    # Percorrer imagem inteira para nao confundir transparencia local com global.
    px = img.load()
    for y in range(h):
        lat = EXT[3] - y/max(1, h-1)*(EXT[3]-EXT[1])
        for x in range(w):
            lon = EXT[0] + x/max(1, w-1)*(EXT[2]-EXT[0])
            alpha = px[x, y][3]
            contagens['total'] += 1
            alfas[alpha] += 1
            visivel = alpha > 0
            if visivel:
                contagens['visiveis'] += 1
                limites = [min(limites[0],x), min(limites[1],y), max(limites[2],x), max(limites[3],y)]
                if alpha == 255: contagens['opacos'] += 1
                else: contagens['semitransparentes'] += 1
            q = ('N' if y < y0 else 'S') + ('O' if x < x0 else 'E')
            quadrantes[q]['pixels'] += 1
            quadrantes[q]['visiveis'] += int(visivel)
            # Limitacao: distancia haversine sobre a hipotese de georreferenciamento EXT.
            if abs(lat-LAT) < 0.52 and abs(lon-LON) < 0.65:
                d = hav(LAT, LON, lat, lon)
            else:
                d = 1000
            if d > 50:
                fora50['pixels'] += 1
                fora50['visiveis'] += int(visivel)
            for r in aneis:
                if d <= int(r):
                    aneis[r]['pixels'] += 1
                    aneis[r]['visiveis'] += int(visivel)
                    if visivel:
                        if alpha == 255: aneis[r]['opacos'] += 1
                        else: aneis[r]['semitransparentes'] += 1
    meta = {}
    if caminho_dados:
        dados = json.loads(Path(caminho_dados).read_text(encoding='utf-8'))
        radar = dados.get('radar') or {}
        meta = {'gerado_em_dados': dados.get('gerado_em'),
                'horario_ultimo_quadro': radar.get('horario_ultimo_quadro'),
                'dados_frescos_declarados': radar.get('dados_frescos'),
                'arquivo_selecionado': (radar.get('diagnostico_lista_fonte_176') or {}).get('arquivo_selecionado')}
    rel = {'versao': '#221', 'natureza': 'AUDITORIA_ESPACIAL_SEM_VALIDACAO_METEOROLOGICA',
           'gerado_em': datetime.now(timezone.utc).isoformat(), 'png': str(caminho_png),
           'dimensoes': [w, h], 'extensao_assumida_lonlat': list(EXT),
           'hipotese': 'Projecao linear lon/lat baseada no EXT do atualizar_dados.py; nao e verificacao independente da projecao oficial.',
           'referencia_guaxanduva': {'latitude': LAT, 'longitude': LON,
                                    'pixel_x': round(x0, 2), 'pixel_y': round(y0, 2),
                                    'dentro_da_imagem': 0 <= x0 < w and 0 <= y0 < h},
           'imagem_completa': contagens, 'alpha_top': [{'alpha': a, 'pixels': n} for a,n in alfas.most_common(12)],
           'aneis_cumulativos_km': aneis, 'fora_50km': fora50,
           'quadrantes_relativos_ao_ponto': quadrantes,
           'limites_pixels_visiveis': limites if contagens['visiveis'] else None,
           'metadados': meta,
           'conclusao_limitada': ('PNG integralmente transparente: nao permite inferir ausencia de chuva.' if contagens['visiveis'] == 0 else
                                  'Existem pixels visiveis no PNG; sua natureza meteorologica e localizacao oficial nao estao validadas.'),
           'restricao': 'Transparencia nao prova ausencia de chuva; nao converter RGB em chuva nem alterar paleta.'}
    if saida_imagem:
        # Imagem diagnostica: fundo cinza apenas para revelar pixels transparentes.
        fundo = Image.new('RGBA', img.size, (235,235,235,255))
        fundo.alpha_composite(img)
        desenho = ImageDraw.Draw(fundo)
        x, y = round(x0), round(y0)
        desenho.line((x-12,y,x+12,y), fill=(255,0,0,255), width=2)
        desenho.line((x,y-12,x,y+12), fill=(255,0,0,255), width=2)
        desenho.ellipse((x-4,y-4,x+4,y+4), outline=(255,0,0,255), width=2)
        fundo.convert('RGB').save(saida_imagem)
        rel['imagem_diagnostica'] = str(saida_imagem)
    return rel

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--png', type=Path, required=True)
    ap.add_argument('--dados', type=Path, default=Path('dados.json'))
    ap.add_argument('--saida', type=Path, default=Path('auditoria_geometria_radarsc_221.json'))
    ap.add_argument('--imagem', type=Path, default=Path('mapa_transparencia_radarsc_221.png'))
    a=ap.parse_args()
    rel=auditar(a.png, a.dados, a.imagem)
    a.saida.write_text(json.dumps(rel,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Auditoria #221:',rel['imagem_completa']['visiveis'],'pixels visiveis na imagem inteira; raio 50km:',rel['aneis_cumulativos_km']['50']['visiveis'])
if __name__ == '__main__': main()
