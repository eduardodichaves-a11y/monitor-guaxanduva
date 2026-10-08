#!/usr/bin/env python3
"""#215/#216: auditoria multifonte com rastreabilidade RGB; sem calibracao automatica."""
import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ANCORA = {'numero': 1, 'latitude': -26.215039, 'longitude': -48.614186,
          'pixels': 1, 'territorio': {'municipio_provavel': 'Sao Francisco do Sul'},
          'proveniencia': 'Eco historico #212/#213; coordenada aproximada; nao observado neste run'}
QUADRO = '2026-10-08T12:20:00-03:00'

def consultar_open_meteo(lat, lon, quadro):
    parametros = {'latitude': lat, 'longitude': lon,
                  'hourly': 'precipitation,rain,showers,weather_code',
                  'timezone': 'America/Sao_Paulo', 'past_days': 2, 'forecast_days': 1}
    url = 'https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode(parametros)
    req = urllib.request.Request(url, headers={'User-Agent': 'MonitorGuaxanduva-Auditoria/215',
                                               'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as resp:
        d = json.load(resp)
    hourly = d.get('hourly') or {}
    horas = hourly.get('time') or []
    alvo = quadro.astimezone(ZoneInfo('America/Sao_Paulo'))
    candidatas = []
    for i, hora in enumerate(horas):
        try:
            t = datetime.fromisoformat(hora).replace(tzinfo=alvo.tzinfo)
            delta = abs((t-alvo).total_seconds()) / 60
            if delta <= 90:
                registro = {'horario_local': t.isoformat(), 'diferenca_minutos': round(delta, 1)}
                for campo in ('precipitation', 'rain', 'showers', 'weather_code'):
                    valores = hourly.get(campo) or []
                    registro[campo] = valores[i] if i < len(valores) else None
                candidatas.append(registro)
        except (ValueError, TypeError):
            continue
    candidatas.sort(key=lambda x: x['diferenca_minutos'])
    return {'provedor': 'Open-Meteo', 'tipo': 'ESTIMATIVA_MODELO',
            'origem': 'https://open-meteo.com/',
            'descricao': 'Precipitacao horaria modelada; nao equivale a chuva observada no pixel.',
            'amostras': candidatas[:3], 'horario_consulta_utc': datetime.now(timezone.utc).isoformat()}

def auditar(territorio, sem_rede=False):
    quadro_str = territorio.get('quadro_radar') or QUADRO
    quadro = datetime.fromisoformat(quadro_str.replace('Z', '+00:00'))
    if quadro.tzinfo is None:
        raise ValueError('Quadro sem fuso')
    grupos = territorio.get('agrupamentos') or []
    origem = 'auditoria_territorial_213.json'
    if not grupos:
        grupos = [dict(ANCORA)]
        quadro_str, quadro, origem = QUADRO, datetime.fromisoformat(QUADRO), 'ANCORA_HISTORICA_212_213'
    resultado = {'versao': '#215+#216', 'quadro_radar': quadro_str, 'origem_ecos': origem,
                 'criterio': 'Modelo e previsao sao apoio, nao validacao observacional independente.',
                 'calibracao_cores': 'BLOQUEADA', 'agrupamentos': []}
    for g in grupos:
        cores = g.get('cores_rgb') or []
        item = {'numero': g.get('numero'), 'latitude': g.get('latitude'),
                'longitude': g.get('longitude'), 'pixels': g.get('pixels'),
                'territorio_provavel': (g.get('territorio') or {}).get('municipio_provavel'),
                'cores_rgb': cores, 'familias_cromaticas': g.get('familias_cromaticas') or [],
                'origem_rgb': g.get('origem_rgb') if cores else None,
                'rgb_preservado': bool(cores),
                'estado_rgb': 'PRESERVADO_DA_FONTE' if cores else 'NAO_DISPONIVEL_NA_FONTE',
                'evidencias': [], 'chuva_no_pixel_confirmada': False}
        if g.get('proveniencia'):
            item['proveniencia'] = g['proveniencia']
        if item['latitude'] is not None and item['longitude'] is not None:
            if sem_rede:
                item['evidencias'].append({'provedor': 'Open-Meteo', 'status': 'CONSULTA_DESATIVADA'})
            else:
                try:
                    item['evidencias'].append(consultar_open_meteo(float(item['latitude']), float(item['longitude']), quadro))
                except (OSError, ValueError, KeyError) as exc:
                    item['evidencias'].append({'provedor': 'Open-Meteo', 'status': 'INDISPONIVEL', 'erro': str(exc)})
        resultado['agrupamentos'].append(item)
    return resultado

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--territorio', default='auditoria_territorial_213.json')
    p.add_argument('--saida', default='auditoria_multifonte_215.json')
    p.add_argument('--sem-rede', action='store_true')
    args = p.parse_args()
    caminho = Path(args.territorio)
    entrada = json.loads(caminho.read_text(encoding='utf-8')) if caminho.is_file() else {'agrupamentos': []}
    resultado = auditar(entrada, args.sem_rede)
    Path(args.saida).write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Ecos:', len(resultado['agrupamentos']), '| origem:', resultado['origem_ecos'])
    print('Calibracao:', resultado['calibracao_cores'])

if __name__ == '__main__':
    main()
