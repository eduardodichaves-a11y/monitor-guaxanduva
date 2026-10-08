#!/usr/bin/env python3
"""#212/#216 — Auditoria geografica RadarSC: preserva RGB observado, sem inferir chuva."""
import argparse
import json
import math
from pathlib import Path


def distancia_km(lat1, lon1, lat2, lon2):
    r1, r2 = math.radians(lat1), math.radians(lat2)
    dr = r2 - r1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dr / 2) ** 2 + math.cos(r1) * math.cos(r2) * math.sin(dl / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(a)))


def auditar(dados, max_km=25):
    radar = dados.get('radar') or {}
    geo = (radar.get('classificacao_qualitativa_local_130') or {}).get('geolocalizacao_ecos_211') or {}
    grupos = geo.get('agrupamentos') or []
    estacoes = (dados.get('chuva') or {}).get('estacoes_joinville_ativas') or []
    saida = {'versao': '#212+#216', 'gerado_em_fonte': dados.get('gerado_em'),
             'quadro_radar': radar.get('horario_ultimo_quadro'),
             'total_agrupamentos': len(grupos), 'agrupamentos': [],
             'regra': 'RGB observado nao confirma chuva. Acumulado de 24h nao valida eco; sem pareamento temporal e espacial, nao promover classe.'}
    for i, g in enumerate(grupos, 1):
        lat = g.get('centroide_latitude', g.get('latitude'))
        lon = g.get('centroide_longitude', g.get('longitude'))
        centro = g.get('centroide') or {}
        if isinstance(centro, dict):
            lat = lat if lat is not None else centro.get('latitude')
            lon = lon if lon is not None else centro.get('longitude')
        candidatos = []
        if lat is not None and lon is not None:
            for e in estacoes:
                if e.get('latitude') is None or e.get('longitude') is None:
                    continue
                km = distancia_km(float(lat), float(lon), float(e['latitude']), float(e['longitude']))
                if km <= max_km:
                    candidatos.append({'nome': e.get('nome'), 'municipio': e.get('cidade'),
                        'rede': e.get('rede'), 'distancia_km': round(km, 2),
                        'acumulado_24h_mm': e.get('acumulado_24h_mm'),
                        'tem_medicao': bool(e.get('acumulado_disponivel')),
                        'validou_eco': False,
                        'motivo': 'Sem pareamento de precipitacao no horario do quadro'})
        candidatos.sort(key=lambda x: x['distancia_km'])
        saida['agrupamentos'].append({'numero': i, 'latitude': lat, 'longitude': lon,
            'pixels': g.get('pixels'),
            'cores_rgb': g.get('cores_rgb') or [],
            'familias_cromaticas': g.get('familias_cromaticas') or [],
            'origem_rgb': 'RadarSC PNG / geolocalizacao_ecos_211',
            'rgb_preservado': bool(g.get('cores_rgb')),
            'estacoes_proximas_cadastradas': candidatos,
            'cobertura_regional_completa': False,
            'validacao': 'PENDENTE: requer inventario regional e serie temporal da chuva'})
    return saida


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dados', nargs='?', default='dados.json')
    parser.add_argument('--raio-estacoes-km', type=float, default=25)
    parser.add_argument('--saida', default='auditoria_geografica_212.json')
    args = parser.parse_args()
    dados = json.loads(Path(args.dados).read_text(encoding='utf-8'))
    resultado = auditar(dados, args.raio_estacoes_km)
    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Agrupamentos:', resultado['total_agrupamentos'])
    print('Relatorio:', args.saida)


if __name__ == '__main__':
    main()
