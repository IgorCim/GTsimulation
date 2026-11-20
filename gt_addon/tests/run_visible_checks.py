"""Visible bounded test run and local HTML evidence; never imports or changes GT."""
from pathlib import Path
from datetime import datetime,timezone
import argparse
import csv
import hashlib
import html
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]


def junit_summary(path):
    suites=list(ET.parse(path).getroot().iter('testsuite'))
    counts={k:sum(int(s.attrib.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    counts['status']='PASS' if counts['tests']>0 and counts['failures']==counts['errors']==counts['skipped']==0 else 'FAIL'
    return counts


def overall(state):
    if state.get('runner_error'):return 'FAIL'
    statuses=[x['status'] for x in state['models'].values()]
    if state.get('unit',{}).get('status') not in ('PASS','NOT_RUN'):return 'FAIL' if state['unit']['status'] in ('FAIL','TIMEOUT','ERROR') else 'RUNNING'
    if any(x in ('FAIL','TIMEOUT','ERROR') for x in statuses):return 'FAIL'
    if all(x=='PASS' for x in statuses) and statuses:return 'PARTIAL' if state['unit']['status']=='NOT_RUN' else 'PASS'
    return 'RUNNING'


def render(state,folder):
    e=lambda x:html.escape(str(x),quote=True)
    cards=[]
    for model,item in state['models'].items():
        status=item['status'];values=item.get('check',{})
        links=''
        if item.get('log'):links+=f'<a href="{e(item["log"])}">Журнал</a> '
        if item.get('report_link'):links+=f'<a href="{e(item["report_link"])}">Исходный отчёт</a> '
        if item.get('csv'):links+=f'<a href="{e(item["csv"])}">CSV со всеми строками</a>'
        rows=''.join(f'<tr><td>{e(k)}</td><td>{e(v)}</td></tr>' for k,v in values.get('first_expected',{}).items())
        err=''.join(f'<tr><td>{e(k)}</td><td>{e(v)}</td></tr>' for k,v in values.get('max_absolute_error_by_component',{}).items())
        preview=item.get('preview',{})
        actual='<tr>'+''.join('<th>'+e(k)+'</th>' for k in preview.get('headers',[]))+'</tr>'
        actual+=''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in preview.get('rows',[]))
        cards.append(f'<section><h2>{e(model)} — <span class="{e(status)}">{e(status)}</span></h2><p>{e(item.get("phase",""))} · {e(item.get("seconds",0))} с</p><p>{e(item.get("error",""))}</p><p>Строк: {e(values.get("rows","—"))}; UTC: {e(values.get("start","—"))} … {e(values.get("end_exclusive","—"))} (конец исключён).</p><p>{links}</p><h3>Первая строка: ожидаемые входы из источника</h3><table>{rows}</table><h3>Первые пять фактически сохранённых строк</h3><div style="overflow:auto"><table>{actual}</table></div><h3>Максимальные расхождения со всеми сохранёнными строками</h3><table>{err}</table></section>')
    status=overall(state)
    content=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Проверка аддона GT</title>
<style>body{{font:16px system-ui;margin:28px auto;padding:0 20px;max-width:1000px;background:#f6f8fa;color:#16202a}}section{{background:white;padding:18px;margin:18px 0;border:1px solid #ccd3dc;border-radius:10px}}table{{border-collapse:collapse}}td{{padding:6px 12px;border-bottom:1px solid #ddd}}.PASS{{color:#08733d}}.FAIL,.TIMEOUT,.ERROR{{color:#b71922}}.RUNNING,.PARTIAL{{color:#925900}}a{{color:#145cc5}}p{{overflow-wrap:anywhere}}</style>
<h1>Проверка самостоятельного аддона</h1><h2>Итог: <span class="{e(status)}">{e(status)}</span></h2>
<p>Режим: свежая сеть. Проверяются только источники, файлы и подготовка входов. Физические модели GT не запускаются.</p>
<p>Автотесты: {e(state['unit'].get('status'))}; {e(state['unit'].get('tests','—'))} случаев. <a href="unit.log">Журнал тестов</a>. <a href="report.json">Общий JSON</a>.</p>
<p>Лимит на один источник: {e(state['timeout'])} с. TIMEOUT означает отсутствие подтверждённого результата в этот срок. Это не доказательство ошибки расчёта и не успешная загрузка.</p>
<p>Страница обновляется по F5. Все выбранные источники должны иметь PASS; NOT_RUN не заменяет пройденные автотесты. Прохождение не доказывает отсутствие любых ошибок во всех условиях.</p>
{''.join(cards)}</html>'''
    state['status']=status
    (folder/'report.json').write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding='utf-8')
    (folder/'report.html').write_text(content,encoding='utf-8')


def stop_tree(proc):
    if proc.poll() is not None:return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=20)
    else:os.killpg(proc.pid,signal.SIGKILL)
    if proc.poll() is None:proc.kill()
    proc.wait(timeout=20)


def bounded(command,log_path,timeout,tick):
    """Enforce wall time; also stop this process tree on interruption."""
    kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NO_WINDOW}
    started=time.monotonic()
    with log_path.open('w',encoding='utf-8') as log:
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1'},**kwargs)
        try:
            while proc.poll() is None:
                elapsed=time.monotonic()-started
                tick(round(elapsed,1))
                if elapsed>=timeout:
                    stop_tree(proc)
                    return {'status':'TIMEOUT','seconds':round(time.monotonic()-started,1),'returncode':proc.returncode}
                try:proc.wait(timeout=min(5,max(.01,timeout-elapsed)))
                except subprocess.TimeoutExpired:pass
        except BaseException:
            stop_tree(proc);raise
    return {'status':'PASS' if proc.returncode==0 else 'FAIL','seconds':round(time.monotonic()-started,1),'returncode':proc.returncode}


def add_preview(item,model,folder):
    import numpy as np
    bundle=item['check']['bundle']
    data=np.load(bundle['input_file'],allow_pickle=False)
    if model=='89':headers=['UTC','T89_activity_bin'];values=data['T89_input'][:,None]
    elif model=='96':headers=['UTC','Pdyn_nPa','Dst_nT','By_GSM_nT','Bz_GSM_nT'];values=data['T96_input']
    elif model=='15B':headers=['UTC','Pdyn_nPa','By_GSW_nT','Bz_GSW_nT','B_index','imf_flag','sw_flag'];values=np.column_stack([data['T15B_input'],data['imf_flag'],data['sw_flag']])
    else:headers=['UTC','previous_day_F107_sfu','center81_F107_sfu','daily_Ap','ap_now','ap_minus3h','ap_minus6h','ap_minus9h','ap_mean12_33h','ap_mean36_57h'];values=np.column_stack([data['f107'],data['f107a'],data['ap']])
    name=model+'.csv'
    with (folder/name).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(headers)
        for date,row in zip(data['date'],values):writer.writerow([str(date)+'Z',*row.tolist()])
    item['csv']=name
    item['preview']={'headers':headers,'rows':[[str(date)+'Z',*row.tolist()] for date,row in zip(data['date'][:5],values[:5])]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout',type=int,default=180,help='Wall seconds per source')
    parser.add_argument('--models',nargs='+',choices=['89','96','15B','nrlmsis'],default=['89','96','15B','nrlmsis'])
    parser.add_argument('--skip-unit',action='store_true',help='Explicit focused network check; not a complete acceptance')
    args=parser.parse_args()
    if not 5<=args.timeout<=900:parser.error('--timeout must be 5..900 seconds')
    (ROOT/'results').mkdir(exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix='visible-',dir=ROOT/'results'))
    state={'status':'RUNNING','mode':'live network','created_UTC':datetime.now(timezone.utc).isoformat(),'timeout':args.timeout,
           'fetcher_sha256':hashlib.sha256((ROOT/'fetcher.py').read_bytes()).hexdigest(),
           'unit':{'status':'NOT_RUN' if args.skip_unit else 'RUNNING'},
           'models':{m:{'status':'PENDING','phase':'Ожидание'} for m in dict.fromkeys(args.models)}}
    render(state,folder)
    print('HTML-ОТЧЁТ: '+str(folder/'report.html'),flush=True)
    try:
        if not args.skip_unit:
            print('АВТОТЕСТЫ: подробные имена пишутся в unit.log',flush=True)
            def unit_tick(seconds):
                state['unit']['seconds']=seconds;render(state,folder);print(f'  тесты: {seconds} с',flush=True)
            unit=bounded([sys.executable,'-u','-m','pytest',str(ROOT/'tests'),'-v','-W','error','-p','no:cacheprovider','--junitxml='+str(folder/'tests.xml')],folder/'unit.log',180,unit_tick)
            state['unit']=junit_summary(folder/'tests.xml') if (folder/'tests.xml').is_file() else unit
            if unit['status']!='PASS':state['unit']['status']='FAIL'
            render(state,folder)
            print('АВТОТЕСТЫ: '+state['unit']['status']+'; '+str(state['unit'].get('tests','?')),flush=True)
        for model,item in state['models'].items():
            print(f'ИСТОЧНИК {model}: запуск, лимит {args.timeout} с',flush=True)
            item.update(status='RUNNING',phase='Загрузка → SHA256 → независимый пересчёт',log=model+'.log')
            def tick(seconds):
                item['seconds']=seconds;render(state,folder);print(f'  {model}: ожидание {seconds}/{args.timeout} с',flush=True)
            outcome=bounded([sys.executable,'-u',str(ROOT/'tests/check_live.py'),'--models',model],folder/(model+'.log'),args.timeout,tick)
            item.update(outcome)
            text=(folder/(model+'.log')).read_text(encoding='utf-8',errors='replace')
            if outcome['status']=='TIMEOUT':item['error']='Превышен лимит; процесс проверки источника остановлен.'
            else:
                paths=[line[len('Evidence: '):] for line in text.splitlines() if line.startswith('Evidence: ')]
                if paths:
                    path=Path(paths[-1]).resolve()
                    if not path.is_relative_to((ROOT/'results').resolve()):raise ValueError('Unexpected evidence path')
                    report=json.loads(path.read_text(encoding='utf-8'))
                    item['check']=report['models'][model]
                    item['report_link']=Path(os.path.relpath(path,folder)).as_posix()
                    if report.get('mode')!='live network' or item['check'].get('status')!='PASS':item['status']='FAIL'
                    item['error']=item['check'].get('error','')
                    if item['status']=='PASS':add_preview(item,model,folder)
                else:item.update(status='ERROR',error='Нет завершённого отчёта; см. журнал.')
            item['phase']='Завершено';render(state,folder)
            print(f"ИСТОЧНИК {model}: {item['status']}; {item.get('error','')}",flush=True)
    except BaseException as exc:
        state['runner_error']=str(exc)
        for item in state['models'].values():
            if item['status']=='RUNNING':item.update(status='ERROR',error=str(exc))
        render(state,folder);raise
    print('ИТОГ: '+state['status']+'; HTML: '+str(folder/'report.html'),flush=True)
    return 0 if state['status']=='PASS' and state['unit']['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
