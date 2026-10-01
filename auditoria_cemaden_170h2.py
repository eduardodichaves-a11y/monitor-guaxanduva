import ast
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

UTC = ZoneInfo("UTC")
FUSO = ZoneInfo("America/Sao_Paulo")

ARQUIVO_H1 = "historico_cemaden_chuva_170h1.json"
ARQUIVO_SAIDA = "auditoria_cemaden_170h2.json"
ARQUIVO_HISTORICO = "historico_cemaden_subhorario_170h2.json"

URL_GRAFICO = (
    "https://resources.cemaden.gov.br/graficos/interativo/"
    "grafico_pcds.php?idpcd={idestacao}"
)

TOLERANCIA_MM = 0.01
MIN_CONFIRMACOES_PARA_GATE_GLOBAL = 2


def agora():
    return datetime.now(FUSO)


def numero(valor):
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(str(valor).strip().replace(",", "."))
    except Exception:
        return None


def carregar_json(caminho, padrao=None):
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {} if padrao is None else padrao


def salvar_json(caminho, objeto):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(objeto, f, ensure_ascii=False, indent=2)


def parse_iso(valor):
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def extrair_chamada_grafico(html):
    """
    Extrai a chamada server-side:
      Grafico(2,'mm','Precipitação ...', ... categorias ..., valores ..., acumulada ...)
    sem executar JavaScript.
    """
    m = re.search(
        r"Grafico\s*\(\s*2\s*,\s*'mm'\s*,(.*?)\)\s*;",
        html,
        flags=re.S | re.I,
    )
    if not m:
        return None

    chamada = "Grafico(2,'mm'," + m.group(1) + ")"

    # Captura todos os arrays literais da chamada.
    arrays = re.findall(r"\[[^\[\]]*\]", chamada, flags=re.S)
    if len(arrays) < 3:
        return None

    try:
        categorias = ast.literal_eval(arrays[0])
        incrementos = ast.literal_eval(arrays[1])
        acumulada = ast.literal_eval(arrays[2])
    except Exception:
        return None

    if not (
        isinstance(categorias, list)
        and isinstance(incrementos, list)
        and isinstance(acumulada, list)
    ):
        return None

    n = min(len(categorias), len(incrementos), len(acumulada))
    pontos = []
    for i in range(n):
        rotulo = str(categorias[i]).strip()
        mm = numero(incrementos[i])
        acc = numero(acumulada[i])
        if mm is None:
            continue

        # Exemplo oficial observado:
        # 2026-10-01 02h50 UTC
        mt = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2})h(\d{2})\s+UTC",
            rotulo,
        )
        if not mt:
            continue

        instante = datetime.strptime(
            f"{mt.group(1)} {int(mt.group(2)):02d}:{mt.group(3)}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=UTC)

        pontos.append({
            "instante_utc": instante.isoformat(),
            "instante_local": instante.astimezone(FUSO).isoformat(),
            "rotulo_fonte": rotulo,
            "incremento_mm": mm,
            "acumulada_exibida_mm": acc,
        })

    return pontos


def consultar_subhorario(idestacao):
    url = URL_GRAFICO.format(idestacao=idestacao)
    r = requests.get(
        url,
        timeout=30,
        headers={"User-Agent": "Monitor-Guaxanduva/1.0"},
    )
    r.raise_for_status()
    pontos = extrair_chamada_grafico(r.text)
    return {
        "url": url,
        "http_status": r.status_code,
        "content_type": r.headers.get("content-type"),
        "pontos": pontos or [],
        "quantidade_pontos": len(pontos or []),
    }


def soma_janela_fim(pontos, t):
    """
    Hipótese testada: o valor 1h rotulado em T representa (T-60min, T].
    """
    inicio = t - timedelta(minutes=60)
    usados = []
    total = 0.0

    for p in pontos:
        instante = parse_iso(p.get("instante_utc"))
        mm = numero(p.get("incremento_mm"))
        if instante is None or mm is None:
            continue
        if inicio < instante <= t:
            total += mm
            usados.append(p)

    return round(total, 2), usados


def auditar_episodio(episodio, consulta):
    chuva = episodio.get("chuva_observada") or {}
    est = episodio.get("estacao") or {}
    t = parse_iso(chuva.get("rotulo_ultima_celula_utc"))
    mm1 = numero(chuva.get("acumulado_1h_mm"))

    resultado = {
        "chave_h1": episodio.get("chave"),
        "estacao": est,
        "rotulo_horario_utc": chuva.get("rotulo_ultima_celula_utc"),
        "acumulado_1h_h1_mm": mm1,
        "janela_testada": "(T-60min,T]",
        "soma_subhoraria_mm": None,
        "diferenca_mm": None,
        "quantidade_pontos_na_janela": 0,
        "pontos_na_janela": [],
        "coincide_tolerancia_0_01_mm": False,
        "evidencia_temporal_positiva": False,
        "motivo": "sem_dados_suficientes",
    }

    if t is None or mm1 is None:
        resultado["motivo"] = "episodio_h1_sem_timestamp_ou_1h"
        return resultado

    soma, usados = soma_janela_fim(consulta.get("pontos") or [], t)
    resultado["soma_subhoraria_mm"] = soma
    resultado["quantidade_pontos_na_janela"] = len(usados)
    resultado["pontos_na_janela"] = usados

    # Não validar uma hora chuvosa por soma vazia/zero.
    if not usados:
        resultado["motivo"] = "nenhum_ponto_subhorario_na_janela"
        return resultado

    diferenca = round(soma - mm1, 2)
    coincide = abs(diferenca) <= TOLERANCIA_MM
    resultado["diferenca_mm"] = diferenca
    resultado["coincide_tolerancia_0_01_mm"] = coincide
    resultado["evidencia_temporal_positiva"] = bool(coincide and mm1 > 0)
    resultado["motivo"] = (
        "soma_subhoraria_fecha_exatamente_com_1h"
        if resultado["evidencia_temporal_positiva"]
        else "soma_subhoraria_nao_fecha_com_1h"
    )
    return resultado


def carregar_historico():
    hist = carregar_json(ARQUIVO_HISTORICO, {})
    if not isinstance(hist, dict):
        hist = {}
    registros = hist.get("registros")
    if not isinstance(registros, list):
        registros = []
    return registros


def chave_prova(item):
    est = item.get("estacao") or {}
    return "|".join([
        str(est.get("id") or est.get("codigo") or ""),
        str(item.get("rotulo_horario_utc") or ""),
    ])


def main():
    saida = {
        "monitor": "Monitor Guaxanduva",
        "versao": "#170-H2",
        "tipo": "auditoria_empirica_subhoraria_cemaden",
        "natureza": "DIAGNOSTICO_FAIL_CLOSED",
        "atualizado_em": agora().isoformat(),
        "status": "indisponivel",
        "hipotese_testada": (
            "O acumulado CEMADEN de 1h rotulado em T corresponde "
            "a soma dos incrementos sub-horarios em (T-60min,T]."
        ),
        "fonte_subhoraria": (
            "grafico_pcds.php publico do CEMADEN; serie server-side "
            "Precipitacao Acumulada nas Ultimas 4 horas, timestamps UTC."
        ),
        "tolerancia_mm": TOLERANCIA_MM,
        "confirmacoes_nesta_execucao": 0,
        "confirmacoes_historicas_distintas": 0,
        "borda_horaria_retrospectiva_empiricamente_confirmada": False,
        "pareamento_temporal_validado": False,
        "elegivel_calibracao_zr": False,
        "zr_validada": False,
        "conversao_dbz_mm_h_liberada": False,
        "regra_seguranca": (
            "H2 testa somente a semantica temporal CEMADEN. Mesmo com "
            "confirmacoes positivas, nao valida pareamento espacial radar-pluviometro, "
            "nao calibra Z-R e nao libera dBZ para mm/h."
        ),
        "consultas": [],
        "resultados": [],
    }

    try:
        h1 = carregar_json(ARQUIVO_H1, {})
        episodios = h1.get("episodios") if isinstance(h1, dict) else None
        if not isinstance(episodios, list):
            raise ValueError("H1 sem lista de episodios")

        ids = []
        for ep in episodios:
            est = ep.get("estacao") or {}
            ident = est.get("id")
            if ident is not None and ident not in ids:
                ids.append(ident)

        consultas = {}
        for ident in ids:
            try:
                consulta = consultar_subhorario(ident)
            except Exception as e:
                consulta = {
                    "url": URL_GRAFICO.format(idestacao=ident),
                    "http_status": None,
                    "pontos": [],
                    "quantidade_pontos": 0,
                    "erro": str(e)[:500],
                }
            consultas[str(ident)] = consulta
            saida["consultas"].append({
                "idestacao": ident,
                "url": consulta.get("url"),
                "http_status": consulta.get("http_status"),
                "content_type": consulta.get("content_type"),
                "quantidade_pontos": consulta.get("quantidade_pontos"),
                "erro": consulta.get("erro"),
            })

        resultados = []
        for ep in episodios:
            est = ep.get("estacao") or {}
            consulta = consultas.get(str(est.get("id"))) or {"pontos": []}
            resultados.append(auditar_episodio(ep, consulta))

        saida["resultados"] = resultados
        positivos = [x for x in resultados if x.get("evidencia_temporal_positiva")]
        saida["confirmacoes_nesta_execucao"] = len(positivos)

        antigos = carregar_historico()
        por_chave = {chave_prova(x): x for x in antigos if chave_prova(x) != "|"}
        for x in positivos:
            por_chave[chave_prova(x)] = {
                **x,
                "confirmado_em": agora().isoformat(),
                "fonte": "CEMADEN_grafico_pcds_publico",
            }

        historico = sorted(
            por_chave.values(),
            key=lambda x: str(x.get("rotulo_horario_utc") or ""),
        )
        confirmacoes = len(historico)

        # Gate temporal global exige pelo menos duas horas chuvosas distintas
        # confirmadas pela soma sub-horária oficial. Isso NÃO libera Z-R.
        gate_temporal = confirmacoes >= MIN_CONFIRMACOES_PARA_GATE_GLOBAL

        saida["confirmacoes_historicas_distintas"] = confirmacoes
        saida["borda_horaria_retrospectiva_empiricamente_confirmada"] = gate_temporal
        saida["pareamento_temporal_validado"] = gate_temporal
        saida["status"] = (
            "sem_confirmacao_subhoraria_nesta_execucao"
            if not positivos
            else (
                "borda_temporal_cemaden_confirmada"
                if gate_temporal
                else "evidencia_subhoraria_positiva_insuficiente_para_gate"
            )
        )

        historico_doc = {
            "monitor": "Monitor Guaxanduva",
            "versao": "#170-H2",
            "tipo": "historico_provas_subhorarias_cemaden",
            "natureza": "DIAGNOSTICO_TEMPORAL",
            "atualizado_em": agora().isoformat(),
            "quantidade_confirmacoes_distintas": confirmacoes,
            "minimo_confirmacoes_gate": MIN_CONFIRMACOES_PARA_GATE_GLOBAL,
            "borda_horaria_retrospectiva_empiricamente_confirmada": gate_temporal,
            "pareamento_temporal_validado": gate_temporal,
            "elegivel_calibracao_zr": False,
            "zr_validada": False,
            "conversao_dbz_mm_h_liberada": False,
            "observacao": (
                "O gate aqui e exclusivamente temporal para CEMADEN. "
                "Z-R permanece bloqueada ate validacao espacial e calibracao propria."
            ),
            "registros": historico,
        }
        salvar_json(ARQUIVO_HISTORICO, historico_doc)

    except Exception as e:
        saida["status"] = "falha_h2_fail_closed"
        saida["erro"] = str(e)[:500]

    salvar_json(ARQUIVO_SAIDA, saida)

    print(json.dumps({
        "arquivo": ARQUIVO_SAIDA,
        "versao": saida.get("versao"),
        "status": saida.get("status"),
        "confirmacoes_nesta_execucao": saida.get("confirmacoes_nesta_execucao"),
        "confirmacoes_historicas_distintas": saida.get("confirmacoes_historicas_distintas"),
        "pareamento_temporal_validado": saida.get("pareamento_temporal_validado"),
        "zr_validada": saida.get("zr_validada"),
        "conversao_dbz_mm_h_liberada": saida.get("conversao_dbz_mm_h_liberada"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
