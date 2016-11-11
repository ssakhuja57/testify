from RestHelper import RestHelper
import json
import os
import time
import datetime
from jsonconv import *
import re
import copy
import abc
import traceback
from subprocess import Popen, PIPE

# constants
DEBUG_LEVEL = 0
TIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
DEFAULT_TASK_TYPE = 'http'

# helpers
def log(msg):
	print '-- ' + msg

def debug(msg, lvl=1):
    if DEBUG_LEVEL >= lvl:
        log(msg)

def run_cmd(cmd):
    cmd_list = cmd.split(' ')
    debug('running cmd: ' + str(cmd_list))
    p = Popen(cmd_list, stdout=PIPE)
    output = p.communicate()[0]
    return p.returncode, output

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
	return int((t2 - t1).microseconds/1000)

def results_to_html(results):
    res_cp = copy.deepcopy(results)
    for result in res_cp['task-results']:
        result_name = result['result']
        result_attr = TaskResult.results[result_name]
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

def get_task(task_type):
    for t in Task.__subclasses__():
        if t.__name__ == task_type:
            return t
    return None

# task

class Task(object):

    __metaclass__ = abc.ABCMeta

    required_fields_general = ['name', 'description']

    def __init__(self, cfg):
        try:
            self.name = cfg['name']
            self.host_index = cfg.get('host-index', 0)
            self.description = cfg['description']
            self.enabled = cfg.get('enabled', True)
            self.instances = cfg.get('instances', 1)
        except KeyError:
            raise ValueError('the following are required for all task definitons: ' + ','.join(self.required_fields_general))
        self.start_time, self.end_time = None, None

        # check task specific required fields
        for f in self.required_fields:
            if f not in cfg:
                raise ValueError('the following are required for all ' + self.__name__ + ' task definitions: ' + ','.join(self.required_fields))

    @abc.abstractproperty
    def required_fields(self):
        return

    @abc.abstractmethod
    def run(self, host, runtime):
        return

    def start(self):
        self.start_time = get_current_time()

    def end(self):
        self.end_time = get_current_time()

# task implementations

class docker_exec(Task):

    def __init__(self, cfg):
        Task.__init__(self, cfg)

        self.command = cfg['command']
        self.privileged = cfg.get('privileged', False)
        self.user = cfg.get('user', None)

    @property
    def required_fields(self):
        return ['command']

    def run(self, host, runtime):
        command = runtime.expand_macros(self.command)
        options = ''
        if self.user is not None:
            options += ' --user ' + self.user
        if self.privileged:
            options += ' --privileged'
        
        full_cmd = 'docker exec' + options + ' ' + host.cfg['container-name'] + ' ' + command
        debug('running command: ' + full_cmd)

        self.start()
        res = run_cmd(full_cmd)
        self.end()

        ret = res[0]
        if ret == 0:
            return TaskResult(TaskResult.SUCCESS, 'OK')
        else:
            return TaskResult(TaskResult.UNCLASSIFIED_ERROR, res[1])

class http(Task):
    def __init__(self, cfg): 
        Task.__init__(self, cfg)

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
            raise ValueError('cannot define a task with multiple instances and a save-field')
		
        debug('task definition object created: ' + str(vars(self)))

    @property
    def required_fields(self):
        return []

    def run(self, host, runtime):
        debug('preparing to run task: ' + self.name)
        name = self.name
        uri = runtime.expand_macros(self.uri)
        method = self.method
        data = runtime.expand_macros(self.data)
        content_type = self.content_type
        expected_status_lower = self.expected_status_lower
        expected_status_upper = self.expected_status_upper
        auth = runtime.expand_macros(self.auth)

        debug('running http task ' + name + ': uri ' + uri + ', method ' + method + ', auth ' + auth + ', data ' + data + ', expected status ' + str(self.expected_status_range))

        self.start()
        for i in range(self.instances):
            if host.name not in runtime.values:
                hostname = host.cfg['hostname']
                port = host.cfg.get('port', None)
                secure = host.cfg.get('secure', False)
                check_cert = host.cfg.get('check-cert', True)
                runtime.values[host.name] = RestHelper(hostname, port, secure, check_cert=check_cert)
            restHelper = runtime.values[host.name]
            response = restHelper.request(method, uri, data=data, content_type=content_type, auth=auth)
        self.end()

        if not expected_status_lower <= response.status <= expected_status_upper:
            result_detail = 'expected status ' + str(self.expected_status_range) + ', got ' + str(response.status) + ', response: ' + response.read()
            return TaskResult(TaskResult.UNEXPECTED_HTTP_STATUS, result_detail)

        try:
            response_json = json.loads(response.read())
        except:
            response_json = None

        debug('response: ' + str(response_json))

        save_field = self.save_field
        if save_field is not None:
            debug('saving value for response field ' + save_field)
            value = xpath_get(response_json, save_field)
            if value is None:
                result_detail = 'expected but could not find key in response: ' + save_field
                return TaskResult(TaskResult.EXPECTED_KEY_NOT_FOUND, result_detail)
            runtime.save_value(self, save_field, value)

        expected_response_field = self.expected_response_field
        if expected_response_field is not None:
            expected_response_value = runtime.expand_macros(self.expected_response_value)
            debug('looking for value ' + expected_response_value)
            value = xpath_get(response_json, expected_response_field)
            if value is None:
                result_detail = 'expected but could not find key in response: ' + expected_response_field
                return TaskResult(TaskResult.EXPECTED_KEY_NOT_FOUND, result_detail)
            if value != expected_response_value:
                result_detail = 'value "' + str(value) + '" does not match expected value "' + str(expected_response_value) + '" in response field "' + expected_response_field + '"'
                return (TaskResult.EXPECTED_VALUE_NOT_FOUND, result_detail)

        return TaskResult(TaskResult.SUCCESS, 'OK')


class TaskResult(object):
    SKIPPED = {'name': 'SKIPPED', 'code': -1, 'color': '#0000CD'}
    SUCCESS = {'name': 'SUCCESS', 'code': 0, 'color': 'green'}
    UNEXPECTED_HTTP_STATUS = {'name': 'UNEXPECTED_HTTP_STATUS', 'code': 1, 'color': 'red'}
    EXPECTED_KEY_NOT_FOUND = {'name': 'EXPECTED_KEY_NOT_FOUND', 'code': 2, 'color': 'red'}
    EXPECTED_VALUE_NOT_FOUND = {'name': 'EXPECTED_VALUE_NOT_FOUND', 'code': 3, 'color':'red'}
        # add more results here
    UNCLASSIFIED_ERROR = {'name': 'UNCLASSIFIED_ERROR', 'code': 8675309, 'color': 'red'}
    
    def __init__(self, result, detail):		
        self.result = result
        self.result_name = result['name']
        self.code = result['code']
        self.detail = detail
        debug('task result created with: ' + str(vars(self)))

class Routine(object):
    def __init__(self, cfg):
        self.name = cfg['name']
        self.tasks = []
        debug('creating routine from task definitions')
        for task in cfg['tasks']:
            task_type = task.get('task-type', DEFAULT_TASK_TYPE)
            task_class = get_task(task_type)
            if task_class is None:
                raise ValueError('unrecognized task-type: ' + task_type)
            self.tasks.append(task_class(task))

class Host(object):
    def __init__(self, cfg):
        self.name = cfg['name']
        self.cfg = cfg
        debug('host definition object created: ' + str(vars(self)))

class HostSet(object):
    def __init__(self, cfg):
        self.name = cfg['name']
        self.hosts = []
        for host_cfg in cfg['hosts']:
            self.hosts.append(Host(host_cfg))

class Runner(object):
    def __init__(self, host_set, routine):
		# dictionary to store any values returned from tasks
        self.runtime = Runtime()
        self.host_set = host_set
        self.routine = routine

    def run(self):
        task_results = {
            'timestamp': get_current_time().strftime(TIME_FORMAT),
            'host-set': self.host_set.name,
            'routine': self.routine.name,
            'hosts': ','.join([host.name for host in self.host_set.hosts]),
            'tasks-passed': 0,
            'tasks-failed': 0,
            'task-results': []
       	    }
        for task in self.routine.tasks:
            if task.enabled:
                try:
                    host = self.host_set.hosts[task.host_index]
                    result = task.run(host, self.runtime)
                except Exception as e:
                    traceback.print_exc()
                    result = TaskResult(TaskResult.UNCLASSIFIED_ERROR, 'Task Exception: ' + str(e))
            else:
                result = TaskResult(TaskResult.SKIPPED, 'Task marked as disabled')
            # evaluate result
            if result.code == 0:
                task_results['tasks-passed'] += 1
                passed = True
            elif result.code > 0:
                task_results['tasks-failed'] += 1
                passed = False
            else:
                passed = False

            start_time = 'N/A' if task.start_time is None else task.start_time.strftime(TIME_FORMAT)
            time_diff_ms = 'N/A' if (task.start_time is None or task.end_time is None) else get_time_diff(task.start_time, task.end_time)

            task_summary = {'name': task.name,
                            'type': task.__class__.__name__,
	                        'description': task.description,
                            'instances': task.instances,
                            'host-index': task.host_index,
        	                #'status_code': result.status_code,
                            'result': result.result_name,
                            'result-detail': result.detail,
                        	'task-start': start_time, 
	                        'task-duration-ms': time_diff_ms
        	                }
            task_results['task-results'].append(task_summary)
		
        return task_results


class Runtime(object):

    macro_defs = {
        'rand_email': get_rand_email
    }

    def __init__(self):
        self.values = {'cached': {}}

    def save_value(task, key, value):
        debug('saving value ' + str(value) + ' for key ' + key + ' for task ' + task.name)
        if task.name in self.values:
            self.values[task.name][key] = value
        else:
            self.values[task.name] = {key: value}        

    def expand_macros(self, string):
        debug('expanding string: ' + string)
        res = string
        matcher = re.compile(r'<\w+:[\w\:]+>')
        for macro in matcher.findall(string):
            debug('replacing macro ' + macro)
            # strip < and > and turn into array
            macro_chunks = macro[1:-1].split(':')
            # first field is macro class
            macro_class = macro_chunks[0]
            # second field is macro name
            macro_name = macro_chunks[1]
            # rest of fields are macro args
            macro_args = macro_chunks[2:]
            if macro_class == 'task':
                task_name = macro_name
                key = macro_args[0]
                expanded = self.values[task_name][key]
            elif macro_class == 'general':
                try:
                    expanded = self.values['cached'][macro_name]
                except KeyError:
                    expanded = self.macro_defs[macro_name]()
                    self.values['cached'][macro_name] = expanded
            debug('expanding macro to: ' + expanded)
            res = res.replace(macro, expanded)
        debug('string expanded to: ' + res)
        return res

if __name__ == '__main__':

    routine_cfg = json.load(open(sys.argv[1]))
    host_set_cfg = json.load(open(sys.argv[2]))
    routine = Routine(routine_cfg)
    host_set = HostSet(host_set_cfg)
    res = Runner(host_set, routine).run()
    print json.dumps(res, indent=4)
    sys.exit(res['tasks-failed'])
