#!/usr/bin/env python

import csv
import json
from mimetypes import guess_type
import urllib

import envoy
from flask import Flask, Markup, abort, render_template

import app_config
from render_utils import flatten_app_config, make_context
app = Flask(app_config.PROJECT_NAME)

# Example application views
@app.route('/best-picture.html')
def best_picture():
    context = make_context()
    context['PAGE_NAME'] = 'best-picture'

    return render_template('best-picture.html', **context)

@app.route('/')
@app.route('/chat.html')
def chat():
    context = make_context()
    context['PAGE_NAME'] = 'index'
    return render_template('chat.html', **make_context())

def _make_data_json(filename):
    """
    Generate data.
    """
    with open('data/%s.csv' % filename) as f:
        rows = list(csv.reader(f))

    slides = []

    for row in rows[1:]:
        if filename == 'best-picture':
            slide = {
                'sort': row[0],
                'movie_name': row[0],
                'img_filename': row[1],
                'link1_title': row[2],
                'link1_url': row[3],
                'link2_title': row[4],
                'link2_url': row[5],
                'link3_title': row[6],
                'link3_url': row[7],
                'link4_title': row[8],
                'link4_url': row[9]
            }
        elif filename == 'best-actor':
            slide = {
                'sort': row[0],
                'movie_name': row[0],
                'img_filename': row[1],
                'link1_title': row[2],
                'link1_url': row[3],
            }

        slides.append(slide)

    return json.dumps(slides), 200, { 'Content-Type': 'application/javascript' }

# @app.route('/live-data/best-picture.json')
# def best_picture_json():
#     return _make_data_json('best-picture')

# @app.route('/widget.html')
# def widget():
#     """
#     Embeddable widget example page.
#     """
#     return render_template('widget.html', **make_context())

# @app.route('/test_widget.html')
# def test_widget():
#     """
#     Example page displaying widget at different embed sizes.
#     """
#     return render_template('test_widget.html', **make_context())

# Render LESS files on-demand
@app.route('/less/<string:filename>')
def _less(filename):
    try:
        with open('less/%s' % filename) as f:
            less = f.read()
    except IOError:
        abort(404)

    r = envoy.run('node_modules/less/bin/lessc -', data=less)

    return r.std_out, 200, { 'Content-Type': 'text/css' }

# Render JST templates on-demand
@app.route('/js/templates.js')
def _templates_js():
    r = envoy.run('node_modules/universal-jst/bin/jst.js --template underscore jst')

    return r.std_out, 200, { 'Content-Type': 'application/javascript' }

# Render application configuration
@app.route('/js/app_config.js')
def _app_config_js():
    config = flatten_app_config()
    js = 'window.APP_CONFIG = ' + json.dumps(config)

    return js, 200, { 'Content-Type': 'application/javascript' }

# Server arbitrary static files on-demand
@app.route('/<path:path>')
def _static(path):
    try:
        with open('www/%s' % path) as f:
            print guess_type(path)[0]
            return f.read(), 200, { 'Content-Type': guess_type(path)[0] }
    except IOError:
        abort(404)

@app.template_filter('urlencode')
def urlencode_filter(s):
    """
    Filter to urlencode strings.
    """
    if type(s) == 'Markup':
        s = s.unescape()

    s = s.encode('utf8')
    s = urllib.quote_plus(s)

    return Markup(s)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=app_config.DEBUG)
