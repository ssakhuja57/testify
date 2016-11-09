import sys
sys.path.append('lib/')
import web
import os
import testify
import json
from RestHelper import RestHelper


EMAIL_SERVER = 'api.sparkpost.com'
EMAIL_PORT = 443
EMAIL_FROM = 'donotreply@thingspace.verizon.com'
EMAIL_AUTH = '7c2d9b98dc84816588131e2633e44109f6677bba'
DNS_SUFFIX = os.environ.get('DNS_SUFFIX', 'suffix_not_passed')
STATE_FILE = 'state.json'

def log(msg):
	print msg

def send_email_http(host, success, results, email_on_fail, email_on_success, last_state):
	if success and last_state:
		if email_on_success is None:
			log('success and email_on_success not defined, not sending email')
			return
		email_to = email_on_success
	else:
		if email_on_fail is None:
			log('not success and email_on_fail not defined, not sending email')
			return
		email_to = email_on_fail

	email_list = []
	for email in email_to.split(','):
		email_list.append({'address': {'email': email, 'header_to': email_to}})

	result = 'Success' if success else 'Failed'

	data = {'content': {
			'from': EMAIL_FROM,
			'subject': 'Report ' + result + ': ' + host,
			'html': results
			},
		'recipients': email_list
		}
	uri = '/api/v1/transmissions'
	method = 'POST'

	log('sending email report')
	try:
		restHelper = RestHelper(EMAIL_SERVER, EMAIL_PORT, secure=True, check_cert=False)
		resp = restHelper.request(method, uri, data=json.dumps(data), content_type='application/json', auth=EMAIL_AUTH)
		log(resp.read())
	except Exception as e:
		log('error sending email: ' + str(e))

def get_stack_state(dc, stack):
	return state[dc][stack]

def update_stack_state(dc, stack, val):
	if state.get(dc, None) is None:
		state[dc] = {}
	state[dc][stack] = val
	json.dump(state, open(STATE_FILE, 'w'), indent=4)
	

def get_configs_dropdown(name, dir_name):
	files = os.listdir(dir_name)
	options = [f[:-5] for f in files if f.endswith('.json')]
	return get_dropdown(name, options)

def get_dropdown(name, options):
	res = '<select name="%s">' % (name)
	for o in options:
		res += '<option value="%s">%s</option>' % (o, o)
	res += '</select>'
	return res

def get_cfg(folder, name):
	return json.loads(open(folder + '/' + name + '.json').read())


urls = (
        '/testify/edit/(.*)', 'editor',
	'/testify', 'menu',
	'/testify/run', 'run',
	'/testify/run_proxy', 'run_proxy',
)
app = web.application(urls, globals())

class editor:
	def GET(self, type):
		params = web.input(name=None)
		object_str = '{}' if params.name is None else open('configs/{}/{}.json'.format(type, params.name)).read()
		schema = open('schemas/' + type + '.json').read()
		options = get_configs_dropdown('name', 'configs/' + type)
		editor_vals = {'type': type, 'schema': schema, 'cfg': object_str, 'options': options}
		return open('static/editor.html').read() % editor_vals

	def POST(self, type):
		data = web.data()
		obj = json.loads(data)
		name = obj['name']
		if name.strip() == '':
			return 'name field is required'
		locked = open('configs/{}/locked'.format(type) ).read().strip().split(',')
		if name in locked:
			return 'unable to modify locked config ' + name
		f = 'configs/{}/{}.json'.format(type, name)
		open(f, 'w').write(data)
		return 'config saved successfully'

class menu:
	def GET(self):
		html = '''
			<a href="/testify/run">Run</a><br>
			<a href="/testify/edit/host">Add/Edit Host Sets</a><br>
			<a href="/testify/edit/suite">Add/Edit Suites</a><br>
			'''
		return html

class run:
	def GET(self):
		params = web.input(host=None, suite=None, group=None, email_on_success=None, email_on_fail=None, fmt='html')
		host = params.host
		suite = params.suite
                group = params.group
		if suite is None or (group is None and host is None):
                        log('suite and a host/group must be supplied')
			html = '<html><form>'
			html += get_configs_dropdown('host', 'configs/host')
			html += '<br>'
			html += get_configs_dropdown('suite', 'configs/suite')
			html += '<br>'
			html += '<input type="submit">'
			html += '</form></html>'
			return html
                if group is not None:
                        log('using default host set with group: ' + group)
                        host_cfg = {
                                    'name': group,
                                    'hosts': [
                                        {
                                         'hostname': 'nginx-{}-ts{}'.format(group, DNS_SUFFIX),
                                         'port': 443,
                                         'secure': True,
                                         'check-cert': False
                                        },
                                        {
                                         'hostname': 'user-{}-ts{}'.format(group, DNS_SUFFIX),
                                         'port': 8089,
                                         'secure': False,
                                         'check-cert': False
                                        }
                                     ]
                                    }
                else:
                        host_cfg = get_cfg('configs/host', host)
		host = testify.HostSet(host_cfg)
		suite = testify.TestSuite(get_cfg('configs/suite', suite))
		runner = testify.TestRunner(host, suite)
                results_obj = runner.runTests()
		results_html = testify.results_to_html(results_obj)

		# email report
		success = True if results_obj['tests_failed'] == 0 else False
		send_email_http(params.host, success, results_html, params.email_on_fail, params.email_on_success)

                if params.fmt == 'html':
        		return results_html
                elif params.fmt == 'json':
                        return json.dumps(results_obj)
                else:
                        return json.dumps({'error': 'unknown format: ' + params.fmt})

class run_proxy:
	def GET(self):
		params = web.input(dc=None, agent=None, suite=None, group=None, email_on_fail=None, email_on_success=None, fmt='html')
		if None in (params.dc, params.agent, params.suite, params.group):
			return 'dc, agent, suite, and group params are required'
		log('connecting to ' + params.agent)
		restHelper = RestHelper(params.agent, 80, secure=False)
		uri = '/testify/run?fmt=json&suite={}&group={}'.format(params.suite, params.group)
		log('requesting ' + uri)
		result = restHelper.request('GET', uri).read()
		log('response recieved, loading into object')
		results_obj = json.loads(result)
		success = True if results_obj['tests_failed'] == 0 else False
		results_html = testify.results_to_html(results_obj)
		last_state = get_stack_state(params.dc, params.group)
		send_email_http(params.dc + ' ' + params.group, success, results_html, params.email_on_fail, params.email_on_success, last_state)
		update_stack_state(params.dc, params.group, success)

                if params.fmt == 'html':
                        return results_html
                elif params.fmt == 'json':
                        return json.dumps(results_obj)
                else:
                        return json.dumps({'error': 'unknown format: ' + params.fmt})	

# create state file if DNE
if not os.path.exists(STATE_FILE):
	log('state file ' + STATE_FILE + ' not found, creating')
	json.dump({}, open(STATE_FILE, 'w'), indent=4)
log('loading state file ' + STATE_FILE)
state = json.load(open(STATE_FILE))
	
if __name__ == '__main__':
	app.run()
