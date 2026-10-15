"""Serve only public local evidence, including byte ranges for playable/seekable MP4."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import argparse,re,os
ROOT=Path(__file__).resolve().parents[1]/'research/evidence'
class EvidenceHandler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        self._byte_range=None
        super().__init__(*args,directory=str(ROOT),**kwargs)
    def translate_path(self,path):
        result=Path(super().translate_path(path)).resolve()
        try:result.relative_to(ROOT.resolve())
        except ValueError:return str(ROOT/'_outside_public_root_blocked')
        return str(result)
    def list_directory(self,path):
        self.send_error(404,'No reader page at this path')
        return None
    def send_head(self):
        self._byte_range=None
        name=self.translate_path(self.path)
        if os.path.isfile(name) and self.headers.get('Range'):
            size=os.path.getsize(name)
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'].strip())
            if not match or not any(match.groups()):return self.unsatisfiable(size)
            first,last=match.groups()
            if not first:
                count=int(last);start=max(0,size-count);end=size-1
            else:
                start=int(first);end=min(size-1,int(last)) if last else size-1
            if start>=size or start<0 or end<start:return self.unsatisfiable(size)
            stream=open(name,'rb');stat=os.fstat(stream.fileno());self._byte_range=(start,end)
            self.send_response(206)
            self.send_header('Content-type',self.guess_type(name))
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length',str(end-start+1))
            self.send_header('Last-Modified',self.date_time_string(stat.st_mtime))
            self.end_headers();stream.seek(start)
            return stream
        return super().send_head()
    def unsatisfiable(self,size):
        self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return None
    def end_headers(self):
        if self._byte_range is None:self.send_header('Accept-Ranges','bytes')
        super().end_headers()
    def copyfile(self,source,outputfile):
        if self._byte_range is None:return super().copyfile(source,outputfile)
        remaining=self._byte_range[1]-self._byte_range[0]+1
        while remaining:
            block=source.read(min(64*1024,remaining))
            if not block:break
            try:outputfile.write(block)
            except (BrokenPipeError,ConnectionResetError):break
            remaining-=len(block)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--port',type=int,default=4311);args=parser.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),EvidenceHandler)
    print(f'Local public evidence: http://127.0.0.1:{args.port}/ (HTTP Range supported)',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
