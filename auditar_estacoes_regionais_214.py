#!/usr/bin/env python3
"""#214: cruzamento observacional regional, sem alterar o Monitor.

Entradas: auditoria_territorial_213.json e observacoes_regionais_214.json.
O arquivo de observacoes precisa conter lista 'observacoes' com fonte, estacao,
latitude, longitude, horario ISO com fuso, precipitacao_mm, periodo_minutos.
Sem observacoes reais, o resultado permanece NAO_VALIDADO.
"""
import argparse
import json
import math
from datetime import datetime
from pathlib import Path


def distancia_km(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(d-b)/2)**2
    return 12742.0176 * math.asin(min(1, math.sqrt(x)))


def instante(valor):
    t = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError('Horario sem fuso horario')
    return t


def auditar(territorio, observacoes, raio_km=25, janela_min=15):
    quadro = instante(territorio['quadro_radar'])
    saida = {'versao': '#214', 'quadro_radar': territorio['quadro_radar'],
             'criterio': {'raio_km': raio_km, 'janela_min': janela_min},
             'aviso': 'Associacao observacional nao prova que o pixel de radar seja chuva em superficie; nao calibra C1-C16.',
             'agrupamentos': []}
    for grupo in territorio.get('agrupamentos', []):
        lat, lon = grupo.get('latitude'), grupo.get('longitude')
        candidatos = []
        for o in observacoes.get('observacoes', []):
            try:
                if lat is None or lon is None: continue
                km = distancia_km(float(lat), float(lon), float(o['latitude']), float(o['longitude']))
                atraso = abs((instante(o['horario']) - quadro).total_seconds())/60
                periodo = float(o['periodo_minutos'])
                chuva = float(o['precipitacao_mm'])
                if not (0 < periodo <= 60 and chuva >= 0 and math.isfinite(chuva)):
                    continue
                if km <= raio_km and atraso <= janela_min:
                    candidatos.append({'estacao': o['estacao'], 'fonte': o['fonte'],
                        'municipio': o.get('municipio'), 'distancia_km': round(km, 2),
                        'diferenca_horario_min': round(atraso, 1),
                        'precipitacao_mm': chuva, 'periodo_minutos': periodo,
                        'horario': o['horario'], 'situacao': 'MEDICAO_PROXIMA',
                        'observacao': 'Amostra regional; nao valida diretamente o pixel.'})
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        candidatos.sort(key=lambda c: (c['distancia_km'], c['diferenca_horario_min']))
        saida['agrupamentos'].append({'numero': grupo.get('numero'),
            'territorio_provavel': (grupo.get('territorio') or {}).get('municipio_provavel'),
            'latitude': lat, 'longitude': lon, 'medicoes_compativeis': candidatos,
            'status': 'MEDICOES_REGIONAIS_ENCONTRADAS' if candidatos else 'SEM_MEDICAO_REGIONAL_COMPATIVEL',
            'validacao_cor_intensidade': 'BLOQUEADA'})
    return saida


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('territorio', nargs='?', default='auditoria_territorial_213.json')
    ap.add_argument('--observacoes', default='observacoes_regionais_214.json')
    ap.add_argument('--saida', default='auditoria_estacoes_regionais_214.json')
    args = ap.parse_args()
    territorio = json.loads(Path(args.territorio).read_text(encoding='utf-8'))
    caminho = Path(args.observacoes)
    observacoes = json.loads(caminho.read_text(encoding='utf-8')) if caminho.is_file() else {'observacoes': []}
    resultado = auditar(territorio, observacoes)
    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Agrupamentos:', len(resultado['agrupamentos']))
    print('Observacoes fornecidas:', len(observacoes.get('observacoes', [])))
    print('Relatorio:', args.saida)

if __name__ == '__main__':
    main()
