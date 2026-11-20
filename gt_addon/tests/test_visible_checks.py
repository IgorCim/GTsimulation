"""Checks of reporting honesty and bounded verification; no source network calls."""
from pathlib import Path
import importlib.util
import sys
import pytest
s=importlib.util.spec_from_file_location('visible',Path(__file__).with_name('run_visible_checks.py'))
v=importlib.util.module_from_spec(s);s.loader.exec_module(v)


def test_status_does_not_hide_failed_or_unfinished_checks():
 state={'unit':{'status':'PASS'},'models':{'89':{'status':'PENDING'}}}
 assert v.overall(state)=='RUNNING'
 state['models']['89']['status']='TIMEOUT';assert v.overall(state)=='FAIL'
 state['models']['89']['status']='PASS';assert v.overall(state)=='PASS'
 state['unit']['status']='NOT_RUN';assert v.overall(state)=='PARTIAL'
 state['runner_error']='interrupted';assert v.overall(state)=='FAIL'


def test_html_escapes_source_error(tmp_path):
 state={'unit':{'status':'PASS','tests':1},'timeout':10,'models':{'89':{'status':'FAIL','error':'<script>alert(1)</script>'}}}
 v.render(state,tmp_path)
 text=(tmp_path/'report.html').read_text(encoding='utf-8')
 assert '<script>' not in text and '&lt;script&gt;' in text
 assert 'FAIL' in text


def test_junit_failure_and_skips_not_passed(tmp_path):
 p=tmp_path/'tests.xml';p.write_text('<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1"/></testsuites>')
 r=v.junit_summary(p);assert r['status']=='FAIL' and r['failures']==1 and r['skipped']==1


def test_timeout_is_bounded_and_log_preserved(tmp_path):
 p=tmp_path/'slow.log'
 r=v.bounded([sys.executable,'-u','-c','import time;print("started",flush=True);time.sleep(60)'],p,1,lambda _:None)
 assert r['status']=='TIMEOUT' and r['seconds']<20
 assert 'started' in p.read_text()


def test_worker_error_is_not_success(tmp_path):
 r=v.bounded([sys.executable,'-c','raise ValueError("injected")'],tmp_path/'error.log',10,lambda _:None)
 assert r['status']=='FAIL' and r['returncode']!=0
