#!/usr/bin/env python

from glob import glob
import json
import os

from fabric.api import *
import requests

import app
import app_config
from etc import github

"""
Base configuration
"""
env.project_name = app_config.PROJECT_NAME
env.deployed_name = app_config.DEPLOYED_NAME
env.code_root_name = app_config.CODE_ROOT_NAME
env.deploy_to_servers = True
env.repo_url = 'git@github.com:nprapps/%(code_root_name)s.git' % env
env.alt_repo_url = None  # 'git@bitbucket.org:nprapps/%(code_root_name)s.git' % env
env.user = 'ubuntu'
env.python = 'python2.7'
env.path = '/home/%(user)s/apps/%(code_root_name)s' % env
env.repo_path = '%(path)s/repository' % env
env.virtualenv_path = '%(path)s/virtualenv' % env
env.forward_agent = True

"""
Environments
"""
def production():
    env.settings = 'production'
    env.s3_buckets = app_config.PRODUCTION_S3_BUCKETS
    env.hosts = app_config.PRODUCTION_SERVERS

def staging():
    env.settings = 'staging'
    env.s3_buckets = app_config.STAGING_S3_BUCKETS
    env.hosts = app_config.STAGING_SERVERS

"""
Branches
"""
def stable():
    """
    Work on stable branch.
    """
    env.branch = 'stable'

def master():
    """
    Work on development branch.
    """
    env.branch = 'master'

def branch(branch_name):
    """
    Work on any specified branch.
    """
    env.branch = branch_name

def _confirm_branch():
    """
    Confirm a production deployment.
    """
    if (env.settings == 'production' and env.branch != 'stable'):
        answer = prompt("You are trying to deploy the '%(branch)s' branch to production.\nYou should really only deploy a stable branch.\nDo you know what you're doing?" % env, default="Not at all")
        if answer not in ('y','Y','yes','Yes','buzz off','screw you'):
            exit()

"""
Template-specific functions
"""
def less():
    """
    Render LESS files to CSS.
    """
    for path in glob('less/*.less'):
        filename = os.path.split(path)[-1]
        name = os.path.splitext(filename)[0]
        out_path = 'www/css/%s.less.css' % name

        local('node_modules/less/bin/lessc %s %s' % (path, out_path))

def jst():
    """
    Render Underscore templates to a JST package.
    """
    local('node_modules/universal-jst/bin/jst.js --template underscore jst www/js/templates.js')

def app_config_js():
    """
    Render app_config.js to file.
    """
    from app import _app_config_js

    response = _app_config_js()
    js = response[0]

    with open('www/js/app_config.js', 'w') as f:
        f.write(js)

def render():
    """
    Render HTML templates and compile assets.
    """
    from flask import g

    less()
    jst()

    # Fake out deployment target
    app_config.configure_targets(env.get('settings', None))

    app_config_js()

    compiled_includes = []

    for rule in app.app.url_map.iter_rules():
        rule_string = rule.rule
        name = rule.endpoint

        if name == 'static':
            print 'Skipping %s' % name
            continue

        if name.startswith('_'):
            print 'Skipping %s' % name
            continue

        if rule_string.endswith('/'):
            filename = 'www' + rule_string + 'index.html'
        else:
            filename = 'www' + rule_string

        print 'Rendering %s' % (filename)

        with app.app.test_request_context(path=rule_string):
            g.compile_includes = True
            g.compiled_includes = compiled_includes

            view = app.__dict__[name]
            content = view()

            compiled_includes = g.compiled_includes

        if not isinstance(content, basestring):
            content = content[0]

        with open(filename, 'w') as f:
            f.write(content)

    # Un-fake-out deployment target
    app_config.configure_targets(app_config.DEPLOYMENT_TARGET)

"""
Setup
"""
def setup():
    """
    Setup servers for deployment.
    """
    require('settings', provided_by=[production, staging])
    require('branch', provided_by=[stable, master, branch])

    setup_directories()
    setup_virtualenv()
    clone_repo()
    checkout_latest()
    install_requirements()

def setup_directories():
    """
    Create server directories.
    """
    require('settings', provided_by=[production, staging])

    run('mkdir -p %(path)s' % env)

def setup_virtualenv():
    """
    Setup a server virtualenv.
    """
    require('settings', provided_by=[production, staging])

    run('virtualenv -p %(python)s --no-site-packages %(virtualenv_path)s' % env)
    run('source %(virtualenv_path)s/bin/activate' % env)

def clone_repo():
    """
    Clone the source repository.
    """
    require('settings', provided_by=[production, staging])

    run('git clone %(repo_url)s %(repo_path)s' % env)

    if env.get('alt_repo_url', None):
        run('git remote add bitbucket %(alt_repo_url)s' % env)

def checkout_latest(remote='origin'):
    """
    Checkout the latest source.
    """
    require('settings', provided_by=[production, staging])

    env.remote = remote

    run('cd %(repo_path)s; git fetch %(remote)s' % env)
    run('cd %(repo_path)s; git checkout %(branch)s; git pull %(remote)s %(branch)s' % env)


def install_requirements():
    """
    Install the latest requirements.
    """
    require('settings', provided_by=[production, staging])

    run('%(virtualenv_path)s/bin/pip install -U -r %(repo_path)s/requirements.txt' % env)


def install_crontab():
    """
    Install cron jobs script into cron.d.
    """
    require('settings', provided_by=[production, staging])

    sudo('cp %(repo_path)s/crontab /etc/cron.d/%(deployed_name)s' % env)


def uninstall_crontab():
    """
    Remove a previously install cron jobs script from cron.d
    """
    require('settings', provided_by=[production, staging])

    sudo('rm /etc/cron.d/%(deployed_name)s' % env)


def bootstrap_issues():
    """
    Bootstraps Github issues with default configuration.
    """
    auth = github.get_auth()
    github.delete_existing_labels(auth)
    github.create_default_labels(auth)
    github.create_default_tickets(auth)

"""
Deployment
"""
def _deploy_to_s3():
    """
    Deploy the gzipped stuff to S3.
    """
    s3cmd = 's3cmd -P --add-header=Cache-Control:max-age=5 --guess-mime-type --recursive --exclude-from gzip_types.txt sync gzip/ %s'
    s3cmd_gzip = 's3cmd -P --add-header=Cache-Control:max-age=5 --add-header=Content-encoding:gzip --guess-mime-type --recursive --exclude "*" --include-from gzip_types.txt sync gzip/ %s'

    for bucket in env.s3_buckets:
        env.s3_bucket = bucket
        local(s3cmd % ('s3://%(s3_bucket)s/%(deployed_name)s/' % env))
        local(s3cmd_gzip % ('s3://%(s3_bucket)s/%(deployed_name)s/' % env))

def _gzip_www():
    """
    Gzips everything in www and puts it all in gzip.
    """
    local('python gzip_www.py')

def deploy(remote='origin'):
    require('settings', provided_by=[production, staging])
    require('branch', provided_by=[stable, master, branch])

    _confirm_branch()
    render()
    _gzip_www()
    _deploy_to_s3()

    if env.get('deploy_to_servers', False):
        checkout_latest(remote)

"""
Destruction
"""
def shiva_the_destroyer():
    """
    Deletes the app from s3
    """
    with settings(warn_only=True):
        s3cmd = 's3cmd del --recursive %s'

        for bucket in env.s3_buckets:
            env.s3_bucket = bucket
            local(s3cmd % ('s3://%(s3_bucket)s/%(deployed_name)s' % env))

        if env.get('deploy_to_servers', False):
            run('rm -rf %(path)s' % env)

"""
App-specific utils
"""
def update_csv():
    """
    Pulls the latest version of Oscars data from Google Doc.
    """
    response = requests.get('https://docs.google.com/spreadsheet/pub?key=0AiINjEdvBDPadFUtUWk5MEpqWDNrODlULU9VSG1MM3c&output=csv')
    with open('data/best-picture.csv', 'w') as f:
        f.write(response.text)


def build_awards_json():
    url = 'https://spreadsheets.google.com/feeds/list/0AjWpFWKpoFHqdDZHaTExd1Rpcl9aLTFIaVhIR2RRdWc/od6/public/values?alt=json-in-script&sq='
    r = requests.get(url)

    if r.status_code == 200:
        json_data = json.loads(r.content.replace('gdata.io.handleScriptLoaded(', '').replace(');', ''))
        with_winners = []
        without_winners = []

        for row in json_data['feed']['entry']:
            award_dict = {}
            award_dict['award'] = row['title']['$t']
            award_dict['nominees'] = []
            award_dict['has_winner'] = False
            for nominee_number in range(1, 10):
                nominee = row['gsx$nominee%s' % nominee_number]['$t']
                if nominee != u'':
                    nominee_dict = {}
                    nominee_dict['title'] = nominee
                    nominee_dict['winner'] = False
                    if row['gsx$winner']['$t'] == nominee:
                        nominee_dict['winner'] = True
                        award_dict['has_winner'] = True

                    if nominee in row['gsx$winner']['$t']:
                        nominee_dict['winner'] = True
                        award_dict['has_winner'] = True

                    award_dict['nominees'].append(nominee_dict)

            if award_dict['has_winner']:
                with_winners.append(award_dict)
            else:
                without_winners.append(award_dict)

    output = {
        'with_winners': with_winners,
        'without_winners': without_winners
    }

    with open('www/live-data/awards.json', 'w') as f:
        f.write(json.dumps(output))


def deploy_awards_json():
    """
    Deploy awards JSON to S3
    """
    require('settings', provided_by=[production, staging])
    build_awards_json()
    s3cmd = 's3cmd -P --add-header=Cache-Control:max-age=5 --guess-mime-type put /home/ubuntu/apps/oscars/repository/www/live-data/awards.json %s'
    for bucket in env.s3_buckets:
        env.s3_bucket = bucket
        local(s3cmd % ('s3://%(s3_bucket)s/%(deployed_name)s/live-data/awards.json' % env))
