#!/usr/bin/env python3
"""#218 - Cruzamento exploratorio de ecos RGB arquivados com observacoes INMET.

Somente leitura das fontes; nao modifica dados.json nem historico #217.
Nao calibra C1-C16, nao infere chuva a partir de RGB.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path
from coletar_inmet_regional_214 import coletar
from auditar_estacoes_regionais_214 import auditar


def instante(s):
    d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError('Quadro sem fuso horario')
    return d


def processar(historico, consultar=coletar, limite=5, raio_km=50):
    quadros = historico.get('quadros', [])
    if not isinstance(quadros, list):
        raise ValueError('Historico sem lista de quadros')
    saida = {'versao': '#218', 'origem': 'historico_ecos_rgb_217.json',
             'status': 'SEM_ECOS_ARQUIVADOS', 'quadros_no_historico': len(quadros),
             'quadros_analisados': 0, 'resultados': [],
             'politica': 'INMET independente; acumulado horario nao representa instante do radar. Sem calibracao automatica C1-C16.'}
    # Mais recentes primeiro; apenas quadros com horario valido e ecos.
    elegiveis = []
    for q in quadros:
        try:
            dt = instante(q['quadro_radar'])
            if isinstance(q.get('ecos'), list) and q['ecos']:
                elegiveis.append((dt, q))
        except (ValueError, TypeError, KeyError):
            continue
    for _, q in sorted(elegiveis, key=lambda p: p[0], reverse=True)[:limite]:
        grupos = []
        for eco in q['ecos']:
            if eco.get('latitude') is None or eco.get('longitude') is None:
                continue
            grupos.append({'numero': eco.get('numero'), 'latitude': eco['latitude'],
                           'longitude': eco['longitude']})
        territorio = {'quadro_radar': q['quadro_radar'], 'agrupamentos': grupos}
        if grupos:
            try:
                observacoes = consultar(territorio, raio_km=raio_km)
                cruzamento = auditar(territorio, observacoes)
                diagnostico = observacoes.get('diagnostico', [])
            except Exception as exc:
                cruzamento = {'agrupamentos': []}
                diagnostico = ['Consulta indisponivel: ' + str(exc)]
        else:
            cruzamento = {'agrupamentos': []}
            diagnostico = ['Sem centroides validos']
        por_numero = {g.get('numero'): g for g in cruzamento['agrupamentos']}
        ecos = []
        for eco in q['ecos']:
            a = por_numero.get(eco.get('numero'), {})
            ecos.append({'numero': eco.get('numero'), 'pixels': eco.get('pixels'),
                         'latitude': eco.get('latitude'), 'longitude': eco.get('longitude'),
                         'cores_rgb': eco.get('cores_rgb', []),
                         'familias_cromaticas': eco.get('familias_cromaticas', []),
                         'medicoes_regionais': a.get('medicoes_compativeis', []),
                         'status_observacional': a.get('status', 'SEM_MEDICAO_REGIONAL_COMPATIVEL'),
                         'validacao_cor_intensidade': 'BLOQUEADA'})
        saida['resultados'].append({'quadro_radar': q['quadro_radar'],
                                   'ecos': ecos, 'diagnostico_inmet': diagnostico})
    saida['quadros_analisados'] = len(saida['resultados'])
    if saida['resultados']:
        saida['status'] = 'CRUZAMENTO_EXPLORATORIO_SEM_CALIBRACAO'
    return saida


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--historico', default='historico_ecos_rgb_217.json')
    ap.add_argument('--saida', default='auditoria_historico_inmet_218.json')
    ap.add_argument('--limite', type=int, default=5)
    args = ap.parse_args()
    if args.limite < 1 or args.limite > 50:
        ap.error('--limite deve estar entre 1 e 50')
    entrada = json.loads(Path(args.historico).read_text(encoding='utf-8'))
    resultado = processar(entrada, limite=args.limite)
    Path(args.saida).write_text(json.dumps(resultado, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Status:', resultado['status'], '| quadros analisados:', resultado['quadros_analisados'])


if __name__ == '__main__':
    main()
