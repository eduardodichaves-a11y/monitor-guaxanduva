import io  
import json  
import math  
import hashlib  
from collections import Counter, deque  
from datetime import datetime  
from zoneinfo import ZoneInfo  
  
import requests  
import urllib3  
from PIL import Image  
  
ARQUIVO = "dados.json"  
LAT, LON = -26.27, -48.81  # coordenada pública aproximada do Comasa  
FUSO = ZoneInfo("America/Sao_Paulo")  
UTC = ZoneInfo("UTC")  
  
MARE = "https://ciram.epagri.sc.gov.br/ciram_arquivos/oceano/tabuamare/csv/Tabua_Mare_Joinville.csv"  
RADAR = "https://sifap.defesacivil.sc.gov.br/radarsc/"  
LISTA = RADAR + "rest/radar/getUltimasImagens"  
IMAGEM = RADAR + "rest/radar/getImagem"  
LEGENDA = RADAR + "img/legenda.png"  
EXT = [-58.0651279, -33.8163446, -46.4999942, -24.7653703]  
CINZA = (200, 200, 200)  
  
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  
  
  
def agora():  
    return datetime.now(FUSO)  
  
  
def get(url, params=None, radar=False):  
    r = requests.get(  
        url,  
        params=params,  
        timeout=30,  
        headers={"User-Agent": "Monitor-Guaxanduva/1.0"},  
        verify=False if radar else True,  
    )  
    r.raise_for_status()  
    return r  
  
  
def hav(lat1, lon1, lat2, lon2):  
    R = 6371.0088  
    p1, p2 = math.radians(lat1), math.radians(lat2)  
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)  
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2  
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))  
  
  
def rumo(lat1, lon1, lat2, lon2):  
    p1, p2 = math.radians(lat1), math.radians(lat2)  
    dl = math.radians(lon2-lon1)  
    y = math.sin(dl)*math.cos(p2)  
    x = math.cos(p1)*math.sin(p2) - math.sin(p1)*math.cos(p2)*math.cos(dl)  
    return (math.degrees(math.atan2(y, x)) + 360) % 360  
  
  
def cardinal(g):  
    if g is None:  
        return None  
    return ["N", "NE", "L", "SE", "S", "SO", "O", "NO"][int((g+22.5)//45) % 8]  
  
  
def difang(a, b):  
    return abs((a-b+180) % 360 - 180)  
  
  
def px2geo(x, y, w, h):  
    oeste, sul, leste, norte = EXT  
    lat = norte - y/(h-1)*(norte-sul)  
    lon = oeste + x/(w-1)*(leste-oeste)  
    return lat, lon  
  
  
def geo2px(lon, lat, w, h):  
    oeste, sul, leste, norte = EXT  
    x = round((lon-oeste)/(leste-oeste)*(w-1))  
    y = round((norte-lat)/(norte-sul)*(h-1))  
    return max(0, min(w-1, x)), max(0, min(h-1, y))  
  
  
def buscar_previsao():  
    try:  
        p = {  
            "latitude": LAT,  
            "longitude": LON,  
            "current": "precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m",  
            "hourly": "precipitation_probability,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m",  
            "daily": "precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max",  
            "forecast_days": 7,  
            "timezone": "America/Sao_Paulo",  
        }  
        d = get("https://api.open-meteo.com/v1/forecast", p).json()  
        c, h, dy = d.get("current", {}), d.get("hourly", {}), d.get("daily", {})  
        idx = None  
        for i, t in enumerate(h.get("time", [])):  
            try:  
                if datetime.fromisoformat(t).replace(tzinfo=FUSO) > agora():  
                    idx = i  
                    break  
            except Exception:  
                pass  
  
        def hv(k):  
            a = h.get(k, [])  
            return a[idx] if idx is not None and idx < len(a) else None  
  
        dias = []  
        for i, data in enumerate(dy.get("time", [])):  
            def dv(k):  
                a = dy.get(k, [])  
                return a[i] if i < len(a) else None  
            dias.append({  
                "data": data,  
                "probabilidade_chuva_pct": dv("precipitation_probability_max"),  
                "precipitacao_total_mm": dv("precipitation_sum"),  
                "vento_max_kmh": dv("wind_speed_10m_max"),  
                "rajada_max_kmh": dv("wind_gusts_10m_max"),  
            })  
  
        return {  
            "status": "online",  
            "fonte": "Open-Meteo",  
            "modelo": "Best Match",  
            "atual": {  
                "horario": c.get("time"),  
                "precipitacao_mm": c.get("precipitation"),  
                "vento_kmh": c.get("wind_speed_10m"),  
                "direcao_graus": c.get("wind_direction_10m"),  
                "rajada_kmh": c.get("wind_gusts_10m"),  
            },  
            "proxima_hora": {  
                "horario": hv("time"),  
                "probabilidade_chuva_pct": hv("precipitation_probability"),  
                "precipitacao_mm": hv("precipitation"),  
                "vento_kmh": hv("wind_speed_10m"),  
                "direcao_graus": hv("wind_direction_10m"),  
                "rajada_kmh": hv("wind_gusts_10m"),  
            },  
            "proximos_7_dias": dias,  
        }  
    except Exception as e:  
        return {"status": "indisponivel", "fonte": "Open-Meteo", "erro": str(e)}  
  
  
def buscar_mare():  
    try:  
        r = get(MARE)  
        r.encoding = "ISO-8859-1"  
        a = agora()  
        dh = a.strftime("%d/%m/%Y")  
        eventos = []  
        for ln in r.text.splitlines():  
            p = ln.strip().split(";")  
            if len(p) != 3 or p[0].strip() != dh:  
                continue  
            try:  
                alt = float(p[2].strip().replace(",", "."))  
                datetime.strptime(p[1].strip(), "%H:%M")  
            except Exception:  
                continue  
            eventos.append({"hora": p[1].strip(), "altura_m": alt})  
  
        if not eventos:  
            raise ValueError("Nenhum evento de maré para " + dh)  
  
        eventos.sort(key=lambda x: datetime.strptime(x["hora"], "%H:%M"))  
        am = a.hour*60 + a.minute  
        ant = prox = None  
        for e in eventos:  
            t = datetime.strptime(e["hora"], "%H:%M")  
            m = t.hour*60 + t.minute  
            if m <= am:  
                ant = e  
            elif prox is None:  
                prox = e  
  
        return {  
            "status": "online",  
            "fonte": "EPAGRI/CIRAM",  
            "tipo": "tabua_de_mare_prevista",  
            "local": "Joinville",  
            "data": dh,  
            "eventos": eventos,  
            "anterior": ant,  
            "proximo": prox,  
        }  
    except Exception as e:  
        return {  
            "status": "indisponivel",  
            "fonte": "EPAGRI/CIRAM",  
            "tipo": "tabua_de_mare_prevista",  
            "erro": str(e),  
        }  
  
  
def legenda():  
    try:  
        b = get(LEGENDA, radar=True).content  
        im = Image.open(io.BytesIO(b)).convert("RGBA")  
        best = []  
        for y in range(im.height):  
            seg = []  
            cor = im.getpixel((0, y))  
            ini = 0  
            for x in range(1, im.width):  
                c = im.getpixel((x, y))  
                if c != cor:  
                    if x-ini >= 10 and cor[3] > 0 and cor[:3] not in ((255,255,255),(0,0,0)):  
                        seg.append((ini, x-1, cor))  
                    ini, cor = x, c  
            if im.width-ini >= 10 and cor[3] > 0 and cor[:3] not in ((255,255,255),(0,0,0)):  
                seg.append((ini, im.width-1, cor))  
            if len(seg) > len(best):  
                best = seg  
  
        classes = [  
            {"classe": i+1, "rgb": list(s[2][:3]), "dbz": None}  
            for i, s in enumerate(best[:16])  
        ]  
        return {  
            "status": "online",  
            "fonte": "legenda oficial RadarSC",  
            "sha256": hashlib.sha256(b).hexdigest(),  
            "quantidade_classes": len(classes),  
            "classes": classes,  
            "dbz_numerico": "aguardando_validacao",  
        }  
    except Exception as e:  
        return {"status": "indisponivel", "erro": str(e)}  
  
  
def alpha_idx(tr, i):  
    if tr is None:  
        return 255  
    if isinstance(tr, int):  
        return 0 if i == tr else 255  
    if isinstance(tr, (bytes, bytearray)) and i < len(tr):  
        return int(tr[i])  
    return 255  
  
  
def rgb_idx(pal, i):  
    j = i*3  
    return tuple(pal[j:j+3]) if pal and j+2 < len(pal) else None  
  
  
def diagnostico(im):  
    if im.mode != "P":  
        return {"status": "modo_inesperado", "modo_original": im.mode}  
    pal, tr = im.getpalette(), im.info.get("transparency")  
    cnt = Counter(im.getdata())  
    itens = []  
    vis = trans = cin = cand = 0  
  
    for i, n in sorted(cnt.items()):  
        rgb = rgb_idx(pal, i)  
        al = alpha_idx(tr, i)  
        v = al > 0  
        c = rgb == CINZA  
        cm = v and not c  
        vis += n if v else 0  
        trans += n if not v else 0  
        cin += n if c else 0  
        cand += n if cm else 0  
        itens.append({  
            "indice_p": int(i),  
            "rgb": list(rgb) if rgb else None,  
            "alpha": al,  
            "pixels": n,  
            "visivel": v,  
            "cinza_nao_validado": c,  
            "candidato_meteorologico": cm,  
        })  
  
    return {  
        "status": "online",  
        "modo_original": im.mode,  
        "largura_px": im.width,  
        "altura_px": im.height,  
        "total_pixels": im.width*im.height,  
        "pixels_transparentes": trans,  
        "pixels_visiveis": vis,  
        "pixels_cinza_nao_validado": cin,  
        "pixels_candidatos_meteorologicos": cand,  
        "indices_usados": itens,  
    }  
  
  
def mascara(im):  
    if im.mode != "P":  
        return set(), {}  
    pal, tr = im.getpalette(), im.info.get("transparency")  
    inds = {}  
    for i in set(im.getdata()):  
        rgb = rgb_idx(pal, i)  
        if alpha_idx(tr, i) > 0 and rgb is not None and rgb != CINZA:  
            inds[i] = rgb  
  
    px = im.load()  
    m = {  
        (x, y)  
        for y in range(im.height)  
        for x in range(im.width)  
        if px[x, y] in inds  
    }  
    return m, inds  
  
  
def componentes(m):  
    rest = set(m)  
    out = []  
    viz = ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1))  
    while rest:  
        ini = rest.pop()  
        q = deque([ini])  
        pts = [ini]  
        while q:  
            x, y = q.popleft()  
            for dx, dy in viz:  
                p = (x+dx, y+dy)  
                if p in rest:  
                    rest.remove(p)  
                    q.append(p)  
                    pts.append(p)  
        if len(pts) >= 3:  
            out.append(pts)  
    return sorted(out, key=len, reverse=True)  
  
  
def resumo_comp(pts, im, n):  
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]  
    cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)  
    lat, lon = px2geo(cx, cy, im.width, im.height)  
    dc = hav(LAT, LON, lat, lon)  
    rc = rumo(LAT, LON, lat, lon)  
    pal, pix = im.getpalette(), im.load()  
    cores = Counter()  
    men = None  
  
    for x, y in pts:  
        la, lo = px2geo(x, y, im.width, im.height)  
        d = hav(LAT, LON, la, lo)  
        if men is None or d < men[0]:  
            men = (d, x, y, la, lo)  
        rgb = rgb_idx(pal, pix[x, y])  
        if rgb:  
            cores[rgb] += 1  
  
    d, x, y, la, lo = men  
    rm = rumo(LAT, LON, la, lo)  
    return {  
        "id_quadro": n,  
        "pixels": len(pts),  
        "centroide": {  
            "pixel_x": round(cx,1), "pixel_y": round(cy,1),  
            "latitude": round(lat,5), "longitude": round(lon,5),  
            "distancia_comasa_km": round(dc,2),  
            "direcao_graus": round(rc,1), "direcao_cardinal": cardinal(rc),  
        },  
        "ponto_mais_proximo_comasa": {  
            "pixel_x": x, "pixel_y": y,  
            "latitude": round(la,5), "longitude": round(lo,5),  
            "distancia_comasa_km": round(d,2),  
            "direcao_graus": round(rm,1), "direcao_cardinal": cardinal(rm),  
        },  
        "caixa_pixels": {  
            "x_min": min(xs), "x_max": max(xs),  
            "y_min": min(ys), "y_max": max(ys),  
        },  
        "cores": [{"rgb": list(c), "pixels": q} for c, q in cores.most_common()],  
        "dbz": None,  
        "classificacao": "candidato_a_area_de_eco",  
    }  
  
  
def analisar(im):  
    m, inds = mascara(im)  
    xc, yc = geo2px(LON, LAT, im.width, im.height)  
  
    if not m:  
        return {  
            "status": "sem_pixels_candidatos",  
            "pixel_comasa": {"x": xc, "y": yc},  
            "pixels_candidatos": 0,  
            "quantidade_componentes_3px_ou_mais": 0,  
            "maiores_componentes": [],  
            "componentes_mais_proximos_comasa": [],  
        }  
  
    raios = {10:0,25:0,50:0,100:0}  
    eco = None  
    for x, y in m:  
        la, lo = px2geo(x, y, im.width, im.height)  
        d = hav(LAT, LON, la, lo)  
        for r in raios:  
            if d <= r:  
                raios[r] += 1  
        if eco is None or d < eco["_d"]:  
            rg = rumo(LAT, LON, la, lo)  
            eco = {  
                "_d": d, "pixel_x": x, "pixel_y": y,  
                "latitude": round(la,5), "longitude": round(lo,5),  
                "distancia_comasa_km": round(d,2),  
                "direcao_graus": round(rg,1), "direcao_cardinal": cardinal(rg),  
            }  
    eco.pop("_d", None)  
  
    br = componentes(m)  
    cs = [resumo_comp(p, im, i) for i, p in enumerate(br[:40], 1)]  
    prox = sorted(cs, key=lambda c: c["ponto_mais_proximo_comasa"]["distancia_comasa_km"])  
  
    return {  
        "status": "diagnostico_espacial_ativo",  
        "metodo": "componentes_conectados_8_vizinhos",  
        "pixel_comasa": {"x": xc, "y": yc, "latitude_aproximada": LAT, "longitude_aproximada": LON},  
        "pixels_candidatos": len(m),  
        "indices_candidatos": [{"indice_p": i, "rgb": list(rgb)} for i, rgb in sorted(inds.items())],  
        "eco_mais_proximo": eco,  
        "pixels_por_raio": {  
            "ate_10_km": raios[10], "ate_25_km": raios[25],  
            "ate_50_km": raios[50], "ate_100_km": raios[100],  
        },  
        "quantidade_componentes_3px_ou_mais": len(br),  
        "maiores_componentes": cs,  
        "componentes_mais_proximos_comasa": prox[:10],  
    }  
  
  
def distc(a, b):  
    A, B = a["centroide"], b["centroide"]  
    return hav(A["latitude"], A["longitude"], B["latitude"], B["longitude"])  
  
  
def overlap(a, b):  
    A, B = a["caixa_pixels"], b["caixa_pixels"]  
    x1, y1 = max(A["x_min"], B["x_min"]), max(A["y_min"], B["y_min"])  
    x2, y2 = min(A["x_max"], B["x_max"]), min(A["y_max"], B["y_max"])  
    if x2 < x1 or y2 < y1:  
        return 0  
    inter = (x2-x1+1)*(y2-y1+1)  
    aa = (A["x_max"]-A["x_min"]+1)*(A["y_max"]-A["y_min"]+1)  
    bb = (B["x_max"]-B["x_min"]+1)*(B["y_max"]-B["y_min"]+1)  
    return inter/min(aa,bb) if min(aa,bb) > 0 else 0  
  
  
def pontuar(a, b, minu):  
    if minu <= 0:  
        return None  
    d = distc(a, b)  
    v = d/(minu/60)  
    if v > 150 or d > 25:  
        return None  
    tam = min(max(1,a["pixels"]), max(1,b["pixels"])) / max(max(1,a["pixels"]), max(1,b["pixels"]))  
    ov = overlap(a, b)  
    if tam < .15 and ov == 0:  
        return None  
    sc = max(0,1-d/25)*.55 + tam*.25 + min(1,ov)*.20  
    return {"score": sc, "distancia_km": d, "velocidade_kmh": v, "razao_tamanho": tam, "sobreposicao_caixas": ov}  
  
  
def casar(qa, qb):  
    A = qa.get("analise_espacial", {}).get("maiores_componentes", [])  
    B = qb.get("analise_espacial", {}).get("maiores_componentes", [])  
    if not A or not B:  
        return []  
  
    ta = datetime.fromisoformat(qa["horario_utc"])  
    tb = datetime.fromisoformat(qb["horario_utc"])  
    mins = (tb-ta).total_seconds()/60  
    cand = []  
  
    for a in A:  
        for b in B:  
            p = pontuar(a, b, mins)  
            if p:  
                cand.append({"a": a, "b": b, **p})  
  
    cand.sort(key=lambda x: x["score"], reverse=True)  
    ua, ub, out = set(), set(), []  
  
    for c in cand:  
        ia, ib = c["a"]["id_quadro"], c["b"]["id_quadro"]  
        if ia in ua or ib in ub or c["score"] < .38:  
            continue  
        ua.add(ia); ub.add(ib)  
        ca, cb = c["a"]["centroide"], c["b"]["centroide"]  
        dm = rumo(ca["latitude"], ca["longitude"], cb["latitude"], cb["longitude"])  
        va, vb = ca["distancia_comasa_km"], cb["distancia_comasa_km"]  
        dv = vb-va  
        tend = "aproximando" if dv < -1 else "afastando" if dv > 1 else "estavel"  
  
        out.append({  
            "componente_anterior": ia,  
            "componente_atual": ib,  
            "score": round(c["score"],3),  
            "intervalo_min": round(mins,1),  
            "deslocamento_centroide_km": round(c["distancia_km"],2),  
            "velocidade_estimada_kmh": round(c["velocidade_kmh"],1),  
            "direcao_movimento_graus": round(dm,1),  
            "direcao_movimento_cardinal": cardinal(dm),  
            "razao_tamanho": round(c["razao_tamanho"],3),  
            "sobreposicao_caixas": round(c["sobreposicao_caixas"],3),  
            "distancia_comasa_anterior_km": va,  
            "distancia_comasa_atual_km": vb,  
            "variacao_distancia_comasa_km": round(dv,2),  
            "tendencia_relativa_comasa": tend,  
            "centroide_anterior": ca,  
            "centroide_atual": cb,  
        })  
    return out  
  
  
def rastrear(qs):  
    if len(qs) < 2:  
        return {"status": "dados_insuficientes", "pares_quadros": [], "trilhas": []}  
  
    blocos = []  
    for i in range(1, len(qs)):  
        ps = casar(qs[i-1], qs[i])  
        blocos.append({  
            "de": qs[i-1]["horario_local"],  
            "para": qs[i]["horario_local"],  
            "correspondencias": ps,  
            "quantidade": len(ps),  
        })  
  
    trilhas, mapa, nid = [], {}, 1  
    for i, bl in enumerate(blocos, 1):  
        for p in bl["correspondencias"]:  
            ka = (i-1, p["componente_anterior"])  
            kb = (i, p["componente_atual"])  
            t = mapa.get(ka)  
            if t is None:  
                t = {"id_trilha": nid, "passos": []}  
                nid += 1  
                trilhas.append(t)  
            t["passos"].append({"de": bl["de"], "para": bl["para"], **p})  
            mapa[ka] = t  
            mapa[kb] = t  
  
    rs = []  
    for t in trilhas:  
        ps = t["passos"]  
        if not ps:  
            continue  
        apr = sum(p["tendencia_relativa_comasa"] == "aproximando" for p in ps)  
        afa = sum(p["tendencia_relativa_comasa"] == "afastando" for p in ps)  
        ten = "aproximando" if apr > afa else "afastando" if afa > apr else "indeterminada"  
        rs.append({  
            "id_trilha": t["id_trilha"],  
            "transicoes": len(ps),  
            "elegivel_para_analise": len(ps) >= 2,  
            "score_medio": round(sum(p["score"] for p in ps)/len(ps),3),  
            "velocidade_media_kmh": round(sum(p["velocidade_estimada_kmh"] for p in ps)/len(ps),1),  
            "tendencia_relativa_comasa": ten,  
            "passos_aproximando": apr,  
            "passos_afastando": afa,  
            "passos_estaveis": len(ps)-apr-afa,  
            "ultima_distancia_comasa_km": ps[-1]["distancia_comasa_atual_km"],  
            "ultima_direcao_movimento": ps[-1]["direcao_movimento_cardinal"],  
            "passos": ps,  
        })  
  
    rs.sort(key=lambda t: (t["elegivel_para_analise"], t["transicoes"], t["score_medio"]), reverse=True)  
    el = [t for t in rs if t["elegivel_para_analise"]]  
    ap = [t for t in el if t["tendencia_relativa_comasa"] == "aproximando"]  
    ap.sort(key=lambda t: (t["ultima_distancia_comasa_km"], -t["score_medio"]))  
    principal = ap[0] if ap else (el[0] if el else None)  
  
    return {  
        "status": "rastreamento_geometrico_experimental",  
        "criterios": {  
            "distancia_max_centroide_km": 25,  
            "velocidade_max_kmh": 150,  
            "score_minimo": .38,  
            "minimo_transicoes_trilha": 2,  
        },  
        "pares_quadros": blocos,  
        "quantidade_trilhas": len(rs),  
        "quantidade_trilhas_elegiveis": len(el),  
        "trilhas": rs[:20],  
        "trilha_principal_diagnostica": principal,  
        "observacao": "Rastreamento geométrico experimental; ETA só é liberado após checagem de interceptação.",  
    }  
  
  
# =========================================================  
# #116 — INTERCEPTAÇÃO DA TRAJETÓRIA + ETA CONSERVADOR  
# =========================================================  
  
def local_xy(lat0, lon0, lat, lon):  
    y = (lat-lat0)*111.32  
    x = (lon-lon0)*111.32*math.cos(math.radians((lat+lat0)/2))  
    return x, y  
  
  
def analisar_interceptacao(trilha, radar_fresco, idade):  
    if not trilha or trilha.get("transicoes", 0) < 2:  
        return {  
            "status": "bloqueado",  
            "intercepta_corredor": False,  
            "motivo": "Trilha temporal insuficiente.",  
            "eta": None,  
        }  
  
    ps = trilha["passos"]  
    ult = ps[-1]  
    ca, cb = ult["centroide_anterior"], ult["centroide_atual"]  
  
    ax, ay = local_xy(cb["latitude"], cb["longitude"], ca["latitude"], ca["longitude"])  
    vx, vy = -ax, -ay  
    vnorm = math.hypot(vx, vy)  
  
    tx, ty = local_xy(cb["latitude"], cb["longitude"], LAT, LON)  
    dist = math.hypot(tx, ty)  
  
    if vnorm < 0.5:  
        return {  
            "status": "bloqueado",  
            "intercepta_corredor": False,  
            "motivo": "Deslocamento recente pequeno demais para projetar trajetória.",  
            "eta": None,  
        }  
  
    rumo_mov = rumo(ca["latitude"], ca["longitude"], cb["latitude"], cb["longitude"])  
    rumo_alvo = rumo(cb["latitude"], cb["longitude"], LAT, LON)  
    ang = difang(rumo_mov, rumo_alvo)  
  
    ux, uy = vx/vnorm, vy/vnorm  
    avanc = tx*ux + ty*uy  
    lateral = abs(tx*uy - ty*ux)  
  
    corredor = min(20.0, max(8.0, 8.0 + dist*.08))  
    aponta = avanc > 0 and ang <= 35  
    intercepta = aponta and lateral <= corredor  
  
    velocidades = [  
        p["velocidade_estimada_kmh"]  
        for p in ps[-3:]  
        if 5 <= p["velocidade_estimada_kmh"] <= 120  
    ]  
    vel = sum(velocidades)/len(velocidades) if velocidades else 0  
  
    base = {  
        "status": "diagnostico",  
        "intercepta_corredor": intercepta,  
        "distancia_centroide_comasa_km": round(dist,2),  
        "rumo_movimento_graus": round(rumo_mov,1),  
        "rumo_movimento_cardinal": cardinal(rumo_mov),  
        "rumo_para_comasa_graus": round(rumo_alvo,1),  
        "rumo_para_comasa_cardinal": cardinal(rumo_alvo),  
        "diferenca_angular_graus": round(ang,1),  
        "distancia_lateral_trajetoria_km": round(lateral,2),  
        "corredor_tolerancia_km": round(corredor,2),  
        "projecao_adiante_km": round(avanc,2),  
        "velocidade_recente_media_kmh": round(vel,1),  
        "radar_fresco": radar_fresco,  
        "idade_radar_min": idade,  
    }  
  
    if not radar_fresco:  
        return {**base, "status": "bloqueado", "motivo": f"Radar desatualizado: {idade} min.", "eta": None}  
  
    if trilha.get("score_medio", 0) < .55:  
        return {**base, "status": "bloqueado", "motivo": "Confiança geométrica insuficiente.", "eta": None}  
  
    if trilha.get("tendencia_relativa_comasa") != "aproximando":  
        return {**base, "status": "bloqueado", "motivo": "Trilha não apresenta aproximação persistente.", "eta": None}  
  
    if not aponta:  
        return {**base, "status": "bloqueado", "motivo": "Vetor recente não aponta suficientemente para o Comasa.", "eta": None}  
  
    if not intercepta:  
        return {**base, "status": "bloqueado", "motivo": "Trajetória projetada passa fora do corredor do Comasa.", "eta": None}  
  
    if vel < 5:  
        return {**base, "status": "bloqueado", "motivo": "Velocidade insuficiente para ETA confiável.", "eta": None}  
  
    minutos = (avanc/vel)*60  
    if minutos < 0 or minutos > 180:  
        return {**base, "status": "bloqueado", "motivo": "ETA projetado fora da janela operacional de 0–180 min.", "eta": None}  
  
    ini = max(0, round(minutos*.70))  
    fim = round(minutos*1.30)  
  
    if trilha["transicoes"] >= 4 and trilha["score_medio"] >= .70 and ang <= 20 and lateral <= corredor*.5:  
        conf = "alta"  
    elif trilha["transicoes"] >= 3 and trilha["score_medio"] >= .60:  
        conf = "moderada"  
    else:  
        conf = "baixa"  
  
    return {  
        **base,  
        "status": "eta_disponivel_experimental",  
        "motivo": "Trilha persistente, radar fresco e trajetória compatível com o corredor do Comasa.",  
        "eta": {  
            "minutos_central": round(minutos),  
            "janela_minutos": [ini, fim],  
            "confianca": conf,  
            "observacao": "Estimativa geométrica; células podem intensificar, dissipar ou mudar de direção.",  
        },  
    }  
  
  
def baixar(nome):  
    b = get(IMAGEM, {"prod":4, "radar":"COMP", "file":nome}, True).content  
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):  
        raise ValueError("Resposta não é PNG válido.")  
    im = Image.open(io.BytesIO(b))  
    return {  
        "bytes": len(b),  
        "sha256": hashlib.sha256(b).hexdigest(),  
        "largura_px": im.width,  
        "altura_px": im.height,  
        "modo_png_original": im.mode,  
        "diagnostico_paleta_png": diagnostico(im),  
        "analise_espacial": analisar(im),  
    }  
  
  
def buscar_radar():  
    try:  
        leg = legenda()  
        nomes = get(LISTA, {"prod":4, "radar":"COMP", "data":""}, True).json()  
        if not isinstance(nomes, list) or not nomes:  
            raise ValueError("Radar não retornou lista de imagens.")  
  
        nomes = nomes[-7:]  
        qs = []  
  
        for n in nomes:  
            try:  
                u = datetime.strptime(n[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)  
                l = u.astimezone(FUSO)  
                qs.append({  
                    "arquivo": n,  
                    "horario_utc": u.isoformat(),  
                    "horario_local": l.isoformat(),  
                    "download": "ok",  
                    **baixar(n),  
                })  
            except Exception as e:  
                qs.append({"arquivo": n, "download": "erro", "erro": str(e)})  
  
        val = [q for q in qs if q.get("download") == "ok"]  
        if not val:  
            raise ValueError("Nenhum PNG válido.")  
  
        ult = val[-1]  
        idade = max(0, round((datetime.now(UTC)-datetime.fromisoformat(ult["horario_utc"])).total_seconds()/60, 1))  
        fresco = idade <= 30  
  
        serie = []  
        for q in val:  
            a = q["analise_espacial"]  
            serie.append({  
                "horario_local": q["horario_local"],  
                "pixels_candidatos": a.get("pixels_candidatos"),  
                "componentes": a.get("quantidade_componentes_3px_ou_mais"),  
                "eco_mais_proximo": a.get("eco_mais_proximo"),  
                "pixels_por_raio": a.get("pixels_por_raio"),  
            })  
  
        rt = rastrear(val)  
        pr = rt.get("trilha_principal_diagnostica")  
        inter = analisar_interceptacao(pr, fresco, idade)  
  
        mov = {"status": "sem_trilha_elegivel", "validado_para_eta": False}  
        if pr:  
            mov = {  
                "status": "diagnostico_disponivel",  
                "metodo": "rastreamento_de_componentes",  
                "trilha_id": pr["id_trilha"],  
                "transicoes": pr["transicoes"],  
                "score_medio": pr["score_medio"],  
                "tendencia": pr["tendencia_relativa_comasa"],  
                "velocidade_media_kmh": pr["velocidade_media_kmh"],  
                "distancia_atual_comasa_km": pr["ultima_distancia_comasa_km"],  
                "direcao_movimento": pr["ultima_direcao_movimento"],  
                "validado_para_eta": inter["status"] == "eta_disponivel_experimental",  
            }  
  
        eta = {  
            "status": "bloqueado",  
            "janela_chegada": None,  
            "motivo": inter.get("motivo"),  
        }  
  
        if inter.get("eta"):  
            e = inter["eta"]  
            eta = {  
                "status": "experimental_disponivel",  
                "janela_chegada_minutos": e["janela_minutos"],  
                "estimativa_central_minutos": e["minutos_central"],  
                "confianca": e["confianca"],  
                "motivo": inter["motivo"],  
                "observacao": e["observacao"],  
            }  
  
        return {  
            "status": "online" if fresco and len(val) == len(nomes) else "parcial",  
            "fonte": "Defesa Civil de Santa Catarina - RadarSC",  
            "radar": "COMP",  
            "produto": "C-MAX",  
            "produto_codigo": 4,  
            "extent": EXT,  
            "quantidade_quadros": len(nomes),  
            "quadros_png_validos": len(val),  
            "todos_png_validos": len(val) == len(nomes),  
            "dimensoes_consistentes": len({(q["largura_px"], q["altura_px"]) for q in val}) == 1,  
            "idade_ultimo_quadro_min": idade,  
            "dados_frescos": fresco,  
            "legenda_oficial": leg,  
            "metodo_eco": {  
                "status": "experimental_validacao",  
                "fundo": "alpha_zero_excluido",  
                "cinza_200_200_200": "excluido_ate_validacao",  
                "demais_pixels_visiveis": "candidatos_meteorologicos",  
                "dbz": "nao_atribuido",  
            },  
            "serie_espacial": serie,  
            "rastreamento_temporal": rt,  
            "interceptacao_trajetoria": inter,  
            "quadros": qs,  
            "ultimo_quadro": ult,  
            "analise_geografica": {  
                "status": "ativa",  
                "referencia": "Comasa - coordenada pública aproximada",  
                "ultimo": ult.get("analise_espacial"),  
            },  
            "analise_movimento": mov,  
            "interpretacao_dbz": "aguardando_validacao_numerica",  
            "eta": eta,  
        }  
  
    except Exception as e:  
        return {  
            "status": "indisponivel",  
            "fonte": "Defesa Civil de Santa Catarina - RadarSC",  
            "radar": "COMP",  
            "produto": "C-MAX",  
            "produto_codigo": 4,  
            "dados_frescos": False,  
            "erro": str(e),  
        }  
  
  
def main():  
    dados = {  
        "monitor": "Monitor Guaxanduva",  
        "local": "Comasa - Joinville/SC",  
        "gerado_em": agora().isoformat(),  
        "chuva": {  
            "status": "aguardando_integracao",  
            "fonte": "CEMADEN",  
            "leitura_mm": None,  
            "acumulado_1h_mm": None,  
            "acumulado_24h_mm": None,  
        },  
        "mare": buscar_mare(),  
        "rio": {  
            "nome": "Rio Guaxanduva",  
            "status": "sem_sensor_publico_confirmado",  
            "nivel_m": None,  
        },  
        "previsao": buscar_previsao(),  
        "radar": buscar_radar(),  
        "granizo": {  
            "status": "sem_alerta_integrado",  
            "fonte": "Defesa Civil - integração futura",  
        },  
        "emergencia": {  
            "defesa_civil": "199",  
            "bombeiros": "193",  
        },  
    }  
  
    with open(ARQUIVO, "w", encoding="utf-8") as f:  
        json.dump(dados, f, ensure_ascii=False, indent=2)  
  
    print("dados.json criado com sucesso")  
    print(json.dumps(dados["radar"], ensure_ascii=False, indent=2))  
  
  
if __name__ == "__main__":  
    main()  
