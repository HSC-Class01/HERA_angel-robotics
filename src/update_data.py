import io,json,os,zipfile
from pathlib import Path
from datetime import datetime,timezone
import requests,pandas as pd
ROOT=Path(__file__).resolve().parents[1];RAW=ROOT/'data/raw';PROC=ROOT/'data/processed';DASH=ROOT/'dashboard';API='https://opendart.fss.or.kr/api'
REPORTS={'11011':('annual','사업보고서'),'11012':('half_year','반기보고서'),'11013':('quarterly','1분기보고서'),'11014':('quarterly','3분기보고서')}
def api(ep,p):
 r=requests.get(API+'/'+ep+'.json',params=p,timeout=60);r.raise_for_status();d=r.json()
 if d.get('status') not in ('000','013'):raise RuntimeError(ep+': '+str(d.get('message')))
 return d
def code_for(key):
 r=requests.get(API+'/corpCode.xml',params={'crtfc_key':key},timeout=90);r.raise_for_status()
 with zipfile.ZipFile(io.BytesIO(r.content)) as z:
  n=next(x for x in z.namelist() if x.lower().endswith('.xml'));df=pd.read_xml(io.BytesIO(z.read(n)),xpath='.//list')
 hit=df[df.corp_name.astype(str).str.contains('엔젤로보틱스',na=False)]
 if hit.empty:raise RuntimeError('corpCode.xml에서 엔젤로보틱스를 찾지 못했습니다')
 return str(hit.iloc[0].corp_code).zfill(8)
def number(v):
 try:return float(str(v).replace(',','')) if str(v).strip() not in ('','-','None','nan') else None
 except:return None
def acct(g,terms):
 s=g[g.account_nm.fillna('').astype(str).str.replace(' ','',regex=False).apply(lambda x:any(t in x for t in terms))]
 s=s[s.amount.notna()]
 return float(s.iloc[0].amount) if not s.empty else None
def main():
 key=os.getenv('DART_API_KEY','').strip()
 if not key:raise RuntimeError('GitHub Secret DART_API_KEY를 설정하세요')
 for p in (RAW,PROC,DASH):p.mkdir(parents=True,exist_ok=True)
 corp=code_for(key);(RAW/'company.json').write_text(json.dumps({'corp_name':'엔젤로보틱스','corp_code':corp},ensure_ascii=False,indent=2),encoding='utf-8')
 today=datetime.now(timezone.utc).strftime('%Y%m%d');filings=[]
 for y in range(2010,datetime.now().year+1):
  params={'crtfc_key':key,'corp_code':corp,'bgn_de':f'{y}0101','end_de':min(f'{y}1231',today),'pblntf_ty':'A','page_no':1,'page_count':100}
  d=api('list',params);filings+=d.get('list') or []
  for pg in range(2,int(d.get('total_page',1) or 1)+1):
   params['page_no']=pg;d=api('list',params);filings+=d.get('list') or []
 pd.DataFrame(filings).to_csv(RAW/'filings_2010_onward.csv',index=False,encoding='utf-8-sig')
 rows=[];errors=[]
 for y in range(2015,datetime.now().year+1):
  for rc,(cat,label) in REPORTS.items():
   result=None
   for fs in ('CFS','OFS'):
    try:
     d=api('fnlttSinglAcntAll',{'crtfc_key':key,'corp_code':corp,'bsns_year':str(y),'reprt_code':rc,'fs_div':fs})
     if d.get('list'):result=d;break
    except Exception as e:errors.append({'year':y,'report_code':rc,'error':str(e)})
   if not result:continue
   (RAW/f'financial_{y}_{rc}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
   for a in result['list']:rows.append({'year':y,'report_code':rc,'report_type':label,'category':cat,'fs_div':a.get('fs_div'),'account_nm':a.get('account_nm'),'amount':number(a.get('thstrm_amount')),'thstrm_add_amount':number(a.get('thstrm_add_amount')),'frmtrm_amount':number(a.get('frmtrm_amount')),'rcept_no':a.get('rcept_no')})
 df=pd.DataFrame(rows);df.to_csv(PROC/'financial_data.csv',index=False,encoding='utf-8-sig');metrics=[]
 if not df.empty:
  for (y,rc,cat,fs),g in df.groupby(['year','report_code','category','fs_div']):
   rev=acct(g,['매출액','수익(매출액)','영업수익']);op=acct(g,['영업이익(손실)','영업이익']);net=acct(g,['당기순이익(손실)','분기순이익(손실)','반기순이익(손실)','당기순이익']);assets=acct(g,['자산총계']);debt=acct(g,['부채총계']);equity=acct(g,['자본총계']);ca=acct(g,['유동자산']);cl=acct(g,['유동부채']);cfo=acct(g,['영업활동현금흐름','영업활동으로인한현금흐름']);capex=acct(g,['유형자산의취득','유형자산취득'])
   ratio=lambda a,b:a/b*100 if a is not None and b not in (None,0) else None
   metrics.append({'year':int(y),'report_code':rc,'report_type':g.iloc[0].report_type,'category':cat,'fs_div':fs,'revenue':rev,'operating_income':op,'net_income':net,'total_assets':assets,'total_liabilities':debt,'total_equity':equity,'cash_flow_operations':cfo,'free_cash_flow':cfo-abs(capex) if cfo is not None and capex is not None else None,'debt_to_equity_pct':ratio(debt,equity),'current_ratio_pct':ratio(ca,cl),'operating_margin_pct':ratio(op,rev),'net_margin_pct':ratio(net,rev),'roa_pct':ratio(net,assets),'roe_pct':ratio(net,equity)})
 md=pd.DataFrame(metrics);md.to_csv(PROC/'financial_ratios.csv',index=False,encoding='utf-8-sig')
 (RAW/'collection_errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
 peers=[['코스모로보틱스','웨어러블·보행보조 로봇','직접 시장 비교 후보','상장 여부 확인 필요'],['위로보틱스','웨어러블 로봇·보행 보조','직접 시장 비교 후보','상장/공시 범위 확인 필요'],['큐렉소','의료·재활 로봇','의료로봇 인접','코스닥'],['네오펙트','디지털 재활 솔루션','재활시장 인접','상장/공시 범위 확인 필요'],['로보스타','산업용 로봇·자동화','간접 참고기업','코스닥'],['레인보우로보틱스','로봇 플랫폼·휴머노이드','간접 참고기업','코스닥']]
 payload=json.dumps({'metrics':md.astype(object).where(pd.notna(md),None).to_dict('records') if not md.empty else [],'updated':datetime.now(timezone.utc).isoformat(),'peers':peers},ensure_ascii=False,allow_nan=False).replace('</','<\\/')
 template=(DASH/'template.html').read_text(encoding='utf-8');(DASH/'index.html').write_text(template.replace('__DATA__',payload),encoding='utf-8')
 print('Updated; financial rows:',len(df),'filings:',len(filings))
if __name__=='__main__':main()
