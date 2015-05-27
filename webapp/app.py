#!/usr/bin/env python
# -*- coding: utf-8 -*-
##
##  Whabapp - A Web application microframework
##
##  usage: $ python app.py -s localhost 8080
##
import sys
import re
import cgi
import os.path
import sqlite3

# quote HTML metacharacters.
def q(s):
    assert isinstance(s, basestring), s
    return (s.
            replace('&','&amp;').
            replace('>','&gt;').
            replace('<','&lt;').
            replace('"','&#34;').
            replace("'",'&#39;'))

# encode as a URL.
URLENC = re.compile(r'[^a-zA-Z0-9_.-]')
def urlenc(url, codec='utf-8'):
    def f(m):
        return '%%%02X' % ord(m.group(0))
    return URLENC.sub(f, url.encode(codec))

# remove redundant spaces.
RMSP = re.compile(r'\s+', re.U)
def rmsp(s):
    return RMSP.sub(' ', s.strip())

# merge two dictionaries.
def mergedict(d1, d2):
    d1 = d1.copy()
    d1.update(d2)
    return d1

# iterable
def iterable(obj):
    return hasattr(obj, '__iter__')

# closable
def closable(obj):
    return hasattr(obj, 'close')


##  Template
##
class Template(object):

    debug = 0

    def __init__(self, *args, **kwargs):
        if '_copyfrom' in kwargs:
            _copyfrom = kwargs['_copyfrom']
            objs = _copyfrom.objs
            kwargs = mergedict(_copyfrom.kwargs, kwargs)
        else:
            objs = []
            for line in args:
                i0 = 0
                for m in self._VARIABLE.finditer(line):
                    objs.append(line[i0:m.start(0)])
                    x = m.group(1)
                    if x == '$':
                        objs.append(x)
                    else:
                        objs.append(self.Variable(x[0], x[1:-1]))
                    i0 = m.end(0)
                objs.append(line[i0:])
        self.objs = objs
        self.kwargs = kwargs
        return

    def __call__(self, **kwargs):
        return self.__class__(_copyfrom=self, **kwargs)

    def __iter__(self):
        return self.render()

    def __repr__(self):
        return '<Template %r>' % self.objs

    def __str__(self):
        return ''.join(self)

    @classmethod
    def load(klass, lines, **kwargs):
        template = klass(*lines, **kwargs)
        if closable(lines):
            lines.close()
        return template
    
    def render(self, codec='utf-8', **kwargs):
        kwargs = mergedict(self.kwargs, kwargs)
        def render1(value, quote=False):
            if value is None:
                pass
            elif isinstance(value, Template):
                if quote:
                    if 2 <= self.debug:
                        raise ValueError
                    elif self.debug:
                        yield '[ERROR: Template in a quoted context]'
                else:
                    for x in value.render(codec=codec, **kwargs):
                        yield x
            elif isinstance(value, dict):
                if 2 <= self.debug:
                    raise ValueError
                elif self.debug:
                    yield '[ERROR: Dictionary included]'
            elif isinstance(value, basestring):
                if quote:
                    yield q(value)
                else:
                    yield value
            elif callable(value):
                for x in render1(value(**kwargs), quote=quote):
                    yield x
            elif iterable(value):
                for obj1 in value:
                    for x in render1(obj1, quote=quote):
                        yield x
            else:
                if quote:
                    yield q(unicode(value))
                else:
                    if 2 <= self.debug:
                        raise ValueError
                    elif self.debug:
                        yield '[ERROR: Non-string object in a non-quoted context]'
            return
        for obj in self.objs:
            if isinstance(obj, self.Variable):
                k = obj.name
                if k in kwargs:
                    value = kwargs[k]
                elif k in self.kwargs:
                    value = self.kwargs[k]
                else:
                    yield '[notfound:%s]' % k
                    continue
                if obj.type == '(':
                    for x in render1(value, quote=True):
                        yield x
                    continue
                elif obj.type == '[':
                    yield urlenc(value)
                    continue
            else:
                value = obj
            for x in render1(value):
                yield x
        return

    _VARIABLE = re.compile(r'\$(\(\w+\)|\[\w+\]|<\w+>)')
    
    class Variable(object):
        
        def __init__(self, type, name):
            self.type = type
            self.name = name
            return
        
        def __repr__(self):
            if self.type == '(':
                return '$(%s)' % self.name
            elif self.type == '[':
                return '$[%s]' % self.name
            else:
                return '$<%s>' % self.name
    

##  Router
##
class Router(object):
    
    def __init__(self, method, regex, func):
        self.method = method
        self.regex = regex
        self.func = func
        return

    @staticmethod
    def make_wrapper(method, pat):
        regex = re.compile('^'+pat+'$')
        def wrapper(func):
            return Router(method, regex, func)
        return wrapper

def GET(pat): return Router.make_wrapper('GET', pat)
def POST(pat): return Router.make_wrapper('POST', pat)


##  Response
##
class Response(object):

    def __init__(self, status='200 OK', content_type='text/html', **kwargs):
        self.status = status
        self.headers = [('Content-Type', content_type)]+kwargs.items()
        return

    def add_header(self, k, v):
        self.headers.append((k, v))
        return

class Redirect(Response):

    def __init__(self, location):
        Response.__init__(self, '302 Found', Location=location)
        return

class NotFound(Response):

    def __init__(self):
        Response.__init__(self, '404 Not Found')
        return

class InternalError(Response):

    def __init__(self):
        Response.__init__(self, '500 Internal Server Error')
        return


##  WebApp
##
class WebApp(object):

    debug = 0
    codec = 'utf-8'
    
    def run(self, environ, start_response):
        method = environ.get('REQUEST_METHOD', 'GET')
        path = environ.get('PATH_INFO', '/')
        fp = environ.get('wsgi.input')
        fields = cgi.FieldStorage(fp=fp, environ=environ)
        result = None
        for attr in dir(self):
            router = getattr(self, attr)
            if not isinstance(router, Router): continue
            if router.method != method: continue
            m = router.regex.match(path)
            if m is None: continue
            params = m.groupdict().copy()
            params['_path'] = path
            params['_fields'] = fields
            params['_environ'] = environ
            code = router.func.func_code
            args = code.co_varnames[:code.co_argcount]
            kwargs = {}
            for k in args[1:]:
                if k in fields:
                    kwargs[k] = fields.getvalue(k)
                elif k in params:
                    kwargs[k] = params[k]
            try:
                result = router.func(self, **kwargs)
            except TypeError:
                if 2 <= self.debug:
                    raise
                elif self.debug:
                    result = [InternalError()]
            break
        if result is None:
            result = self.get_default(path, fields, environ)
        def f(obj):
            if isinstance(obj, Response):
                start_response(obj.status, obj.headers)
            elif isinstance(obj, Template):
                for x in obj.render(codec=self.codec):
                    if isinstance(x, unicode):
                        x = x.encode(self.codec)
                    yield x
            elif iterable(obj):
                for x in obj:
                    for y in f(x):
                        yield y
            else:
                if isinstance(obj, unicode):
                    obj = obj.encode(self.codec)
                yield obj
        return f(result)

    def get_default(self, path, fields, environ):
        return [NotFound(), '<html><body>not found</body></html>']


# run_server
def run_server(host, port, app):
    from wsgiref.simple_server import make_server
    print >>sys.stderr, 'Serving on %r port %d...' % (host, port)
    httpd = make_server(host, port, app.run)
    httpd.serve_forever()

# run_cgi
def run_cgi(app):
    from wsgiref.handlers import CGIHandler
    CGIHandler().run(app.run)

# run_httpcgi: for cgi-httpd
def run_httpcgi(app):
    from wsgiref.handlers import CGIHandler
    class HTTPCGIHandler(CGIHandler):
        def start_response(self, status, headers, exc_info=None):
            protocol = self.environ.get('SERVER_PROTOCOL', 'HTTP/1.0')
            sys.stdout.write('%s %s\r\n' % (protocol, status))
            return CGIHandler.start_response(self, status, headers, exc_info=exc_info)
    HTTPCGIHandler().run(app.run)

# main
def main(app, argv):
    import getopt
    def usage():
        print 'usage: %s [-d] [-s] [host [port]]' % argv[0]
        return 100
    try:
        (opts, args) = getopt.getopt(argv[1:], 'ds')
    except getopt.GetoptError:
        return usage()
    server = False
    debug = 0
    for (k, v) in opts:
        if k == '-d': debug += 1
        elif k == '-s': server = True
    Template.debug = debug
    WebApp.debug = debug
    if server:
        host = ''
        port = 8080
        if args:
            host = args.pop(0)
        if args:
            port = int(args.pop(0))
        run_server(host, port, app)
    else:
        run_cgi(app)
    return


##  VMap
##
class VMap(WebApp):

    DBPATH = './out/'
    HEADER = '''<!DOCTYPE html>
<html>
<head><title>vmap</title></head>
<body>
'''
    FOOTER = '''
</body>
</html>
'''
    
    def __init__(self):
        self.osm_db = sqlite3.connect(os.path.join(self.DBPATH, 'osm.db'))
        self.addr_db = sqlite3.connect(os.path.join(self.DBPATH, 'addr.db'))
        return
    
    @GET('/')
    def index(self):
        yield Response()
        yield self.HEADER
        yield Template(
            u'<h1>vmap</h1>\n'
            u'<form method=GET action="/addr">\n'
            u'住所または郵便番号を入力してください:<br>'
            u'<input name=s size=50>\n'
            u'<input name=cmd type=submit value="検索">\n'
            u'</form>\n')
        yield self.FOOTER
        return
    
    @GET('/addr')
    def hello(self, s):
        from search_addr import search
        from addrdict import PREF, REGION
        yield Response()
        yield self.HEADER
        cur = self.addr_db.cursor()
        s = s.decode(self.codec)
        yield Template(u'<h1>「$(s)」の検索結果</h1>', s=s)
        aids = []
        for r in search(cur, s):
            if r is None: continue
            aids.extend(r)
        if not aids:
            yield Template(u'<p> 該当する住所が見つかりませんでした。\n')
        else:
            yield Template(u'<p> $(n)件の住所が見つかりました。\n', n=len(aids))
            yield '<ul>\n'
            for aid in aids:
                cur.execute('SELECT rgncode,name,postal,lat,lng FROM address WHERE aid=?;',
                            (aid,))
                for (rgncode,name,postal,lat,lng) in cur:
                    yield Template(
                        u'<li> <a href="/search?p=$[lat],$[lng]">'
                        u'〒$(postal) $(pref) $(region) $(name)</a>\n',
                        postal=(postal[:3]+'-'+postal[3:]),
                        pref=PREF[rgncode/1000], region=REGION[rgncode],
                        name=name, lat=str(lat), lng=str(lng))
            yield '</ul>\n'
        yield self.FOOTER
        return
    
    @GET('/search')
    def search(self, p):
        from search_obj import search
        from addrdict import PREF, REGION
        try:
            (lat0,_,lng0) = p.partition(',')
            lat0 = float(lat0)
            lng0 = float(lng0)
        except ValueError:
            yield InternalError()
            return
        yield Response()
        yield self.HEADER
        node = self.osm_db.cursor()
        point = self.osm_db.cursor()
        entity = self.osm_db.cursor()
        kwds = []
        yield '<ul>\n'
        for (nid,lat1,lng1,name,props) in search(node, point, entity, lat0, lng0, kwds):
            yield Template(
                u'<li> $(name) $(props)',
                name=name, props=props)
        yield '</ul>\n'
        yield self.FOOTER
        return

if __name__ == '__main__': sys.exit(main(VMap(), sys.argv))