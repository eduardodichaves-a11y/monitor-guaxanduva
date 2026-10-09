#!/usr/bin/env python3
"""#232: auditoria reprodutivel da paleta RadarSC. Somente leitura.
Uso: python auditar_cores_radarsc_232.py [dados.json] [auditoria_cores_232.json]
Nao calibra automaticamente RGB em dBZ ou mm/h.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def auditar(dados):
    radar = dados.get('radar') or {}
    legenda = radar.get('legenda_oficial') or {}
    validacao = radar.get('validacao_paleta_radar') or {}
    dicionario = radar.get('dicionario_cores_130') or {}
    classes = legenda.get('classes') or []
    observados = {tuple(x) for x in validacao.get('rgb_observados') or []}
    indexados = {}
    erros = []
    for item in classes:
        rgb = item.get('rgb')
        if not isinstance(rgb, list) or len(rgb) != 3:
            erros.append('Classe da legenda sem RGB valido')
            continue
        key = tuple(rgb)
        if key in indexados:
            erros.append('RGB duplicado na legenda: ' + str(key))
        indexados[key] = item
    declarados = {tuple(c.get('rgb') or []) for c in dicionario.get('classes') or []}
    sem_correspondencia = sorted(observados - set(indexados))
    if sem_correspondencia:
        erros.append('RGB observado nao consta na legenda oficial')
    if set(indexados) - declarados:
        erros.append('Dicionario operacional nao contem todas as cores da legenda')
    ancora = indexados.get((255, 255, 0))
    ancora_ok = bool(ancora and ancora.get('classe') == 10 and ancora.get('dbz_min') == 28 and ancora.get('dbz_max') == 33)
    if not ancora_ok:
        erros.append('Ancora C10 amarela diverge do esperado; revisar fonte')
    quadro = validacao.get('por_quadro') or []
    return {
        'versao': '#232', 'gerado_em_utc': datetime.now(timezone.utc).isoformat(),
        'natureza': 'auditoria_estrutural_sem_calibracao_meteorologica',
        'produto': legenda.get('produto'), 'status_legenda': legenda.get('status'),
        'sha256_legenda': legenda.get('sha256'), 'classes_legenda': len(indexados),
        'classes_rgb_exatas_observadas': len(observados & set(indexados)),
        'classes_sem_correspondencia_exata': len(set(indexados) - observados),
        'quadros_comparados': len(quadro),
        'ancora_c10_28_33_dbz_documentada': ancora_ok,
        'cores_observadas_exatas': [list(x) for x in sorted(observados & set(indexados))],
        'familias_legenda': dict(Counter(c.get('familia_cor', 'nao_classificada') for c in dicionario.get('classes') or [])),
        'erros_estruturais': erros,
        'interpretacao': ('Correspondencia exata baixa NAO prova que a paleta esta errada: '
                         'pode refletir diferencas entre raster e legenda, cores ausentes nos quadros ou ambos.'),
        'bloqueios': {'calibracao_rgb_dbz_automatica': True, 'conversao_mm_h': True,
                     'alerta_por_cor': True, 'eta_por_cor': True},
        'proximo_teste': 'Comparar tabela raster nativa versus legenda oficial por produto e quadro; validar correspondencia documental antes de liberar intensidade.'
    }


def main():
    entrada = Path(sys.argv[1] if len(sys.argv) > 1 else 'dados.json')
    saida = Path(sys.argv[2] if len(sys.argv) > 2 else 'auditoria_cores_232.json')
    resultado = auditar(json.loads(entrada.read_text(encoding='utf-8')))
    saida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('RadarSC #232:', resultado['classes_rgb_exatas_observadas'], '/', resultado['classes_legenda'],
          'classes exatas;', resultado['quadros_comparados'], 'quadros; erros:', len(resultado['erros_estruturais']))
    if resultado['erros_estruturais']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
