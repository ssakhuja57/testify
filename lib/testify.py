from RestHelper import RestHelper
import json
import os
import time
import datetime
from jsonconv import *
import re
import copy

# data locations
#script_dir = os.path.dirname(os.path.realpath(__file__))
#resources_dir = script_dir + '/resources/'
#configs_dir = script_dir + '/configs/'
#suites_dir = configs_dir + 'suites/'
#hosts_dir = configs_dir + 'hosts/'

# constants + dependencies
DEBUG = False
TIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
SUCCESS = 'SUCCESS'
FAILED = 'FAILED'

# helpers
def log(msg):
	print '-- ' + msg

def get_current_time(time_zone='utc'):
	return datetime.datetime.utcnow()

def get_current_time_numeric():
	return get_current_time().strftime('%Y%m%d%H%M%S%f')

def get_rand_user(base_name='user'):
	return base_name + get_current_time_numeric()
def get_rand_email(base_name='user', domain='test.test'):
	return get_rand_user(base_name=base_name) + '@' + domain

# get time diff in milliseconds
def get_time_diff(t1, t2):
	if t1 is None or t2 is None:
		return 0
	return int((t2 - t1).microseconds/1000)

def results_to_html(results):
        res_cp = copy.deepcopy(results)
	for result in res_cp['test_results']:
		result_name = result['result']
		result_attr = TestResult.results[result_name]
		result['result'] = '<span style="color:{}">{}</span>'.format(result_attr['color'], result_name)
	table = json2html.convert(json=res_cp)
	return table

def xpath_get(mydict, path):
    elem = mydict
    try:
        for x in path.strip("/").split("/"):
            try:
                x = int(x)
                elem = elem[x]
            except ValueError:
                elem = elem.get(x)
    except:
        pass

    return elem

# classes

class RestTest(object):
	def __init__(self, cfg):
		self.name = cfg['name']
                self.host_index = cfg.get('host-index', 0)
		self.description = cfg['description']
		self.enabled = cfg['enabled']
                self.instances = cfg.get('instances', 1)
		request = cfg['request']
		self.uri = request['uri']
		self.method = request['method']
		self.auth = request.get('auth', '')
		self.data = request.get('data', '')
		self.content_type = request.get('content-type', None)

		response = cfg['response']
		self.expected_status_range = response['expected-status']
		self.expected_status_lower = int(self.expected_status_range.split('-')[0])
		try:
			self.expected_status_upper = int(self.expected_status_range.split('-')[1])
		except IndexError:
			self.expected_status_upper = self.expected_status_lower
		self.expected_response_field = response.get('expected-response-field', None)
		self.expected_response_value = response.get('expected-response-field-value', None)
		self.save_field = response.get('save-field', None)
		
		self.seconds_to_response_warning = response.get('warning-threshold', None)
		self.seconds_to_response_error = response.get('critical-threshold', None)

                # enforce some contstraints
                if self.instances > 1 and self.save_field is not None:
                        raise ValueError('cannot define a test with multiple instances and a save-field')
		
		if DEBUG:
			log('test definition object created: ' + str(vars(self)))

		# set defaults for start and end time in case test fails at setup time
		self.start_time = None
		self.end_time = None

	def start(self):
		self.start_time = get_current_time()

	def end(self):
		self.end_time = get_current_time()


class TestResult(object):
	results = {
		'SKIPPED': {'code': -1, 'color': '#0000CD'},
		'SUCCESS': {'code': 0, 'color': 'green'},
		'UNEXPECTED_HTTP_STATUS': {'code': 1, 'color': 'red'},
		'EXPECTED_KEY_NOT_FOUND': {'code': 2, 'color': 'red'},
		'EXPECTED_VALUE_NOT_FOUND': {'code': 3, 'color':'red'},
		# add more results here
		'UNCLASSIFIED_ERROR': {'code': 8675309, 'color': 'red'}
		}
	def __init__(self, result_name, detail):		
		self.result_name = result_name
		self.result_attr = self.results[self.result_name]
		self.code = self.result_attr['code']
		self.detail = detail
		if DEBUG:
			log('test result created with: ' + str(vars(self)))

class TestSuite(object):
	def __init__(self, cfg):
                self.name = cfg['name']
		self.tests = []
		for test in cfg['tests']:
			self.tests.append(RestTest(test))

class Host(object):
	def __init__(self, cfg):
		self.hostname = cfg['hostname']
		self.port = cfg['port']
		self.secure = cfg['secure']
		self.check_cert = cfg['check-cert']
		
		if DEBUG:
			log('host definition object created: ' + str(vars(self)))

class HostSet(object):
        def __init__(self, cfg):
                self.name = cfg['name']
                self.hosts = []
                for host_cfg in cfg['hosts']:
                        self.hosts.append(Host(host_cfg))

class TestRunner(object):
	def __init__(self, host_set, test_suite):
		# dictionary to store any values returned from tests
		self.values = {}
		self.values['cached'] = {}
		self.host_set = host_set
                self.restHelpers = []
                for host in self.host_set.hosts:
        		self.restHelpers.append(RestHelper(host.hostname, host.port, host.secure, check_cert=host.check_cert))
		self.test_suite = test_suite

	def runTests(self):
		test_results = {
                        'timestamp': get_current_time().strftime(TIME_FORMAT),
                        'host_set': self.host_set.name,
                        'suite': self.test_suite.name,
			'hosts': json.dumps([host.hostname + ':' + str(host.port) for host in self.host_set.hosts]),
        		'tests_passed': 0,
        		'tests_failed': 0,
        		'test_results': []
       	 		}
		for test in self.test_suite.tests:
			try:
				result = self.runTest(test)
			except Exception as e:
				if DEBUG:
					raise e
				else:
					result = TestResult('UNCLASSIFIED_ERROR', 'Test Exception: ' + str(e))
			passed = True
			if result.code == 0:
				test_results['tests_passed'] += 1
			elif result.code > 0:
				test_results['tests_failed'] += 1
				passed = False

			start_time = 'N/A' if test.start_time is None else test.start_time.strftime(TIME_FORMAT)
			time_diff_ms = 'N/A' if (test.start_time is None and test.end_time is None) else get_time_diff(test.start_time, test.end_time)

			test_summary = {'name': test.name,
	                        'description': test.description,
                                'instances': test.instances,
                                'host_index': test.host_index,
        	                #'status_code': result.status_code,
				'result': result.result_name,
                	        'result_detail': result.detail,
                        	'test_start': start_time, 
	                        'test_duration_ms': time_diff_ms
        	                }
		        test_results['test_results'].append(test_summary)
		
		return test_results

	
	def runTest(self, test):
		if DEBUG:
			log('preparing to run test: ' + test.name)
		if not test.enabled:
			return TestResult('SKIPPED', 'Test marked as disabled')
		name = test.name
		uri = self.expand_macros(test.uri)
		method = test.method
		data = self.expand_macros(test.data)
		content_type = test.content_type
		expected_status_lower = test.expected_status_lower
		expected_status_upper = test.expected_status_upper
		auth = self.expand_macros(test.auth)

		if DEBUG:
			log('running test ' + name + ': uri ' + uri + ', method ' + method + ', auth ' + auth + ', data ' + data + ', expected status ' + str(test.expected_status_range))
		
		test.start()
                for i in range(test.instances):
        		response = self.restHelpers[test.host_index].request(method, uri, data=data, content_type=content_type, auth=auth)
		test.end()

		if not expected_status_lower <= response.status <= expected_status_upper:
			result_detail = 'expected status ' + str(test.expected_status_range) + ', got ' + str(response.status) + ', response: ' + response.read()
			return TestResult('UNEXPECTED_HTTP_STATUS', result_detail)
	
		try:
			response_json = json.loads(response.read())
		except:
			response_json = None
		
		if DEBUG:
			log('response: ' + str(response_json))

		result_name = 'SUCCESS'
		result_detail = 'OK'

		save_field = test.save_field
		if save_field is not None:
			if DEBUG:
				log('saving value for response field ' + save_field)
	        value = xpath_get(response_json, save_field)
			if value is None:
				result_detail = 'expected but could not find key in response: ' + save_field
				return TestResult('EXPECTED_KEY_NOT_FOUND', result_detail)
			if DEBUG:
				log('saving field value ' + value + ' for field ' + save_field)
			if name in self.values:
				self.values[name][save_field] = value
			else:
				self.values[name] = {save_field: value}

		expected_response_field = test.expected_response_field
		if expected_response_field is not None:
			expected_response_value = self.expand_macros(test.expected_response_value)
			if DEBUG:
				log('looking for value ' + expected_response_value)
            value = xpath_get(response_json, expected_response_field)
            if value is None:
                result_detail = 'expected but could not find key in response: ' + expected_response_field
                return TestResult('EXPECTED_KEY_NOT_FOUND', result_detail)
			if value != expected_response_value:
				result_detail = 'value "' + str(value) + '" does not match expected value "' + str(expected_response_value) + '" in response field "' + expected_response_field + '"'
				return ('EXPECTED_VALUE_NOT_FOUND', result_detail)
		
		return TestResult(result_name, result_detail)


	def expand_macros(self, string):
		res = string
		matcher = re.compile(r'<\w+:[\w\:]+>')
		for macro in matcher.findall(string):
			if DEBUG:
				log('replacing macro ' + macro)
			# strip < and > and turn into array
			macro_chunks = macro[1:-1].split(':')
			# first field is macro class
			macro_class = macro_chunks[0]
			# second field is macro name
			macro_name = macro_chunks[1]
			# rest of fields are macro args
			macro_args = macro_chunks[2:]
			if macro_class == 'test':
				test_name = macro_name
				key = macro_args[0]
				expanded = self.values[test_name][key]
			elif macro_class == 'general':
				try:
					expanded = self.values['cached'][macro_name]
				except:
					expanded = macro_defs[macro_name]()
					self.values['cached'][macro_name] = expanded
			if DEBUG:
				log('expanding macro to: ' + expanded)
			res = res.replace(macro, expanded)
		return res

# macros -- need to organize this better
macro_defs = {
	'rand_email': get_rand_email
	}
