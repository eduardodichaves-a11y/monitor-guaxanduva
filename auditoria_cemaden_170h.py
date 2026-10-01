import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

UTC = ZoneInfo("UTC")
FUSO = ZoneInfo("America/Sao_Paulo")
ARQUIVO_DADOS = "dados.json"
ARQUIVO_SAIDA = "auditoria_cemaden_170h.json"
ARQUIVO_HISTORICO_ZR = "historico_zr_170.json"
ARQUIVO_HISTORICO_CHUVA = "historico_cemaden_chuva_170h1.json"
BASE_HORARIO = "https://mapservices.cemaden.gov.br/MapaInterativoWS/resources/horario/"


def agora():
    return datetime.now(FUSO)


def carregar_dados():
    with open(ARQUIVO_DADOS, "r", encoding="utf-8") as f:
        dados = json.load(f)
    if not isinstance(dados, dict):
        raise ValueError("dados.json sem objeto raiz valido")
    return dados


def numero(valor):
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(str(valor).strip().replace(",", "."))
    except Exception:
        return None


def extrair_id_estacao(dados):
    chuva = dados.get("chuva") or {}
    selecionada = chuva.get("estacao_selecionada") or {}
    ident = selecionada.get("id")
    if ident is None:
        bloco144 = dados.get("chuva_observada_cemaden_144") or {}
        ident = (bloco144.get("estacao") or {}).get("id")
    return ident, selecionada


def parsear_matriz(payload):
    if not isinstance(payload, dict):
        raise ValueError("endpoint horario nao retornou objeto JSON")

    datas = payload.get("datas")
    horarios = payload.get("horarios")
    acumulados = payload.get("acumulados")

    if not (
        isinstance(datas, list)
        and isinstance(horarios, list)
        and isinstance(acumulados, list)
    ):
        raise ValueError("endpoint sem datas/horarios/acumulados validos")

    celulas = []
    for i, data_txt in enumerate(datas):
        if i >= len(acumulados) or not isinstance(acumulados[i], list):
            continue
        linha = acumulados[i]

        for j, hora_txt in enumerate(horarios):
            if j >= len(linha):
                continue

            mm = numero(linha[j])
            if mm is None:
                continue

            try:
                data_base = datetime.strptime(str(data_txt).strip(), "%d/%m/%Y")
            except Exception:
                continue

            achado = re.search(r"(\d{1,2})", str(hora_txt))
            if not achado:
                continue

            hora = int(achado.group(1))
            if not 0 <= hora <= 23:
                continue

            instante = data_base.replace(
                hour=hora,
                minute=0,
                second=0,
                microsecond=0,
                tzinfo=UTC,
            )
            celulas.append({
                "instante_utc": instante,
                "rotulo_endpoint_data": str(data_txt),
                "rotulo_endpoint_hora": str(hora_txt),
                "valor_mm": mm,
            })

    unicas = {x["instante_utc"].isoformat(): x for x in celulas}
    return sorted(unicas.values(), key=lambda x: x["instante_utc"])


def consultar_horario(idestacao, parametro=23):
    url = BASE_HORARIO + str(idestacao) + "/" + str(parametro)
    r = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
    )
    r.raise_for_status()
    payload = r.json()
    celulas = parsear_matriz(payload)

    serializadas = []
    for x in celulas:
        serializadas.append({
            "instante_utc": x["instante_utc"].isoformat(),
            "instante_local": x["instante_utc"].astimezone(FUSO).isoformat(),
            "rotulo_endpoint_data": x["rotulo_endpoint_data"],
            "rotulo_endpoint_hora": x["rotulo_endpoint_hora"],
            "valor_mm": x["valor_mm"],
        })

    continuidade = True
    deltas = []
    for a, b in zip(celulas, celulas[1:]):
        delta = (b["instante_utc"] - a["instante_utc"]).total_seconds() / 3600.0
        deltas.append(delta)
        if abs(delta - 1.0) > 1e-9:
            continuidade = False

    return {
        "endpoint": url,
        "parametro_final": parametro,
        "http_status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "chaves_raiz": sorted(payload.keys()),
        "quantidade_celulas_numericas": len(celulas),
        "continuidade_horaria": continuidade,
        "deltas_horas": deltas,
        "primeira_celula": serializadas[0] if serializadas else None,
        "ultima_celula": serializadas[-1] if serializadas else None,
        "soma_celulas_mm": round(sum(x["valor_mm"] for x in celulas), 2),
        "celulas": serializadas,
    }



def salvar_historico_chuva_cemaden_170h1():
    """
    #170-H1 - extrai somente episódios CEMADEN com chuva > 0 do histórico Z-R.

    O arquivo de saída é propositalmente compacto: não copia imagens, radar,
    autópsias RGB ou outras estruturas pesadas. Ele serve para auditoria
    temporal humana e permanece totalmente fail-closed.
    """
    documento = {
        "monitor": "Monitor Guaxanduva",
        "versao": "#170-H1",
        "tipo": "historico_compacto_episodios_chuvosos_cemaden",
        "natureza": "DIAGNOSTICO_FAIL_CLOSED",
        "atualizado_em": agora().isoformat(),
        "arquivo_fonte": ARQUIVO_HISTORICO_ZR,
        "status": "indisponivel",
        "quantidade_episodios": 0,
        "pareamento_temporal_validado": False,
        "borda_horaria_inequivoca": False,
        "elegivel_calibracao_zr": False,
        "zr_validada": False,
        "conversao_dbz_mm_h_liberada": False,
        "regra_seguranca": (
            "Este arquivo apenas torna legiveis os episodios CEMADEN com chuva "
            "ja preservados no historico #170. Nao reinterpreta timestamps, nao "
            "pareia radar e pluviometro e nao libera Z-R."
        ),
        "episodios": [],
    }

    try:
        with open(ARQUIVO_HISTORICO_ZR, "r", encoding="utf-8") as f:
            bruto = json.load(f)
        registros = bruto.get("registros") if isinstance(bruto, dict) else None
        if not isinstance(registros, list):
            raise ValueError("historico Z-R sem lista de registros")

        por_chave = {}
        for registro in registros:
            if not isinstance(registro, dict):
                continue
            est = (
                registro.get("estacao")
                or registro.get("estacao_cemaden")
                or {}
            )
            rede = str(registro.get("rede") or est.get("rede") or "")
            if rede != "CEMADEN":
                continue

            chuva = registro.get("chuva_observada") or {}
            mm1 = numero(chuva.get("acumulado_1h_mm"))
            if mm1 is None or mm1 <= 0:
                continue

            hora_utc = chuva.get("rotulo_ultima_celula_utc")
            hora_local = chuva.get("rotulo_ultima_celula_local")
            ident = est.get("id") or est.get("codigo")
            chave = "|".join([
                str(ident or "sem_estacao"),
                str(hora_utc or hora_local or "sem_hora"),
            ])

            diag = registro.get("diagnostico_temporal_170_e") or {}
            fim = diag.get("hipotese_rotulo_como_fim_da_hora") or {}
            inicio = diag.get("hipotese_rotulo_como_inicio_da_hora") or {}

            por_chave[chave] = {
                "chave": chave,
                "registrado_em": registro.get("registrado_em"),
                "estacao": {
                    "id": est.get("id"),
                    "codigo": est.get("codigo"),
                    "nome": est.get("nome"),
                    "cidade": est.get("cidade"),
                    "uf": est.get("uf"),
                    "distancia_comasa_aprox_km": est.get("distancia_comasa_aprox_km"),
                },
                "chuva_observada": {
                    "acumulado_1h_mm": mm1,
                    "acumulado_6h_mm": numero(chuva.get("acumulado_6h_mm")),
                    "acumulado_24h_mm": numero(chuva.get("acumulado_24h_mm")),
                    "rotulo_ultima_celula_utc": hora_utc,
                    "rotulo_ultima_celula_local": hora_local,
                    "dados_frescos": chuva.get("dados_frescos"),
                    "idade_leitura_min": chuva.get("idade_leitura_min"),
                    "produto_temporal": chuva.get("produto_temporal"),
                },
                "diagnostico_temporal": {
                    "rotulo_referencia": diag.get("rotulo_referencia"),
                    "quadros_radar_com_timestamp_valido": diag.get(
                        "quadros_radar_com_timestamp_valido"
                    ),
                    "quadros_na_janela_rotulo_como_fim": fim.get(
                        "quadros_radar_na_janela"
                    ),
                    "quadros_na_janela_rotulo_como_inicio": inicio.get(
                        "quadros_radar_na_janela"
                    ),
                    "borda_horaria_inequivoca": False,
                    "pareamento_temporal_validado": False,
                },
            }

        episodios = sorted(
            por_chave.values(),
            key=lambda x: (
                str((x.get("chuva_observada") or {}).get("rotulo_ultima_celula_utc") or ""),
                str((x.get("estacao") or {}).get("codigo") or ""),
            ),
        )
        documento["episodios"] = episodios
        documento["quantidade_episodios"] = len(episodios)
        documento["status"] = (
            "episodios_chuvosos_compactados"
            if episodios
            else "sem_episodio_chuvoso_no_historico"
        )
    except Exception as e:
        documento["status"] = "falha_extracao_fail_closed"
        documento["erro"] = str(e)[:500]

    with open(ARQUIVO_HISTORICO_CHUVA, "w", encoding="utf-8") as f:
        json.dump(documento, f, ensure_ascii=False, indent=2)

    return documento


def main():
    base = {
        "monitor": "Monitor Guaxanduva",
        "versao": "#170-H",
        "tipo": "auditoria_proveniencia_temporal_cemaden",
        "natureza": "DIAGNOSTICO_FAIL_CLOSED",
        "atualizado_em": agora().isoformat(),
        "status": "indisponivel",
        "pareamento_temporal_validado": False,
        "borda_horaria_inequivoca": False,
        "elegivel_calibracao_zr": False,
        "zr_validada": False,
        "conversao_dbz_mm_h_liberada": False,
        "regra_seguranca": (
            "A #170-H registra a proveniencia temporal observada no endpoint horario "
            "CEMADEN e a compara com os blocos ja produzidos pelo Monitor. "
            "Coincidencia estrutural ou numerica nao prova sozinha a semantica "
            "inicio/fim do acumulado e nao libera Z-R automaticamente."
        ),
    }

    try:
        dados = carregar_dados()
        idestacao, selecionada = extrair_id_estacao(dados)
        if idestacao is None:
            raise ValueError("sem estacao CEMADEN selecionada")

        endpoint = consultar_horario(idestacao, 23)
        bloco141 = dados.get("investigacao_cemaden_141") or {}
        bloco142 = dados.get("investigacao_cemaden_142") or {}
        bloco143 = dados.get("investigacao_cemaden_143") or {}
        bloco144 = dados.get("chuva_observada_cemaden_144") or {}
        chuva = dados.get("chuva") or {}

        ultima = endpoint.get("ultima_celula") or {}
        ultima_utc = ultima.get("instante_utc")
        ultima_local = ultima.get("instante_local")

        produto_24 = chuva.get("acumulado_24h_mm")
        soma24 = endpoint.get("soma_celulas_mm")
        diferenca24 = None
        coincide24 = False
        if isinstance(produto_24, (int, float)) and isinstance(soma24, (int, float)):
            diferenca24 = round(soma24 - float(produto_24), 2)
            coincide24 = abs(diferenca24) <= 0.01

        horario144_utc = bloco144.get("horario_ultima_celula_utc")
        horario144_local = bloco144.get("horario_ultima_celula_local")

        base.update({
            "status": "auditoria_coletada",
            "estacao": {
                "id": idestacao,
                "codigo": selecionada.get("codigo") or (bloco144.get("estacao") or {}).get("codigo"),
                "nome": selecionada.get("nome") or (bloco144.get("estacao") or {}).get("nome"),
                "cidade": selecionada.get("cidade") or (bloco144.get("estacao") or {}).get("cidade"),
                "uf": selecionada.get("uf") or (bloco144.get("estacao") or {}).get("uf"),
            },
            "endpoint_horario_24h": endpoint,
            "comparacao_com_monitor": {
                "rotulo_ultima_celula_endpoint_utc": ultima_utc,
                "rotulo_ultima_celula_endpoint_local": ultima_local,
                "rotulo_ultima_celula_144_utc": horario144_utc,
                "rotulo_ultima_celula_144_local": horario144_local,
                "timestamp_endpoint_igual_144_utc": (
                    bool(ultima_utc and horario144_utc and ultima_utc == horario144_utc)
                ),
                "timestamp_endpoint_igual_144_local": (
                    bool(ultima_local and horario144_local and ultima_local == horario144_local)
                ),
                "produto_independente_311_24_mm": produto_24,
                "soma_24_celulas_endpoint_mm": soma24,
                "diferenca_24h_mm": diferenca24,
                "coincide_311_24_tolerancia_0_01_mm": coincide24,
                "validacao_24h_bloco_144": bloco144.get("validacao_24h"),
                "status_bloco_144": bloco144.get("status"),
            },
            "cadeia_proveniencia": {
                "rota_descoberta_141": bloco141.get("endpoint"),
                "estrutura_matriz_141": {
                    "datas": bloco141.get("datas"),
                    "horarios": bloco141.get("horarios"),
                    "dimensoes_acumulados": bloco141.get("dimensoes_acumulados"),
                },
                "decodificacao_142_status": bloco142.get("status"),
                "auditoria_janelas_143_status": bloco143.get("status"),
                "operacional_144_status": bloco144.get("status"),
            },
            "interpretacao": (
                "A auditoria demonstra como o rotulo horario do endpoint e preservado "
                "pelo Monitor e permite confrontar a soma das celulas com o produto "
                "independente 311_24. A semantica fisica da borda temporal permanece "
                "fail-closed ate evidencia documental inequivoca ou validacao empirica "
                "independente que demonstre se o rotulo fecha ou inicia o intervalo."
            ),
        })

    except Exception as e:
        base["status"] = "falha_auditoria_fail_closed"
        base["erro"] = str(e)[:500]

    with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
        json.dump(base, f, ensure_ascii=False, indent=2)

    historico_chuva = salvar_historico_chuva_cemaden_170h1()

    print(json.dumps({
        "arquivo": ARQUIVO_SAIDA,
        "versao": base.get("versao"),
        "status": base.get("status"),
        "pareamento_temporal_validado": base.get("pareamento_temporal_validado"),
        "zr_validada": base.get("zr_validada"),
        "conversao_dbz_mm_h_liberada": base.get("conversao_dbz_mm_h_liberada"),
        "historico_chuva_170h1_status": historico_chuva.get("status"),
        "historico_chuva_170h1_episodios": historico_chuva.get("quantidade_episodios"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
