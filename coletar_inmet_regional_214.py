#!/usr/bin/env python3
"""#214: coleta observacoes horarias reais do INMET perto dos ecos #213.
Nao altera dados.json. Falha fechada: sem dado INMET => observacoes vazias.
Amostras horarias nao validam um pixel isolado ou classes C1-C16.
"""
import argparse
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = 'https://apitempo.inmet.gov.br'
HEADERS = {'User-Agent': 'MonitorGuaxanduva/214 (auditoria de observacoes INMET)', 'Accept': 'application/json'}

def obter(caminho):
    req = urllib.request.Request(BASE + caminho, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as resposta:
        return json.load(resposta)

def numero(valor):
    try:
        n = float(str(valor).replace(',', '.'))
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None

def distancia(a, b, c, d):
    a, c = math.radians(a), math.radians(c)
    h = math.sin((c-a)/2)**2 + math.cos(a)*math.cos(c)*math.sin(math.radians(d-b)/2)**2
    return 12742.0176 * math.asin(min(1, math.sqrt(h)))

def coletar(territorio, raio_km=50):
    quadro = datetime.fromisoformat(territorio['quadro_radar'].replace('Z', '+00:00'))
    if quadro.tzinfo is None:
        raise ValueError('Quadro sem fuso horario')
    grupos = [g for g in territorio.get('agrupamentos', []) if numero(g.get('latitude')) is not None and numero(g.get('longitude')) is not None]
    resultado = {'versao': '#214-INMET', 'fonte': 'INMET - API publica de estacoes automaticas',
                 'quadro_radar': territorio['quadro_radar'], 'observacoes': [], 'diagnostico': [],
                 'nota': 'CHUVA e acumulado horario; horario de observacao em UTC; nao valida o pixel isolado.'}
    if not grupos:
        resultado['diagnostico'].append('Sem agrupamentos com coordenadas')
        return resultado
    try:
        estacoes = obter('/estacoes/T')
        if not isinstance(estacoes, list):
            raise ValueError('Cadastro INMET nao retornou lista')
    except (OSError, ValueError) as e:
        resultado['diagnostico'].append('Falha no cadastro INMET: ' + str(e))
        return resultado
    selecionadas = []
    for e in estacoes:
        lat, lon = numero(e.get('VL_LATITUDE')), numero(e.get('VL_LONGITUDE'))
        if lat is None or lon is None:
            continue
        km = min(distancia(lat, lon, float(g['latitude']), float(g['longitude'])) for g in grupos)
        if km <= raio_km and e.get('CD_ESTACAO'):
            selecionadas.append((km, e, lat, lon))
    resultado['diagnostico'].append(f'Estacoes INMET no raio {raio_km} km: {len(selecionadas)}')
    data = quadro.astimezone(timezone.utc).date()
    # Consultar dia anterior tambem: o quadro pode cair na virada UTC.
    inicio, fim = (data-timedelta(days=1)).isoformat(), data.isoformat()
    for km, est, lat, lon in sorted(selecionadas, key=lambda x: x[0]):
        codigo = est['CD_ESTACAO']
        try:
            linhas = obter(f'/estacao/{inicio}/{fim}/{codigo}')
            if not isinstance(linhas, list):
                raise ValueError('Dados nao retornaram lista')
            aceitas = 0
            for linha in linhas:
                chuva = numero(linha.get('CHUVA'))
                dia = linha.get('DT_MEDICAO')
                hora = str(linha.get('HR_MEDICAO', '')).zfill(4)
                if chuva is None or chuva < 0 or not dia or len(hora) != 4 or not hora.isdigit():
                    continue
                try:
                    instante = datetime.strptime(f'{dia} {hora}', '%Y-%m-%d %H%M').replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                # Selecionar observacoes proximas, mas #214 decidirá a janela final.
                if abs((instante-quadro).total_seconds()) > 2*3600:
                    continue
                resultado['observacoes'].append({'fonte': 'INMET', 'estacao': est.get('DC_NOME') or codigo,
                    'codigo': codigo, 'municipio': est.get('DC_NOME'), 'latitude': lat, 'longitude': lon,
                    'horario': instante.isoformat(), 'precipitacao_mm': chuva, 'periodo_minutos': 60,
                    'nota': 'Acumulado horario INMET; conferir convencao do intervalo da estacao'})
                aceitas += 1
            resultado['diagnostico'].append(f'{codigo}: {aceitas} observacoes proximas')
        except (OSError, ValueError) as e:
            resultado['diagnostico'].append(f'{codigo}: consulta indisponivel: {e}')
    return resultado

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('territorio', nargs='?', default='auditoria_territorial_213.json')
    ap.add_argument('--saida', default='observacoes_regionais_214.json')
    ap.add_argument('--raio-km', type=float, default=50)
    args = ap.parse_args()
    entrada = json.loads(Path(args.territorio).read_text(encoding='utf-8'))
    saida = coletar(entrada, args.raio_km)
    Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Observacoes INMET:', len(saida['observacoes']))
    print('\n'.join(saida['diagnostico']))

if __name__ == '__main__':
    main()
