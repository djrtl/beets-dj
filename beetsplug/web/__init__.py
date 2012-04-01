# This file is part of beets.
# Copyright 2011, Adrian Sampson.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
# 
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

"""A Web interface to beets."""
from beets.plugins import BeetsPlugin
from beets import ui
from beets.importer import _reopen_lib
import beets.library
import flask
from flask import g, Response, request
from werkzeug.datastructures import Headers
import re
# this was moved in 0.7
try:
    from werkzeug.wsgi import wrap_file
except ImportError:
    from werkzeug.utils import wrap_file


DEFAULT_HOST = ''
DEFAULT_PORT = 8337
DEFAULT_STREAMING_FORMAT = 'original'


# Utilities.

def _rep(obj):
    if isinstance(obj, beets.library.Item):
        out = dict(obj.record)
        del out['path']
        return out
    elif isinstance(obj, beets.library.Album):
        out = dict(obj._record)
        del out['artpath']
        out['items'] = [_rep(item) for item in obj.items()]
        return out


# Flask setup.

app = flask.Flask(__name__)

@app.before_request
def before_request():
    g.lib = _reopen_lib(app.config['lib'])
@app.teardown_request
def teardown_request(req):
    g.lib.conn.close()


# Items.

@app.route('/item/<int:item_id>')
def single_item(item_id):
    item = g.lib.get_item(item_id)
    return flask.jsonify(_rep(item))

@app.route('/item/')
def all_items():
    with g.lib.transaction() as tx:
        rows = tx.query("SELECT id FROM items")
    all_ids = [row[0] for row in rows]
    return flask.jsonify(item_ids=all_ids)

@app.route('/item/<int:item_id>/file')
def item_file(item_id):
    item = g.lib.get_item(item_id)
    return flask.send_file(item.path, as_attachment=True)

@app.route('/item/<int:item_id>/ogg_q<int:ogg_q>')
def item_ogg(item_id, ogg_q):
    from subprocess import Popen, PIPE
    import mimetypes;
    item = g.lib.get_item(item_id)
    filename = os.path.split(item.path)[1]
    filename = os.path.splitext(filename)[0] + '.ogg'

    headers = Headers()
    headers.add('Content-Type', 'audio/ogg')
    headers.add('Content-Disposition', 'attachment', filename=filename)

    if mimetypes.guess_type(item.path)[0] == 'audio/mpeg':
        decoded_fp = Popen(
            ["mpg123", "-q", "-w", "/dev/stdout", item.path],
            stdout=PIPE)
        ogg_fp = Popen(
            ["oggenc", "-q", str(ogg_q), "-Q", "-"],
            stdin=decoded_fp.stdout,
            stdout=PIPE);
        decoded_fp.stdout.close()
    else:
        ogg_fp = Popen(
            ["oggenc", "-q",  str(ogg_q),"-Q", "-o", "/dev/stdout", item.path],
            stdout=PIPE);

    res = Response(
        #wrap_file(request.environ, ogg_fp.stdout),
        ogg_fp.stdout,
        headers=headers,
        direct_passthrough=True)
    res.implicit_sequence_conversion = False

    return res

@app.route('/item/<int:item_id>/stream')
def item_stream(item_id):
  return app.config['stream_func'](item_id)

@app.route('/item/query/<path:query>')
def item_query(query):
    parts = query.split('/')
    items = g.lib.items(parts)
    return flask.jsonify(results=[_rep(item) for item in items])


# Albums.

@app.route('/album/<int:album_id>')
def single_album(album_id):
    album = g.lib.get_album(album_id)
    return flask.jsonify(_rep(album))

@app.route('/album/')
def all_albums():
    with g.lib.transaction() as tx:
        rows = tx.query("SELECT id FROM albums")
    all_ids = [row[0] for row in rows]
    return flask.jsonify(album_ids=all_ids)

@app.route('/album/query/<path:query>')
def album_query(query):
    parts = query.split('/')
    albums = g.lib.albums(parts)
    return flask.jsonify(results=[_rep(album) for album in albums])

@app.route('/album/<int:album_id>/art')
def album_art(album_id):
    album = g.lib.get_album(album_id)
    return flask.send_file(album.artpath)


# UI.

@app.route('/')
def home():
    return flask.render_template('index.html')


# Plugin hook.

class WebPlugin(BeetsPlugin):
    def commands(self):
        cmd = ui.Subcommand('web', help='start a Web interface')
        cmd.parser.add_option('-d', '--debug', action='store_true',
                              default=False, help='debug mode')
        def func(lib, config, opts, args):
            host = args.pop(0) if args else \
                beets.ui.config_val(config, 'web', 'host', DEFAULT_HOST)
            port = args.pop(0) if args else \
                beets.ui.config_val(config, 'web', 'port', str(DEFAULT_PORT))
            port = int(port)

            stream_format = beets.ui.config_val(config, 'web',
                'stream_format', DEFAULT_STREAMING_FORMAT)
            captures = re.match(r'ogg_q([0-9])', stream_format)
            if captures:
                quality = captures.group(1)
                app.config['stream_func'] = lambda x: item_ogg(x, quality)
            else:
                app.config['stream_func'] = item_file

            app.config['lib'] = lib
            app.run(host=host, port=port, debug=opts.debug, threaded=True)
        cmd.func = func
        return [cmd]
