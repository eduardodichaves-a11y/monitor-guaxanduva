#!/usr/bin/env python3
"""#234: evidencia dos bytes PNG RadarSC COMP, sem persistir imagens ou liberar dBZ/mm/h.
Uso: python auditar_png_nativo_234.py [dados.json] [auditoria_png_234.json]
Dependencias: requests, Pillow. Executar somente com rede; ate 2 PNGs por rodada.
"""
import hashlib
import io
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image

URL = 'https://sifap.defesacivil.sc.gov.br/radarsc/rest/radar/getImagem'
MAX_BYTES = 12 * 1024 * 1024
MAX_FRAMES = 2


def baixar(nome):
    params = {'prod': 4, 'radar': 'COMP', 'file': nome}
    aviso_tls = None
    try:
        r = requests.get(URL, params=params, timeout=(12, 35), stream=True)
    except requests.exceptions.SSLError:
        aviso_tls = 'CERTIFICADO_NAO_VALIDADO'
        r = requests.get(URL, params=params, timeout=(12, 35), stream=True, verify=False)
    with r:
        r.raise_for_status()
        partes, total = [], 0
        for bloco in r.iter_content(65536):
            total += len(bloco)
            if total > MAX_BYTES:
                raise ValueError('png_excede_limite_12_mib')
            partes.append(bloco)
    bruto = b''.join(partes)
    if not bruto.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('resposta_nao_png')
    return bruto, aviso_tls


def analisar_png(nome, bruto, aviso_tls, rgb_legenda):
    img = Image.open(io.BytesIO(bruto))
    img.load()
    # Inventario integral de pixels RGBA, sem aproximacao cromatica.
    rgba = img.convert('RGBA')
    contagem = Counter((r, g, b) for r, g, b, a in rgba.getdata() if a > 0)
    paleta = img.getpalette() if img.mode == 'P' else None
    info = {str(k): str(v)[:120] for k, v in img.info.items() if k != 'transparency'}
    # Inspecao dos indices PLTE nativos: indice de arquivo NAO e classe dBZ.
    indices_plte = []
    if img.mode == 'P' and paleta:
        contagem_indices = Counter(img.getdata())
        transparencia = img.info.get('transparency')
        for indice, n in sorted(contagem_indices.items()):
            pos = 3 * indice
            if pos + 3 > len(paleta):
                continue
            rgb = tuple(paleta[pos:pos + 3])
            if isinstance(transparencia, bytes):
                alpha = transparencia[indice] if indice < len(transparencia) else 255
            elif isinstance(transparencia, int):
                alpha = 0 if indice == transparencia else 255
            else:
                alpha = 255
            indices_plte.append({'indice_png': indice, 'rgb': list(rgb),
                                 'pixels': n, 'alpha': alpha,
                                 'visivel': alpha > 0,
                                 'consta_legenda_rgb': rgb in rgb_legenda})
    comuns = [{'rgb': list(rgb), 'pixels': n} for rgb, n in contagem.most_common(40)]
    exatas = [{'rgb': list(rgb), 'pixels': contagem[rgb]} for rgb in sorted(rgb_legenda) if contagem[rgb]]
    return {
        'arquivo': nome, 'bytes': len(bruto), 'sha256': hashlib.sha256(bruto).hexdigest(),
        'certificado': aviso_tls or 'VALIDADO_PELA_BIBLIOTECA',
        'modo_png_original': img.mode, 'dimensoes_px': [img.width, img.height],
        'tem_paleta_plte': paleta is not None,
        'entradas_plte': len(paleta)//3 if paleta else 0,
        'sha256_plte_rgb': hashlib.sha256(bytes(paleta)).hexdigest() if paleta else None,
        'metadados_png': info, 'cores_rgba_visiveis_distintas': len(contagem),
        'cores_mais_frequentes': comuns, 'cores_legenda_exatas_presentes': exatas,
        'pixels_visiveis': sum(contagem.values()),
        'indices_plte_utilizados': indices_plte,
        'nota_indices_plte': ('Indices sao locais ao PNG e podem mudar entre quadros; '
                              'ordem PLTE nao comprova ordem de refletividade.'),
    }


def executar(dados, historico_anterior=None):
    radar = dados.get('radar') or {}
    leg = (radar.get('legenda_oficial') or {}).get('classes') or []
    rgb_legenda = {tuple(c['rgb']) for c in leg if isinstance(c, dict) and isinstance(c.get('rgb'), list) and len(c['rgb']) == 3}
    quadros = (radar.get('validacao_paleta_radar') or {}).get('por_quadro') or []
    nomes = list(dict.fromkeys(q.get('arquivo') for q in quadros if isinstance(q, dict) and q.get('arquivo')))[-MAX_FRAMES:]
    resultado = {
        'versao': '#234', 'gerado_em_utc': datetime.now(timezone.utc).isoformat(),
        'produto': 'COMP', 'fonte': URL, 'limite_png_por_execucao': MAX_FRAMES,
        'classes_legenda': len(rgb_legenda), 'quadros': [], 'erros': [],
        'restricoes': {'rgb_dbz': False, 'mm_h': False, 'alerta_por_cor': False, 'eta_por_cor': False},
        'observacao': 'Cores exatas observadas nao provam correspondencia fisica dBZ. Nao persiste PNG.'
    }
    for nome in nomes:
        try:
            bruto, aviso_tls = baixar(nome)
            resultado['quadros'].append(analisar_png(nome, bruto, aviso_tls, rgb_legenda))
        except Exception as e:
            resultado['erros'].append({'arquivo': nome, 'erro': f'{type(e).__name__}: {str(e)[:180]}'})
    # Teste empirico de estabilidade: o mesmo indice PNG manteve o mesmo RGB?
    if len(resultado['quadros']) >= 2:
        a, b = resultado['quadros'][-2:]
        ma = {x['indice_png']: tuple(x['rgb']) for x in a['indices_plte_utilizados']}
        mb = {x['indice_png']: tuple(x['rgb']) for x in b['indices_plte_utilizados']}
        compartilhados = sorted(set(ma) & set(mb))
        divergentes = [{'indice_png': i, 'rgb_quadro_anterior': list(ma[i]),
                        'rgb_quadro_atual': list(mb[i])}
                       for i in compartilhados if ma[i] != mb[i]]
        resultado['comparacao_indices_plte'] = {
            'indices_compartilhados': len(compartilhados),
            'indices_rgb_alterado': len(divergentes),
            'divergencias': divergentes,
            'ordem_plte_estavel_nestes_quadros': len(divergentes) == 0 if compartilhados else None,
            'aviso': 'Estabilidade entre dois quadros nao prova correspondencia com dBZ.'
        }
    # Historico compacto e cumulativo: preserva pares indice/RGB por quadro,
    # sem persistir imagens e sem confundir indice PNG com dBZ.
    historico = {}
    anterior = historico_anterior if isinstance(historico_anterior, dict) else {}
    for registro in anterior.get('historico_indices_plte', []):
        if isinstance(registro, dict) and isinstance(registro.get('arquivo'), str):
            historico[registro['arquivo']] = registro
    for quadro in resultado['quadros']:
        historico[quadro['arquivo']] = {
            'arquivo': quadro['arquivo'],
            'sha256_png': quadro['sha256'],
            'indices': [
                {'indice': x['indice_png'], 'rgb': x['rgb'], 'pixels': x['pixels']}
                for x in quadro.get('indices_plte_utilizados', []) if x.get('visivel')
            ]
        }
    registros = sorted(historico.values(), key=lambda x: x['arquivo'])[-240:]
    resultado['historico_indices_plte'] = registros
    por_indice = {}
    for registro in registros:
        for item in registro.get('indices', []):
            chave = str(item['indice'])
            rgb = ','.join(str(v) for v in item['rgb'])
            celula = por_indice.setdefault(chave, {})
            celula[rgb] = celula.get(rgb, 0) + 1
    resultado['estatistica_indices_plte'] = {
        'quadros_distintos': len(registros),
        'cores_por_indice': {
            i: [{'rgb': [int(v) for v in rgb.split(',')], 'quadros': n}
                for rgb, n in sorted(cores.items(), key=lambda x: (-x[1], x[0]))]
            for i, cores in sorted(por_indice.items(), key=lambda x: int(x[0]))
        },
        'nota': 'Frequencia de indices por quadro; nao corresponde a intensidade nem a probabilidade de dBZ.'
    }
    resultado['status'] = 'EVIDENCIA_PNG_COLETADA' if resultado['quadros'] else 'SEM_PNG_VALIDO' 
    return resultado


if __name__ == '__main__':
    origem = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('dados.json')
    destino = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('auditoria_png_234.json')
    dados = json.loads(origem.read_text(encoding='utf-8'))
    anterior = None
    if destino.is_file():
        try:
            anterior = json.loads(destino.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
    resultado = executar(dados, anterior)
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"#234 {resultado['status']}: {len(resultado['quadros'])} PNGs; {len(resultado['erros'])} falhas")
