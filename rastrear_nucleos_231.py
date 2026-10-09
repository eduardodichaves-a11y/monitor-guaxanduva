#!/usr/bin/env python3
"""#231: histórico de núcleos cromáticos RadarSC; sem inferir chuva, ETA ou velocidade validada.
Uso: python rastrear_nucleos_231.py [dados.json] [historico_nucleos_231.json]
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

MAX_QUADROS = 144
MAX_INTERVALO_MIN = 35
MAX_DESLOCAMENTO_KM = 20
MAX_EXTENSAO_KM = 15


def distancia_km(a, b):
    lat1, lon1 = math.radians(a['latitude']), math.radians(a['longitude'])
    lat2, lon2 = math.radians(b['latitude']), math.radians(b['longitude'])
    x = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742 * math.asin(min(1, math.sqrt(x)))


def compacto(n):
    centro = n.get('centroide') or {}
    limites = n.get('limites') or {}
    if not all(isinstance(centro.get(k), (int, float)) for k in ('latitude', 'longitude')):
        return None
    if not all(isinstance(limites.get(k), (int, float)) for k in ('lat_min','lat_max','lon_min','lon_max')):
        return None
    extensao = distancia_km({'latitude': limites['lat_min'], 'longitude': limites['lon_min']},
                            {'latitude': limites['lat_max'], 'longitude': limites['lon_max']})
    return {'familia': n.get('familia'), 'pixels': n.get('pixels', 0), 'centroide': centro,
            'distancia_min_km': n.get('distancia_min_comasa_km'),
            'distancia_max_km': n.get('distancia_max_comasa_km'),
            'extensao_diagonal_km': round(extensao, 2),
            'rastreavel': extensao <= MAX_EXTENSAO_KM}


def processar(dados, historico):
    radar = dados.get('radar') or {}
    geo = ((radar.get('classificacao_qualitativa_local_130') or {})
           .get('geolocalizacao_familias_230') or {})
    quadro = radar.get('horario_ultimo_quadro')
    if not quadro or not isinstance(geo.get('nucleos'), list):
        raise ValueError('Sem quadro RadarSC ou núcleos #230: histórico não alterado')
    instante = datetime.fromisoformat(quadro.replace('Z', '+00:00'))
    quadros = historico.get('quadros', [])
    if any(q.get('quadro_radar') == quadro for q in quadros):
        return historico, {'resultado': 'quadro_ja_registrado', 'quadro': quadro}
    nucleos = [c for n in geo['nucleos'] if (c := compacto(n)) is not None]
    anterior = max((q for q in quadros if datetime.fromisoformat(q['quadro_radar'].replace('Z','+00:00')) < instante),
                   key=lambda q: q['quadro_radar'], default=None)
    comparacoes = []
    if anterior:
        intervalo = (instante-datetime.fromisoformat(anterior['quadro_radar'].replace('Z','+00:00'))).total_seconds()/60
        if 0 < intervalo <= MAX_INTERVALO_MIN:
            candidatos = []
            for i, n in enumerate(nucleos):
                if not n['rastreavel']: continue
                for j, velho in enumerate(anterior.get('nucleos', [])):
                    if not velho.get('rastreavel') or n['familia'] != velho['familia']: continue
                    d = distancia_km(n['centroide'], velho['centroide'])
                    if d <= MAX_DESLOCAMENTO_KM:
                        candidatos.append((d, i, j))
            usados_n, usados_v = set(), set()
            for d, i, j in sorted(candidatos):
                if i in usados_n or j in usados_v: continue
                usados_n.add(i); usados_v.add(j)
                velho = anterior['nucleos'][j]; novo = nucleos[i]
                a, b = velho.get('distancia_min_km'), novo.get('distancia_min_km')
                tendencia = ('indeterminada' if a is None or b is None or abs(a-b) < 1
                             else 'aproximacao_possivel' if b < a else 'afastamento_possivel')
                comparacoes.append({'familia': novo['familia'], 'nucleo_atual': i,
                                    'nucleo_anterior': j, 'deslocamento_centroide_km': round(d,2),
                                    'variacao_distancia_min_km': round(b-a,2) if a is not None and b is not None else None,
                                    'tendencia_exploratoria': tendencia,
                                    'intervalo_min': round(intervalo,2),
                                    'validacao_trajetoria': False})
    quadros.append({'quadro_radar': quadro, 'coletado_em': dados.get('gerado_em'),
                    'nucleos': nucleos, 'comparacoes_exploratorias': comparacoes})
    quadros.sort(key=lambda q: q['quadro_radar'])
    historico = {'versao': '#231', 'politica': 'Comparacoes exploratorias; sem ETA, mm/h, raios ou alerta validado.',
                 'quadros': quadros[-MAX_QUADROS:]}
    return historico, {'resultado': 'novo_quadro', 'quadro': quadro,
                       'nucleos': len(nucleos), 'rastreaveis': sum(n['rastreavel'] for n in nucleos),
                       'comparacoes_exploratorias': len(comparacoes)}


def main():
    entrada = Path(sys.argv[1] if len(sys.argv)>1 else 'dados.json')
    saida = Path(sys.argv[2] if len(sys.argv)>2 else 'historico_nucleos_231.json')
    dados = json.loads(entrada.read_text(encoding='utf-8'))
    historico = json.loads(saida.read_text(encoding='utf-8')) if saida.exists() else {}
    resultado, diagnostico = processar(dados, historico)
    if diagnostico['resultado'] == 'novo_quadro':
        saida.write_text(json.dumps(resultado, ensure_ascii=False, separators=(',',':'))+'\n', encoding='utf-8')
    print(json.dumps(diagnostico, ensure_ascii=False))

if __name__ == '__main__':
    main()
