#!/usr/bin/env python3
"""#233: audita evidencias disponiveis, sem converter RGB em dBZ/mm/h.
Uso: python auditar_evidencias_paleta_233.py [dados.json] [auditoria_paleta_233.json]
Nao substitui comparacao direta com os bytes PNG originais.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def auditar(dados):
    radar = dados.get('radar') or {}
    legenda = radar.get('legenda_oficial') or {}
    validacao = radar.get('validacao_paleta_radar') or {}
    classes = legenda.get('classes') or []
    quadros = validacao.get('por_quadro') or []
    mapa = {}
    problemas = []
    for item in classes:
        rgb = item.get('rgb')
        if not isinstance(rgb, list) or len(rgb) != 3 or any(not isinstance(v, int) or v < 0 or v > 255 for v in rgb):
            problemas.append('RGB invalido na legenda')
            continue
        chave = tuple(rgb)
        if chave in mapa:
            problemas.append('RGB duplicado na legenda')
        mapa[chave] = item.get('classe')
    observados = {tuple(c) for c in validacao.get('rgb_observados') or [] if isinstance(c, list) and len(c) == 3}
    correspondentes = sorted(observados.intersection(mapa))
    if len(correspondentes) != validacao.get('classes_legenda_observadas'):
        problemas.append('Contagem declarada difere dos RGB correspondentes')
    return {
        'versao': '#233',
        'gerado_em_utc': datetime.now(timezone.utc).isoformat(),
        'natureza': 'auditoria_de_evidencias_processadas_nao_comparacao_png_nativo',
        'produto': legenda.get('produto'),
        'sha256_legenda': legenda.get('sha256'),
        'classes_legenda': len(classes),
        'classes_rgb_correspondentes': len(correspondentes),
        'rgb_correspondentes': [list(x) for x in correspondentes],
        'quadros_indexados': len(quadros),
        'arquivos_indexados': [q.get('arquivo') for q in quadros],
        'evidencia_png_bruto_incorporada': False,
        'conclusao': 'Os dados processados nao permitem distinguir cor ausente, diferenca de paleta ou transformacao PNG.',
        'proximo_insumo': 'Bytes PNG originais dos mesmos quadros e legenda do mesmo produto, com hash e metadados PNG.',
        'liberacoes': {'rgb_dbz': False, 'mm_h': False, 'alerta_por_cor': False, 'eta_por_cor': False},
        'problemas_estruturais': problemas,
    }


def main():
    origem = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dados.json')
    destino = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('auditoria_paleta_233.json')
    resultado = auditar(json.loads(origem.read_text(encoding='utf-8')))
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"#233: {resultado['classes_rgb_correspondentes']}/{resultado['classes_legenda']} RGB exatos; {resultado['quadros_indexados']} quadros indexados; PNG bruto indisponivel; problemas={len(resultado['problemas_estruturais'])}")


if __name__ == '__main__':
    main()
