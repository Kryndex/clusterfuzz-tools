"""Module for logging tool usage via stackdriver."""
# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import time
import os
import binascii
import sys
import functools
import logging
import traceback

from clusterfuzz import common
from clusterfuzz import local_logging
from httplib2 import Http
from oauth2client.service_account import ServiceAccountCredentials

SESSION_ID = ':'.join([os.environ.get('USER'),
                       str(time.time()),
                       str(binascii.b2a_hex(os.urandom(20)))])
logger = logging.getLogger('clusterfuzz')

def get_session_id():
  """For easier testing/mocking."""

  return SESSION_ID


def send_log(params, stacktrace=None):
  """Joins the params dict with info like user id and then sends logs."""

  scopes = ['https://www.googleapis.com/auth/logging.write']
  filename = common.get_resource(
      0640, 'resources', 'clusterfuzz-tools-logging.json')

  credentials = ServiceAccountCredentials.from_json_keyfile_name(
      filename, scopes=scopes)

  http_auth = credentials.authorize(Http())

  params['version'] = common.get_version()
  params['user'] = os.environ.get('USER')
  params['sessionId'] = get_session_id()
  if 'success' in params:
    prefix = ('successfully finished' if params['success'] else
              'unsuccessfully finished')
  else:
    prefix = 'started'
  params['message'] = ('%s %s running %s with testcase=%s, build_type=%s, '
                       'current=%s, and goma=%s' % (
                           params['user'], prefix, params['command'],
                           params['testcaseId'], params['buildType'],
                           params['current'],
                           'disabled' if params['disableGoma'] else 'enabled'))
  if stacktrace:
    params['message'] += '\n%s' % stacktrace

  structure = {
      'logName': 'projects/clusterfuzz-tools/logs/client',
      'resource': {
          'type': 'project',
          'labels': {
              'project_id': 'clusterfuzz-tools'}},
      'entries': [{
          'jsonPayload': params,
          'severity': 'ERROR' if stacktrace else 'INFO'}]}

  http_auth.request(
      uri='https://logging.googleapis.com/v2/entries:write',
      method='POST',
      body=json.dumps(structure))


def make_basic_params(command, testcase_id, build, current, disable_goma, j,
                      iterations, disable_xvfb, target_args, edit_mode):
  """Creates the basic paramater dict."""

  return {'testcaseId': testcase_id,
          'buildType': build,
          'current': current,
          'command': command,
          'disableGoma': disable_goma,
          'j': j,
          'iterations': iterations,
          'disableXvfb': disable_xvfb,
          'targetArgs': target_args,
          'editMode': edit_mode}


def send_start(**kwargs):
  """Sends the basic testcase details to show a run has started."""

  send_log(make_basic_params(**kwargs))


def send_success(**kwargs):
  """Sends a success message to show the reproduction completed."""

  params = make_basic_params(**kwargs)
  params['success'] = True
  send_log(params)


def send_failure(exception_name, stacktrace, **kwargs):
  """Sends a log with success set to False."""

  params = make_basic_params(**kwargs)
  params['exception'] = exception_name
  params['success'] = False
  send_log(params, stacktrace)


def log(func):
  """Log to stackdriver at the start & end of a command."""
  @functools.wraps(func)
  def wrapped(*args, **kwargs):
    command_name = func.__module__.split('.')[-1]
    try:
      try:
        send_start(*args, command=command_name, **kwargs)
        func(*args, **kwargs)
        send_success(*args, command=command_name, **kwargs)
      except BaseException as e:
        send_failure(e.__class__.__name__, traceback.format_exc(), *args,
                     command=command_name, **kwargs)
        raise
    except (KeyboardInterrupt, common.ExpectedException) as e:
      logger.info('%s: %s', e.__class__.__name__, e.message)
      sys.exit(1)
    finally:
      print ('\nDetailed log of this run can be found in: %s' %
             local_logging.LOG_FILE_PATH)
  return wrapped
