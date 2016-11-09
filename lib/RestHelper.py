import httplib
import json
import ssl

class RestHelper(object):

    def __init__(self, host, port, secure, check_cert=False, auth=None):
        self.host = host
        self.port = port
        self.secure = secure
	self.check_cert = check_cert
	self.auth = auth

    def set_auth(self, auth):
	self.auth = auth
	
    def request(self, method, uri, data=None, content_type='application/json', headers={}, auth='default', timeout=60):
        if self.secure:
		if self.check_cert:
            		conn = httplib.HTTPSConnection(self.host, self.port, timeout=timeout)
		else:
			conn = httplib.HTTPSConnection(self.host, self.port, context=ssl._create_unverified_context(), timeout=timeout)
        else:
		conn = httplib.HTTPConnection(self.host, self.port, timeout=timeout)
	
	auth = self.auth if auth == 'default' else auth

	headers['Authorization'] = auth
		
	headers['Content-type'] = content_type

        conn.request(method, uri, data, headers=headers)
        return conn.getresponse()

