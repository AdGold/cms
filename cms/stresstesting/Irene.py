#!/usr/bin/python
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2010-2011 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2011 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2011 Matteo Boscariol <boscarim@hotmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import sys
import urllib
import urllib2
import cookielib
import mechanize
import threading
import optparse
import random
import time
import re
import email.mime.multipart
import email.mime.nonmultipart

from cms.db.SQLAlchemyAll import Contest, SessionGen


def urlencode(data):
    msg = email.mime.multipart.MIMEMultipart('form-data')
    for key, value in data.iteritems():
        elem = email.mime.nonmultipart.MIMENonMultipart('text', 'plain')
        elem.add_header('Contest-Disposition', 'form-data; name="%s"' % (key))
        elem.set_payload(value)
        msg.attach(elem)
    return msg

class HTTPHelper:
    """A class to emulate a browser's behaviour: for example, cookies
    get automatically accepted, stored and sent with subsequent
    requests.

    """

    def __init__(self):
        self.cookies = cookielib.CookieJar()
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookies))

    def do_request(self, url, data=None):
        """Request the specified URL.

        url (string): the URL to request; the protocol is detected
        from the URL.
        data (dict): the data to sent with the URL; used when an
                     HTTP(S) request is performed: if data is None, a
                     plain GET request is performed. Otherwise a POST
                     request is performed, with the attached data.
        returns: the response; it is a file-like objects that the
                 consumer can read; is also supports other methods,
                 described in the documentation of urllib2.urlopen().

        """
        if data is None:
            request = urllib2.Request(url)
        else:
            request = urllib2.Request(url, urllib.urlencode(data))
        response = self.opener.open(request)
        return response

class RequestLog:

    total = 0
    successes = 0
    failures = 0
    errors = 0
    undecided = 0

    tests = []

    def add_test(self, data):
        self.tests.append((time.time(), data))

    def print_stats(self):
        print >> sys.stderr, "TOTAL:       %5d" % (self.total)
        print >> sys.stderr, "SUCCESS:     %5d" % (self.successes)
        print >> sys.stderr, "FAIL:        %5d" % (self.failures)
        print >> sys.stderr, "ERROR:       %5d" % (self.errors)
        print >> sys.stderr, "UNDECIDED:   %5d" % (self.undecided)

class TestRequest:

    def __init__(self, browser, base_url=None):
        if base_url is None:
            base_url = 'http://localhost:8888/'
        self.browser = browser
        self.base_url = base_url

    def execute(self, log=None):
        if log is not None:
            log.total += 1
        description = self.describe()
        try:
            self.do_request()
            success = self.test_success()
        except Exception as e:
            print >> sys.stderr, "Request '%s' terminated with an exception" % (description)
            if log is not None:
                log.errors += 1
                log.add_test(self.get_test_data())
        else:
            if success is None:
                print >> sys.stderr, "Could not determine status for request '%s'" % (description)
                if log is not None:
                    log.undecided += 1
                    log.add_test(self.get_test_data())
            elif success:
                print >> sys.stderr, "Request '%s' successfully completed" % (description)
                if log is not None:
                    log.successes += 1
                    log.add_test(self.get_test_data())
            elif not success:
                print >> sys.stderr, "Request '%s' failed" % (description)
                if log is not None:
                    log.failures += 1
                    log.add_test(self.get_test_data())

    def describe(self):
        raise NotImplemented("Please subclass this class and actually implement some request")

    def do_request(self):
        raise NotImplemented("Please subclass this class and actually implement some request")

    def test_success(self):
        raise NotImplemented("Please subclass this class and actually implement some request")

    # TODO - Implement in subclasses
    def get_test_data(self):
        return None

class GenericRequest(TestRequest):

    MINIMUM_LENGTH = 100

    def __init__(self, browser, base_url=None):
        TestRequest.__init__(self, browser, base_url)
        self.url = None
        self.data = None

    def do_request(self):
        if self.data is None:
            self.response = self.browser.open(self.url)
        else:
            self.response = self.browser.open(self.url, urllib.urlencode(self.data))
        self.res_data = self.response.read()

    def test_success(self):
        #if self.response.getcode() != 200:
        #    return False
        if len(self.res_data) < GenericRequest.MINIMUM_LENGTH:
            return False
        return True

class HomepageRequest(GenericRequest):

    def __init__(self, http_helper, username, loggedin, base_url=None):
        GenericRequest.__init__(self, http_helper, base_url)
        self.url = self.base_url
        self.username = username
        self.loggedin = loggedin

    def describe(self):
        return "check the main page"

    def test_success(self):
        if not GenericRequest.test_success(self):
            return False
        username_re = re.compile(self.username)
        if self.loggedin:
            if username_re.search(self.res_data) is None:
                return False
        else:
            if username_re.search(self.res_data) is not None:
                return False
        return True

class LoginRequest(GenericRequest):

    def __init__(self, http_helper, username, password, base_url=None):
        TestRequest.__init__(self, http_helper, base_url)
        self.username = username
        self.password = password
        self.url = self.base_url + 'login'
        self.data = {'username': self.username, 'password': self.password, 'next': '/'}

    def describe(self):
        return "try to login"

    def test_success(self):
        if not GenericRequest.test_success(self):
            return False
        fail_re = re.compile('Failed to log in.')
        if fail_re.search(self.res_data) is not None:
            return False
        username_re = re.compile(self.username)
        if username_re.search(self.res_data) is None:
            return False
        return True

class ActorDying(Exception):
    pass

class Actor(threading.Thread):
    """Class that simulates the behaviour of a user of the system. It
    performs some requests at randomized times (checking CMS pages,
    doing submissions, ...), checking for their success or failure.

    The probability that the users doing actions depends on the value
    specified in an object called "metrics".

    """

    def __init__(self, username, password, metrics, tasks, log=None):
        threading.Thread.__init__(self)

        self.username = username
        self.password = password
        self.metric = metrics
        self.tasks = tasks
        self.log = log

        self.name = "Actor thread for user %s" % (self.username)

        self.browser = mechanize.Browser()
        self.die = False

    def run(self):
        try:
            print >> sys.stderr, "Starting actor for user %s" % (self.username)
            self.do_step(HomepageRequest(self.browser, self.username, loggedin=False))
            self.do_step(LoginRequest(self.browser, self.username, self.password))
            self.do_step(HomepageRequest(self.browser, self.username, loggedin=True))
        except ActorDying:
            print >> sys.stderr, "Actor dying for user %s" % (self.username)

    def do_step(self, request):
        self.wait_next()
        if self.die:
            raise ActorDying()
        request.execute(self.log)

    def wait_next(self):
        """Wait some time. At the moment it waits c*X seconds, where c
        is the time_coeff parameter in metrics and X is an
        exponentially distributed random variable, with parameter
        time_lambda in metrics.

        """
        time_to_wait = self.metric['time_coeff'] * random.expovariate(self.metric['time_lambda'])
        time.sleep(time_to_wait)

def harvest_contest_data(contest_id):
    users = {}
    tasks = []
    with SessionGen() as session:
        c = Contest.get_from_id(contest_id, session)
        for u in c.users:
            users[u.username] = {'password': u.password}
        for t in c.tasks:
            tasks.append(t.name)
    return users, tasks

DEFAULT_METRICS = {'time_coeff':  1.0,
                   'time_lambda': 2.0}

def main():
    parser = optparse.OptionParser(usage="usage: %prog [options]")
    parser.add_option("-c", "--contest", help="contest ID to export",
                      dest="contest_id", action="store", type="int", default=None)
    parser.add_option("-n", "--actor-num", help="the number of actors to spawn",
                      dest="actor_num", action="store", type="int", default=None)
    options, args = parser.parse_args()

    users, tasks = harvest_contest_data(options.contest_id)
    if options.actor_num is not None:
        user_items = users.items()
        random.shuffle(user_items)
        users = dict(user_items[:options.actor_num])

    log = RequestLog()
    actors = [Actor(username, data['password'], DEFAULT_METRICS, tasks, log)
              for username, data in users.iteritems()]
    for a in actors:
        a.start()

    finished = False
    while not finished:
        try:
            for a in actors:
                a.join()
            else:
                finished = True
        except KeyboardInterrupt:
            print >> sys.stderr, "Taking down actors"
            for a in actors:
                a.die = True

    print >> sys.stderr, "Test finished"

    log.print_stats()

if __name__ == '__main__':
    main()