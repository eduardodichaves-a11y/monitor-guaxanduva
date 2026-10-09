"""Integra observações manuais sem alterar o modelo hidráulico nem alertas."""
import json
from pathlib import Path

PADRAO = 'observacao_campo_guaxanduva_*.json'

def integrar_observacoes_campo(validacao, pasta='.'):
    if not isinstance(validacao, dict):
        return validacao
    registros = validacao.setdefault('medicoes', [])
    if not isinstance(registros, list):
        return validacao
    existentes = {(str(x.get('data')), str(x.get('nivel_m')), str(x.get('arquivo_origem', ''))) for x in registros if isinstance(x, dict)}
    for caminho in sorted(Path(pasta).glob(PADRAO)):
        try:
            documento = json.loads(caminho.read_text(encoding='utf-8'))
            if documento.get('tipo') != 'MEDICAO_MANUAL_DE_CAMPO' or documento.get('rio') != 'Guaxanduva':
                continue
            nivel = float(documento['nivel_informado_m'])
            data = str(documento['data_local'])
            if not (0 <= nivel <= 20 and len(data) == 10 and data[4] == '-' and data[7] == '-'):
                continue
            chave = (data, str(nivel), caminho.name)
            if chave in existentes:
                continue
            registro = {'data':data,'nivel_m':nivel,'origem':'medicao_manual_usuario',
                        'qualidade':'OBSERVACAO_DE_CAMPO_NAO_INSTRUMENTAL',
                        'referencia_vertical':documento.get('referencia_vertical','NAO_CONFIRMADA'),
                        'horario_descritivo':documento.get('horario','NAO_CONFIRMADO'),
                        'timezone':documento.get('timezone','America/Sao_Paulo'),
                        'arquivo_origem':caminho.name}
            registros.append(registro)
            existentes.add(chave)
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            print(f'CAMPO: arquivo ignorado {caminho.name}: {exc}')
    validacao['quantidade_medicoes'] = len(registros)
    validacao['uso_operacional'] = False
    validacao['altera_v021'] = False
    return validacao
