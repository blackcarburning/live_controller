"""Controlled Windows named-pipe checks of extracted transport only.

Never imports the controller, runs mpv, opens serial/MIDI, or reads app settings.
The only native IPC endpoints are randomized pipes created by this process.
"""
from __future__ import annotations
import argparse
import ast
import ctypes
import ctypes.wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import unittest
import uuid

PINNED = []
PIPE_PREFIX = chr(92)*2+'.'+chr(92)+'pipe'+chr(92)

class Overlapped(ctypes.Structure):
    _fields_ = [('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                ('Offset',W.DWORD),('OffsetHigh',W.DWORD),('hEvent',W.HANDLE)]

class Kernel:
    def __init__(self):
        self.k = ctypes.WinDLL('kernel32',use_last_error=True)
        specs = {
            'CreateNamedPipeW':([W.LPCWSTR,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,W.DWORD,ctypes.c_void_p],W.HANDLE),
            'CreateEventW':([ctypes.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR],W.HANDLE),
            'ConnectNamedPipe':([W.HANDLE,ctypes.c_void_p],W.BOOL),
            'DisconnectNamedPipe':([W.HANDLE],W.BOOL),
            'ReadFile':([W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p],W.BOOL),
            'WriteFile':([W.HANDLE,ctypes.c_void_p,W.DWORD,ctypes.POINTER(W.DWORD),ctypes.c_void_p],W.BOOL),
            'WaitForSingleObject':([W.HANDLE,W.DWORD],W.DWORD),
            'GetOverlappedResult':([W.HANDLE,ctypes.c_void_p,ctypes.POINTER(W.DWORD),W.BOOL],W.BOOL),
            'CancelIoEx':([W.HANDLE,ctypes.c_void_p],W.BOOL),
            'CloseHandle':([W.HANDLE],W.BOOL),
        }
        for name,(args,result) in specs.items():
            f=getattr(self.k,name);f.argtypes=args;f.restype=result
        self.pinned_handles=set()

    def operation(self,handle,kind,data=None):
        event=self.k.CreateEventW(None,True,False,None)
        if not event: raise ctypes.WinError(ctypes.get_last_error())
        ov=Overlapped();ov.hEvent=event;amount=W.DWORD(0)
        buffer=None
        if kind=='connect':
            ok=self.k.ConnectNamedPipe(handle,ctypes.byref(ov))
        else:
            buffer=ctypes.create_string_buffer(data if kind=='write' else 65536)
            length=len(data) if kind=='write' else 65536
            f=self.k.WriteFile if kind=='write' else self.k.ReadFile
            ok=f(handle,buffer,length,ctypes.byref(amount),ctypes.byref(ov))
        pending=False
        try:
            if not ok:
                error=ctypes.get_last_error()
                if kind=='connect' and error==535:
                    return b''
                if error!=997: raise ctypes.WinError(error)
                pending=True
                state=self.k.WaitForSingleObject(event,1200)
                if state!=0:
                    self.k.CancelIoEx(handle,ctypes.byref(ov))
                    state=self.k.WaitForSingleObject(event,1200)
                    if state!=0:
                        self.pinned_handles.add(handle)
                        PINNED.append((self,handle,event,ov,buffer))
                        event=None
                        raise TimeoutError('Controlled server cancellation did not complete')
                    pending=False
                    raise TimeoutError('Controlled server operation timed out')
                if not self.k.GetOverlappedResult(handle,ctypes.byref(ov),ctypes.byref(amount),False):
                    pending=False
                    raise ctypes.WinError(ctypes.get_last_error())
                pending=False
            if kind=='read': return buffer.raw[:amount.value]
            if kind=='write' and amount.value!=len(data):
                raise AssertionError('Controlled server short write')
            return b''
        finally:
            if pending:
                self.k.CancelIoEx(handle,ctypes.byref(ov))
                if self.k.WaitForSingleObject(event,1200)!=0:
                    self.pinned_handles.add(handle)
                    PINNED.append((self,handle,event,ov,buffer));event=None
            if event:self.k.CloseHandle(event)

class Peer:
    def __init__(self,reply,hold=0.0):
        self.native=Kernel();self.reply=reply;self.hold=hold
        self.pipe=PIPE_PREFIX+'lc-two-display-offline-'+uuid.uuid4().hex
        self.handle=self.native.k.CreateNamedPipeW(self.pipe,3|0x40000000,0,1,65536,65536,0,None)
        if self.handle in (None,ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        self.errors=[];self.request=None;self.release=threading.Event()
        self.thread=threading.Thread(target=self.run,name='controlled-pipe-peer',daemon=True)
        self.thread.start()

    def run(self):
        try:
            self.native.operation(self.handle,'connect')
            raw=b''
            while bytes((10,)) not in raw:
                raw+=self.native.operation(self.handle,'read')
                if len(raw)>65536:raise AssertionError('Oversized controlled request')
            self.request=json.loads(raw.split(bytes((10,)),1)[0].decode('utf-8'))
            chunks=self.reply(self.request)
            if chunks:
                for chunk in chunks:
                    self.native.operation(self.handle,'write',chunk)
                    time.sleep(0.002)
            if self.hold:time.sleep(self.hold)
            self.release.wait(1.5)  # Do not discard unread pipe buffers before client finishes.
        except Exception:
            self.errors.append(traceback.format_exc())
        finally:
            if self.handle not in self.native.pinned_handles:
                self.native.k.DisconnectNamedPipe(self.handle)
                self.native.k.CloseHandle(self.handle)

    def finish(self,allow_broken=False):
        self.release.set()
        self.thread.join(3)
        if self.thread.is_alive():raise AssertionError('Controlled pipe peer remained running')
        if self.errors and not allow_broken:raise AssertionError('\n'.join(self.errors))
        if PINNED:raise AssertionError('Controlled peer native state not reclaimed')

def wire(value):
    return (json.dumps(value,ensure_ascii=False)+chr(10)).encode('utf-8')

def load_transport(path):
    tree=ast.parse(path.read_bytes())
    selected=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_TwoDisplayPipeIO']
    if len(selected)!=1:raise AssertionError('Expected exactly one isolated transport class')
    env=dict(ctypes=ctypes,threading=threading,time=time,os=os,uuid=uuid,json=json)
    exec(compile(ast.Module(body=selected,type_ignores=[]),'<extracted controlled Windows IPC>','exec'),env)
    return env['_TwoDisplayPipeIO']

class NativeTransportTests(unittest.TestCase):
    transport=None
    def tearDown(self):
        deadline=time.monotonic()+1.5
        while self.transport._pending and time.monotonic()<deadline:time.sleep(0.005)
        self.assertEqual(len(self.transport._pending),0,'Deferred cancellation state was not reclaimed')

    def request(self,peer,**kwargs):
        start=time.monotonic()
        result=self.transport.request(peer.pipe,['get_property','time-pos'],timeout=0.5,**kwargs)
        self.assertLess(time.monotonic()-start,1.1)
        return result

    def test_native_success_and_request_id(self):
        peer=Peer(lambda r:[wire({'request_id':r['request_id'],'error':'success','data':12.5})])
        try:
            result=self.request(peer)
            self.assertTrue(result['ok'],result);self.assertEqual(result['data'],12.5)
        finally:peer.finish()

    def test_native_fragmented_unicode_events_and_wrong_reply(self):
        message='screen '+chr(233)+' '+''.join(map(chr,(26085,26412,35486)))
        def reply(r):
            b=wire({'event':'property-change','data':'ignored'})+wire({'request_id':r['request_id']+1,'error':'success','data':'wrong'})
            b+=wire({'request_id':r['request_id'],'error':'success','data':message})
            return [b[:9],b[9:43],b[43:-5],b[-5:]]
        peer=Peer(reply)
        try:
            result=self.request(peer);self.assertTrue(result['ok'],result);self.assertEqual(result['data'],message)
        finally:peer.finish()

    def test_native_large_reply_multiple_reads(self):
        value='frame-'*7000
        def reply(r):
            b=wire({'request_id':r['request_id'],'error':'success','data':value})
            return [b[i:i+3500] for i in range(0,len(b),3500)]
        peer=Peer(reply)
        try:
            result=self.request(peer);self.assertTrue(result['ok'],result);self.assertEqual(result['data'],value)
        finally:peer.finish()

    def test_native_rejected_command(self):
        peer=Peer(lambda r:[wire({'request_id':r['request_id'],'error':'invalid parameter','data':None})])
        try:self.assertFalse(self.request(peer)['ok'])
        finally:peer.finish()

    def test_native_read_deadline_and_cleanup(self):
        peer=Peer(lambda r:[],hold=0.15)
        try:
            start=time.monotonic();result=self.transport.request(peer.pipe,['get_property','time-pos'],timeout=0.04)
            self.assertFalse(result['ok']);self.assertIn('deadline',result['error'].lower())
            self.assertLess(time.monotonic()-start,0.6)
        finally:peer.finish()

    def test_native_read_cancellation_and_cleanup(self):
        peer=Peer(lambda r:[],hold=0.15);cancel=threading.Event()
        timer=threading.Timer(0.025,cancel.set);timer.daemon=True;timer.start()
        try:
            start=time.monotonic();result=self.transport.request(peer.pipe,['get_property','time-pos'],cancel=cancel,timeout=0.5)
            self.assertFalse(result['ok']);self.assertIn('cancel',result['error'].lower())
            self.assertLess(time.monotonic()-start,0.6)
        finally:timer.cancel();peer.finish()

    def test_native_missing_endpoint_deadline(self):
        name=PIPE_PREFIX+'lc-two-display-offline-missing-'+uuid.uuid4().hex
        start=time.monotonic();result=self.transport.request(name,['get_property','time-pos'],timeout=0.03)
        self.assertFalse(result['ok']);self.assertLess(time.monotonic()-start,0.6)

    def test_precancel_does_not_open_native(self):
        cancel=threading.Event();cancel.set()
        original=self.transport._kernel
        self.transport._kernel=staticmethod(lambda:(_ for _ in ()).throw(AssertionError('Precancel opened native API')))
        try:
            result=self.transport.request(PIPE_PREFIX+'lc-two-display-offline-unused',['get_property','time-pos'],cancel=cancel)
            self.assertFalse(result['ok']);self.assertIn('cancel',result['error'].lower())
        finally:self.transport._kernel=staticmethod(original)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--receipt',required=True,type=Path)
    a=p.parse_args()
    receipt={'python':sys.version,'platform':sys.platform,'source_sha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),
             'scope':'AST-extracted transport; own in-process randomized Windows named pipes only; no app, media, MIDI or serial',
             'source_unchanged':False,'qualified':False}
    if os.name!='nt':
        receipt['blocked']='Requires Windows kernel named pipes';print(json.dumps(receipt));return 2
    try:
        NativeTransportTests.transport=load_transport(a.source)
        output=io.StringIO()
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(NativeTransportTests)
        result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
        receipt.update(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),log=output.getvalue())
        receipt['source_unchanged']=receipt['source_sha256']==hashlib.sha256(a.source.read_bytes()).hexdigest()
        receipt['qualified']=result.wasSuccessful() and result.testsRun==8 and not result.skipped and receipt['source_unchanged']
    except Exception:receipt['exception']=traceback.format_exc()
    a.receipt.parent.mkdir(parents=True,exist_ok=True)
    with a.receipt.open('x',encoding='utf-8') as f:json.dump(receipt,f,indent=2)
    print(json.dumps(receipt,indent=2))
    return 0 if receipt['qualified'] else 1

if __name__=='__main__':raise SystemExit(main())
