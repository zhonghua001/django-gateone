# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.shortcuts import render,HttpResponse

# Create your views here.
from django.views.generic import View
from django.shortcuts import render_to_response,HttpResponseRedirect,reverse,redirect
import os
import ast
from django.conf import settings
from applications.utils import generate_session_id,mkdir_p
import tornado
from django.core import signing #encrypted the strings
from django.contrib.auth.views import login,logout

def getsettings(name,default=None):
    return getattr(settings, name, default)

class basehttphander(View):
    def user_login(self,request):
        self.request.session.clear_expired()
        if self.request.META.has_key('HTTP_X_FORWARDED_FOR'):  
            ip = self.request.META['HTTP_X_FORWARDED_FOR']
        else:  
            ip = self.request.META['REMOTE_ADDR']
        user = {u'upn': str(self.request.user), u'ip_address': ip}        
        user_dir = os.path.join(getsettings('BASE_DIR'),'users')
        user_dir = os.path.join(user_dir, user['upn'])
        if not os.path.exists(user_dir):
            mkdir_p(user_dir)
            os.chmod(user_dir, 0o700)
        if not self.request.session.get('session',None):
            session_info = {
                'session': generate_session_id()
            }
            session_info.update(user)
            self.request.session['session'] = session_info['session']
            self.request.session['gateone_user'] = session_info    
    def user_logout(self, request, redirect=None):
        if not redirect:
            # Try getting it from the query string
            redirect = self.request.GET.get("redirect", None)
        if redirect:
            return HttpResponse(redirect)
        else:
            return HttpResponse(getsettings('url_prefix','/'))
            
class index(basehttphander):
    def get(self,request):
        hostname = os.uname()[1]
        location = u'default'
        self.user_login(request)
        response = render_to_response('index.html',locals())
        response["Access-Control-Allow-Origin"] = "*"#set django to cros mode
        expiration = getsettings('auth_timeout', 14*86400) #set django user login session time to 14 day
        if not self.request.COOKIES.get('gateone_user',None):
            response.set_cookie("gateone_user",signing.dumps(self.request.session['gateone_user']))
            self.request.session.set_expiry(expiration)
        return response

class auth(basehttphander):
    """
    Only implemented django user login.
    """
    def get(self,request):
        check = self.request.GET.get('check',False)
        if check in ['true','false',False]:#solve ast malformed string exception
            check = {'true':True,'false':False}[str(check).lower()]
        else:
            check = ast.literal_eval(check)
        if self.request.user == 'AnonymousUser':
            user = {'upn': 'ANONYMOUS'}
        else:
            user = {'upn': str(self.request.user)}
        if check and self.request.user.is_authenticated():
            response = HttpResponse(u'authenticated')
            response["Access-Control-Allow-Origin"] = "*"
            response["Server"] = "GateOne"
            return response
        logout_get = self.request.GET.get("logout", None)
        if logout_get:
            logout(request)
            response = HttpResponse('/')
            response.delete_cookie('gateone_user')            
            self.user_logout(request)
            return response
        next_url = self.request.GET.get("next", None)
        if next_url:
            return redirect(next_url)
        return redirect(getsettings('url_prefix','/'))

class DownloadHandler(basehttphander):
    def get(self, path, include_body=True):
        session_dir = self.settings['session_dir']
        user = self.current_user
        if user and 'session' in user:
            session = user['session']
        else:
            logger.error(_("DownloadHandler: Could not determine use session"))
            return # Something is wrong
        filepath = os.path.join(session_dir, session, 'downloads', path)
        abspath = os.path.abspath(filepath)
        if not os.path.exists(abspath):
            self.set_status(404)
            self.write(self.get_error_html(404))
            return
        if not os.path.isfile(abspath):
            raise tornado.web.HTTPError(403, "%s is not a file", path)
        import stat, mimetypes
        stat_result = os.stat(abspath)
        modified = datetime.fromtimestamp(stat_result[stat.ST_MTIME])
        self.set_header("Last-Modified", modified)
        mime_type, encoding = mimetypes.guess_type(abspath)
        if mime_type:
            self.set_header("Content-Type", mime_type)
        # Set the Cache-Control header to private since this file is not meant
        # to be public.
        self.set_header("Cache-Control", "private")
        # Add some additional headers
        self.set_header('Access-Control-Allow-Origin', '*')
        # Check the If-Modified-Since, and don't send the result if the
        # content has not been modified
        ims_value = self.request.headers.get("If-Modified-Since")
        if ims_value is not None:
            import email.utils
            date_tuple = email.utils.parsedate(ims_value)
            if_since = datetime.fromtimestamp(time.mktime(date_tuple))
            if if_since >= modified:
                self.set_status(304)
                return
        # Finally, deliver the file
        with io.open(abspath, "rb") as file:
            data = file.read()
            hasher = hashlib.sha1()
            hasher.update(data)
            self.set_header("Etag", '"%s"' % hasher.hexdigest())
            if include_body:
                self.write(data)
            else:
                assert self.request.method == "HEAD"
                self.set_header("Content-Length", len(data))

    def get_error_html(self, status_code, **kwargs):
        self.require_setting("static_url")
        if status_code in [404, 500, 503, 403]:
            filename = os.path.join(self.settings['static_url'], '%d.html' % status_code)
            if os.path.exists(filename):
                with io.open(filename, 'r') as f:
                    data = f.read()
                return data
        import httplib
        return "<html><title>%(code)d: %(message)s</title>" \
                "<body class='bodyErrorPage'>%(code)d: %(message)s</body></html>" % {
            "code": status_code,
            "message": httplib.responses[status_code],
        }