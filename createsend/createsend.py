import urllib
import urllib2
import httplib
import base64
import gzip
from StringIO import StringIO
from urlparse import urlparse
from utils import json_to_py, get_faker

__version_info__ = ('2', '6', '0')
__version__ = '.'.join(__version_info__)

class CreateSendError(Exception):
  """Represents a CreateSend API error and contains specific data about the error."""
  def __init__(self, data):
    self.data = data
  def __str__(self):
    # self.data should contain Code, Message and optionally ResultData
    extra = ("\nExtra result data: %s" % self.data.ResultData) if hasattr(self.data, 'ResultData') else ""
    return "The CreateSend API responded with the following error - %s: %s%s" % (self.data.Code, self.data.Message, extra)

class ClientError(Exception): pass
class ServerError(Exception): pass
class BadRequest(CreateSendError): pass
class Unauthorized(CreateSendError): pass
class NotFound(ClientError): pass
class Unavailable(Exception): pass

class ExpiredOAuthToken(Unauthorized):
  """Raised for HTTP response code of 401, specifically when an OAuth
  token has expired (Code: 121, Message: 'Expired OAuth Token')"""
  pass

class CreateSendBase(object):
  authentication = None
  oauth = None
  api_key = None

  def __init__(self):
    self.fake_web = False

  def reset_auth(self):
    self.oauth = None
    self.api_key = None

  def auth(self, auth):
    """Authenticate with the Campaign Monitor API using either OAuth or
    an API key.

    :param auth: A dictionary representing the authentication scheme to use.
    This dictionary must take either of the following forms:

    {'access_token': 'your access token', 'refresh_token': 'your refresh token'}

    {'api_key': 'your api key'}

    :returns If no auth is specified, returns the current authentication
    data as a dictionary.
    """
    if not auth:
      return self.authentication
    self.reset_auth()
    self.authentication = auth
    if 'api_key' in auth:
      self.api_key = auth['api_key']
    elif 'access_token' in auth:
      access_token = auth['access_token']
      refresh_token = None
      if 'refresh_token' in auth:
        refresh_token = auth['refresh_token']
      self.oauth = {
        'access_token': access_token,
        'refresh_token': refresh_token }

  def stub_request(self, expected_url, filename, status=None, body=None):
    self.fake_web = True
    self.faker = get_faker(expected_url, filename, status, body)

  def make_request(self, method, path, params={}, body="", username=None, password=None):
    headers = {
      'User-Agent': 'createsend-python-%s' % __version__,
      'Content-Type': 'application/json; charset=utf-8',
      'Accept-Encoding' : 'gzip, deflate' }
    parsed_base_uri = urlparse(CreateSend.base_uri)
    """username and password should only be set when it is intended that
    the default basic authentication mechanism using the API key be 
    overridden (e.g. when using the apikey route with username and password)."""
    if username and password:
      headers['Authorization'] = "Basic %s" % base64.b64encode("%s:%s" % (username, password))
    elif (CreateSend.api_key or self.api_key):
      # Allow api_key to be set for a CreateSend instance.
      headers['Authorization'] = "Basic %s" % base64.b64encode("%s:x" % (CreateSend.api_key or self.api_key))
    elif (self.oauth):
      headers['Authorization'] = "Bearer %s" % self.oauth["access_token"]

    self.headers = headers

    """If in fake web mode (i.e. self.stub_request has been called), 
    self.faker should be set, and this request should be treated as a fake."""
    if self.fake_web:
      # Check that the actual url which would be requested matches self.faker.url. 
      actual_url = "http://%s%s" % (parsed_base_uri.netloc, self.build_url(parsed_base_uri, path, params))
      self.faker.actual_url = actual_url
      if self.faker.url != actual_url:
        raise Exception("Faker's expected URL (%s) doesn't match actual URL (%s)" % (self.faker.url, actual_url))

      self.faker.actual_body = body
      if self.faker.body is not None:
        if self.faker.body != body:
          raise Exception("Faker's expected body (%s) doesn't match actual body (%s)" % (self.faker.body, body))
        
      data = self.faker.open() if self.faker else ''
      status = self.faker.status if (self.faker and self.faker.status) else 200
      return self.handle_response(status, data)

    c = httplib.HTTPConnection(parsed_base_uri.netloc)
    c.request(method, self.build_url(parsed_base_uri, path, params), body, headers)
    response = c.getresponse()
    if response.getheader('content-encoding', '') == 'gzip':
      data = gzip.GzipFile(fileobj=StringIO(response.read())).read()
    else:
      data = response.read()
    c.close()
    return self.handle_response(response.status, data)

  def build_url(self, parsed_base_uri, path, params):
    url = parsed_base_uri.path + path
    if params and len(params) > 0:
      url = (url + "?%s" % urllib.urlencode(params))
    return url

  def handle_response(self, status, data):
    if status == 400:
      raise BadRequest(json_to_py(data))
    elif status == 401:
      json_data = json_to_py(data)
      if json_data.Code == 121:
        raise ExpiredOAuthToken(json_data)
      raise Unauthorized(json_data)
    elif status == 404:
      raise NotFound()
    elif status in range(400, 500):
      raise ClientError()
    elif status in range(500, 600):
      raise ServerError()
    return data

  def _get(self, path, params={}, username=None, password=None):
    return self.make_request(path=path, method="GET", params=params, username=username, password=password)

  def _post(self, path, body=""):
    return self.make_request(path=path, method="POST", body=body)

  def _put(self, path, body="", params={}):
    return self.make_request(path=path, method="PUT", params=params, body=body)

  def _delete(self, path, params={}):
    return self.make_request(path=path, method="DELETE", params=params)

class CreateSend(CreateSendBase):
  """Provides high level CreateSend functionality/data you'll probably need."""
  base_uri = "http://api.createsend.com/api/v3"

  def apikey(self, site_url, username, password):
    """Gets your CreateSend API key, given your site url, username and password."""
    # The only case in which username and password are passed to self.get
    params = { "SiteUrl": site_url }
    response = self._get("/apikey.json", params, username, password)
    return json_to_py(response).ApiKey

  def clients(self):
    """Gets your clients."""
    response = self._get('/clients.json')
    return json_to_py(response)

  def billing_details(self):
    """Gets your billing details."""
    response = self._get('/billingdetails.json')
    return json_to_py(response)

  def countries(self):
    """Gets valid countries."""
    response = self._get('/countries.json')
    return json_to_py(response)

  def systemdate(self):
    """Gets the current date in your account's timezone."""
    response = self._get('/systemdate.json')
    return json_to_py(response).SystemDate

  def timezones(self):
    """Gets valid timezones."""
    response = self._get('/timezones.json')
    return json_to_py(response)

  def administrators(self):
  	"""gets administrators associated with the account"""
  	response = self._get('/admins.json')
  	return json_to_py(response)
  
  def get_primary_contact(self):
  	"""retrieves the primary contact for this account"""
  	response = self._get('/primarycontact.json')
  	return json_to_py(response)

  def set_primary_contact(self, email):
    """assigns the primary contact for this account"""
    params = { "email": email }
    response = self._put('/primarycontact.json', params = params)
    return json_to_py(response)
