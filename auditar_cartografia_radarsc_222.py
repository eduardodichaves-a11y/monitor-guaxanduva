#!/usr/bin/env python3
"""#222: inspeciona referências públicas de cartografia do RadarSC; somente leitura."""
import json, re, hashlib, argparse
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests

BASE='https://sifap.defesacivil.sc.gov.br/radarsc/'
PATTERNS={
 'projecao':r'(?i)(?:EPSG\s*[:/]\s*\d+|projection|proj4|srsName|crs)',
 'extensao':r'(?i)(?:extent|bounds|bbox|imageExtent|imageStatic|ImageStatic)',
 'radar':r'(?i)(?:getImagem|getUltimasImagens|cappi_top|COMP)',
 'coordenadas':r'-?\d{2}\.\d{4,}',
}
def main():
 p=argparse.ArgumentParser();p.add_argument('--saida',default='auditoria_cartografia_radarsc_222.json');a=p.parse_args()
 s=requests.Session();s.headers['User-Agent']='MonitorGuaxanduva-AuditoriaCartografica/222'
 report={'versao':'#222','natureza':'SONDAGEM_PUBLICA_SOMENTE_LEITURA','base':BASE,'arquivos':[],'limite':'Não confirma georreferenciamento do PNG sem metadados inequívocos; não altera sistema operacional.'}
 queue=[BASE];seen=set()
 while queue and len(seen)<16:
  url=queue.pop(0)
  if url in seen:continue
  seen.add(url)
  item={'url':url}
  try:
   try:r=s.get(url,timeout=20)
   except requests.exceptions.SSLError:
    item['tls']='CERTIFICADO_NAO_VALIDADO';r=s.get(url,timeout=20,verify=False)
   else:item['tls']='CERTIFICADO_VALIDADO'
   item['http']=r.status_code;item['tipo']=r.headers.get('content-type','');item['bytes']=len(r.content)
   if r.status_code!=200 or len(r.content)>2_000_000:report['arquivos'].append(item);continue
   txt=r.text;item['sha256']=hashlib.sha256(r.content).hexdigest()
   lines=txt.splitlines();hits=[]
   for n,line in enumerate(lines,1):
    kinds=[k for k,pat in PATTERNS.items() if re.search(pat,line)]
    if kinds and len(hits)<80:hits.append({'linha':n,'tipos':kinds,'trecho':line.strip()[:280]})
   item['ocorrencias']=hits
   if len(seen)==1:
    refs=re.findall(r'''(?:src|href)\s*=\s*["']([^"']+\.js(?:\?[^"']*)?)["']''',txt,re.I)
    for ref in refs:
     u=urljoin(url,ref)
     if urlparse(u).netloc==urlparse(BASE).netloc and u not in seen and u not in queue:queue.append(u)
   report['arquivos'].append(item)
  except Exception as e:item['erro']=type(e).__name__+': '+str(e)[:200];report['arquivos'].append(item)
 Path(a.saida).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('Auditoria #222:',len(report['arquivos']),'recursos; evidências:',sum(len(x.get('ocorrencias',[])) for x in report['arquivos']))
if __name__=='__main__':main()
