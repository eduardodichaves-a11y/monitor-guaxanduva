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



def analisar_vizinhanca_cinza(rgba):
    """Conta vizinhos ortogonais do cinza exato; nao infere chuva nem dBZ."""
    w, h = rgba.size
    pixels = rgba.load()
    cinza = (200, 200, 200)
    grupos = {'transparente': 0, 'cinza': 0, 'azul_ciano': 0,
              'verde': 0, 'amarelo_laranja': 0, 'vermelho_magenta': 0,
              'outra_cor': 0}
    pixels_cinza = 0
    cinza_isolado_de_outras_cores = 0
    cinza_toca_transparente = 0
    cinza_toca_cor_visivel = 0
    cinza_toca_azul_verde = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a == 0 or (r, g, b) != cinza:
                continue
            pixels_cinza += 1
            vizinhos = []
            for nx, ny in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
                if 0 <= nx < w and 0 <= ny < h:
                    nr, ng, nb, na = pixels[nx, ny]
                    if na == 0:
                        categoria = 'transparente'
                    elif (nr, ng, nb) == cinza:
                        categoria = 'cinza'
                    elif nb > nr and nb >= ng:
                        categoria = 'azul_ciano'
                    elif ng > nr and ng >= nb:
                        categoria = 'verde'
                    elif nr >= ng and ng > nb and nr >= 180:
                        categoria = 'amarelo_laranja'
                    elif nr > ng and nr > nb or (nr > 120 and nb > 120 and ng < 120):
                        categoria = 'vermelho_magenta'
                    else:
                        categoria = 'outra_cor'
                    grupos[categoria] += 1
                    vizinhos.append(categoria)
            if all(v == 'cinza' for v in vizinhos):
                cinza_isolado_de_outras_cores += 1
            if 'transparente' in vizinhos:
                cinza_toca_transparente += 1
            if any(v not in ('cinza','transparente') for v in vizinhos):
                cinza_toca_cor_visivel += 1
            if any(v in ('azul_ciano','verde') for v in vizinhos):
                cinza_toca_azul_verde += 1
    return {
        'rgb_cinza': list(cinza), 'pixels_cinza': pixels_cinza,
        'contatos_ortogonais_por_familia': grupos,
        'pixels_cinza_sem_contato_com_outra_cor': cinza_isolado_de_outras_cores,
        'pixels_cinza_tocam_transparente': cinza_toca_transparente,
        'pixels_cinza_tocam_cor_visivel': cinza_toca_cor_visivel,
        'pixels_cinza_tocam_azul_ou_verde': cinza_toca_azul_verde,
        'nota': ('Contatos contam pares de pixels adjacentes e nao chuva. '
                 'Classificacao cromatica exploratoria, sem escala dBZ. '
                 'Bordas externas da imagem nao contam como transparencia.')
    }

def analisar_vizinhanca_transparencia(rgba):
    """Matriz de fronteira transparente/cores: pares ortogonais exatos, sem inferir dBZ.

    Cada par e contado uma unica vez, partindo do pixel transparente.
    Proporcoes por cor usam os pixels visiveis daquela cor no PNG como denominador.
    """
    w, h = rgba.size
    px = rgba.load()
    frequencia_visivel = Counter()
    transparentes = 0
    for r, g, b, a in rgba.getdata():
        if a == 0:
            transparentes += 1
        else:
            frequencia_visivel[(r, g, b)] += 1
    pares = Counter()
    pixels_transparentes_com_vizinho = Counter()
    for y in range(h):
        for x in range(w):
            if px[x, y][3] != 0:
                continue
            cores_vizinhas = set()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    r, g, b, a = px[nx, ny]
                    if a > 0:
                        rgb = (r, g, b)
                        pares[rgb] += 1
                        cores_vizinhas.add(rgb)
            for rgb in cores_vizinhas:
                pixels_transparentes_com_vizinho[rgb] += 1
    detalhes = []
    for rgb, n in sorted(pares.items(), key=lambda kv: (-kv[1], kv[0])):
        total = frequencia_visivel[rgb]
        detalhes.append({
            'rgb': list(rgb), 'pares_ortogonais_com_transparencia': n,
            'pixels_transparentes_que_tocam_rgb': pixels_transparentes_com_vizinho[rgb],
            'pixels_visiveis_dessa_cor': total,
            'pares_por_1000_pixels_dessa_cor': round(1000 * n / total, 3) if total else None,
        })
    return {
        'pixels_transparentes': transparentes,
        'total_pares_transparente_visivel': sum(pares.values()),
        'contatos_por_rgb_exato': detalhes,
        'nota': ('Pares ortogonais entre transparencia e RGB exato; frequencias e '
                 'normalizacao nao definem intensidade de chuva nem dBZ. '
                 'Bordas externas nao sao consideradas pixels transparentes.')
    }


def analisar_png(nome, bruto, aviso_tls, rgb_legenda):
    img = Image.open(io.BytesIO(bruto))
    img.load()
    # Inventario integral de pixels RGBA, sem aproximacao cromatica.
    rgba = img.convert('RGBA')
    contagem = Counter((r, g, b) for r, g, b, a in rgba.getdata() if a > 0)
    paleta = img.getpalette() if img.mode == 'P' else None
    info = {str(k): str(v)[:120] for k, v in img.info.items() if k != 'transparency'}
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
        'diagnostico_espacial_cinza': analisar_vizinhanca_cinza(rgba),
        'diagnostico_vizinhanca_transparencia': analisar_vizinhanca_transparencia(rgba),
        'indices_plte_utilizados': indices_plte,
    }


def analisar_transicao_temporal(pares):
    """Compara dois PNGs no mesmo pixel, sem confundir contato espacial com evolucao.

    Nao corrige adveccao do eco: transicao local nao comprova transformacao da chuva.
    """
    if len(pares) != 2:
        return {'status': 'AGUARDANDO_DOIS_QUADROS_VALIDOS'}
    (nome0, bruto0), (nome1, bruto1) = pares
    im0 = Image.open(io.BytesIO(bruto0)).convert('RGBA')
    im1 = Image.open(io.BytesIO(bruto1)).convert('RGBA')
    if im0.size != im1.size:
        return {'status': 'DIMENSOES_DIFERENTES', 'arquivos': [nome0, nome1]}
    def familia(px):
        r, g, b, a = px
        if a == 0: return 'transparente'
        if (r, g, b) == (200, 200, 200): return 'cinza'
        if b >= r and b >= g and b >= 90: return 'azul_ciano'
        if g > r and g > b: return 'verde'
        if r >= 150 and g >= 55 and b < 120: return 'amarelo_laranja'
        if r >= 130 and (g < 80 or b >= 110): return 'vermelho_magenta'
        return 'outra_cor'
    matriz = Counter()
    for a, b in zip(im0.getdata(), im1.getdata()):
        matriz[(familia(a), familia(b))] += 1
    origens = ('cinza', 'transparente', 'azul_ciano', 'verde')
    saidas = ('cinza', 'transparente', 'azul_ciano', 'verde', 'amarelo_laranja', 'vermelho_magenta', 'outra_cor')
    linhas = {}
    for origem in origens:
        total = sum(matriz[(origem, destino)] for destino in saidas)
        linhas[origem] = {
            'pixels_origem': total,
            'destinos': {destino: matriz[(origem, destino)] for destino in saidas},
            'percentual_para_azul_ciano': round(100 * matriz[(origem, 'azul_ciano')] / total, 3) if total else None,
        }
    return {'status': 'COMPARACAO_EXPLORATORIA', 'arquivos': [nome0, nome1],
            'dimensoes': list(im0.size), 'transicoes': linhas,
            'nota': 'Mesma coordenada de pixel em dois horarios; deslocamento pelo vento nao corrigido. '
                    'Transparencia nao representa chuva. Famílias RGB heuristicas; sem dBZ/mm/h.'}


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
    pares_temporais = []
    for nome in nomes:
        try:
            bruto, aviso_tls = baixar(nome)
            resultado['quadros'].append(analisar_png(nome, bruto, aviso_tls, rgb_legenda))
            pares_temporais.append((nome, bruto))
        except Exception as e:
            resultado['erros'].append({'arquivo': nome, 'erro': f'{type(e).__name__}: {str(e)[:180]}'})
    resultado['diagnostico_transicao_temporal'] = analisar_transicao_temporal(pares_temporais)
    historico = {}
    anterior = historico_anterior if isinstance(historico_anterior, dict) else {}
    # Recuperacao automatica e idempotente do historico anterior ao auditor espacial.
    # O commit antigo e imutavel; nao reverte codigo nem outros arquivos do repositorio.
    URL_HISTORICO = ('https://raw.githubusercontent.com/'
                     'eduardodichaves-a11y/monitor-guaxanduva/'
                     '6a16ac7/auditoria_png_234.json')
    try:
        resposta = requests.get(URL_HISTORICO, timeout=(10, 25))
        resposta.raise_for_status()
        historico_legado = resposta.json().get('historico_indices_plte', [])
        for registro in historico_legado:
            if isinstance(registro, dict) and isinstance(registro.get('arquivo'), str):
                historico[registro['arquivo']] = registro
        resultado['recuperacao_historica'] = {
            'origem_commit': '6a16ac7', 'quadros_legados': len(historico_legado),
            'status': 'RECUPERADO'}
    except (requests.RequestException, ValueError) as exc:
        resultado['recuperacao_historica'] = {
            'origem_commit': '6a16ac7', 'status': 'PENDENTE',
            'motivo': f'{type(exc).__name__}: {str(exc)[:140]}'}
    for registro in anterior.get('historico_indices_plte', []):
        if isinstance(registro, dict) and isinstance(registro.get('arquivo'), str):
            historico[registro['arquivo']] = registro
    for quadro in resultado['quadros']:
        anterior_quadro = historico.get(quadro['arquivo'], {})
        historico[quadro['arquivo']] = {
            'arquivo': quadro['arquivo'], 'sha256_png': quadro['sha256'],
            'indices': [
                {'indice': x['indice_png'], 'rgb': x['rgb'], 'pixels': x['pixels']}
                for x in quadro.get('indices_plte_utilizados', []) if x.get('visivel')
            ],
            'diagnostico_espacial_cinza': (quadro.get('diagnostico_espacial_cinza')
                                            or anterior_quadro.get('diagnostico_espacial_cinza')),
            'diagnostico_vizinhanca_transparencia': (quadro.get('diagnostico_vizinhanca_transparencia')
                                                      or anterior_quadro.get('diagnostico_vizinhanca_transparencia'))
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
        'nota': 'Indices PNG nao sao valores dBZ; estatistica por quadro.'
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
